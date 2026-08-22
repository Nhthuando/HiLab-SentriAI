"""
tests/test_area_pipeline.py — Comprehensive Unit & Pipeline Test Suite for VS-AREA-VIOLATION

Tests:
1. Polygon containment & normalization (parse_polygon, covers, boundaries)
2. Bottom-center point computation
3. Zone Rule Matrix (PROHIBIT_SPECIFIED, ALLOW_SPECIFIED, unmapped classes)
4. Candidate label resolution & Vietnamese accent preservation
5. Violation State Machine (STARTED, anti-spam suppression, 3-frame grace period, ENDED)
6. Sub-second transition handling
7. ZoneSynchronizer snapshot generation & immutability
8. AreaPipeline frame processing & formatted feed output
"""
import os
import sys
import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

# Ensure python-worker directory is on sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

import cv2
import numpy as np
from shapely.geometry import Point

from buffer.circular_buffer import CircularBuffer
from detection.area_pipeline import AreaPipeline
from detection.detector import COCO_VIETNAMESE_MAPPING
from detection.tracked_detector import TrackedYoloDetector
from stream.reader import StreamReader
from zone.zone_checker import (
    ActiveViolation,
    ViolationTransition,
    ZoneChecker,
    choose_display_label,
    evaluate_zone_rule,
    get_detection_bottom_center,
    parse_polygon,
    resolve_candidate_labels,
)
from zone.zone_sync import ZoneSnapshot, ZoneSynchronizer


class TestZonePolygonAndPoints(unittest.TestCase):
    def test_parse_polygon_valid(self):
        # Array of {"x": ..., "y": ...}
        points_dict = [
            {"x": 0.1, "y": 0.1},
            {"x": 0.5, "y": 0.1},
            {"x": 0.5, "y": 0.5},
            {"x": 0.1, "y": 0.5},
        ]
        poly = parse_polygon(points_dict)
        self.assertIsNotNone(poly)
        self.assertTrue(poly.is_valid)

        # Array of [[x, y], ...]
        points_list = [[0.1, 0.1], [0.5, 0.1], [0.5, 0.5], [0.1, 0.5]]
        poly2 = parse_polygon(points_list)
        self.assertIsNotNone(poly2)
        self.assertTrue(poly2.is_valid)

    def test_parse_polygon_invalid(self):
        # Less than 3 points
        self.assertIsNone(parse_polygon([{"x": 0.1, "y": 0.1}, {"x": 0.5, "y": 0.1}]))
        # Invalid data structure
        self.assertIsNone(parse_polygon("not a polygon"))
        self.assertIsNone(parse_polygon([]))
        self.assertIsNone(parse_polygon(None))

    def test_polygon_covers_boundary(self):
        poly = parse_polygon([
            {"x": 0.0, "y": 0.0},
            {"x": 1.0, "y": 0.0},
            {"x": 1.0, "y": 1.0},
            {"x": 0.0, "y": 1.0},
        ])
        # Interior point
        self.assertTrue(poly.covers(Point(0.5, 0.5)))
        # Boundary point
        self.assertTrue(poly.covers(Point(1.0, 0.5)))
        self.assertTrue(poly.covers(Point(0.0, 0.0)))
        # Outside point
        self.assertFalse(poly.covers(Point(1.1, 0.5)))

    def test_bottom_center_computation(self):
        norm_bbox = [0.2, 0.1, 0.4, 0.7]
        px, py = get_detection_bottom_center(norm_bbox)
        self.assertAlmostEqual(px, 0.3)
        self.assertAlmostEqual(py, 0.7)


class TestZoneRuleMatrix(unittest.TestCase):
    def test_prohibit_specified_rule(self):
        target = ["Xe máy", "Xe đạp"]
        # Match prohibited
        self.assertEqual(evaluate_zone_rule("PROHIBIT_SPECIFIED", target, ["Xe máy"]), "VIOLATION")
        self.assertEqual(evaluate_zone_rule("PROHIBIT_SPECIFIED", target, ["xe máy"]), "VIOLATION")
        # Allowed
        self.assertEqual(evaluate_zone_rule("PROHIBIT_SPECIFIED", target, ["Xe tải"]), "ALLOWED")
        self.assertEqual(evaluate_zone_rule("PROHIBIT_SPECIFIED", target, ["CHƯA XÁC ĐỊNH"]), "ALLOWED")

    def test_allow_specified_rule(self):
        target = ["Xe nâng", "Xe container"]
        # Match allowed
        self.assertEqual(evaluate_zone_rule("ALLOW_SPECIFIED", target, ["Xe nâng"]), "ALLOWED")
        # Violation for non-matching
        self.assertEqual(evaluate_zone_rule("ALLOW_SPECIFIED", target, ["Xe máy"]), "VIOLATION")
        # Unknown object in ALLOW_SPECIFIED is a VIOLATION (BR-04)
        self.assertEqual(evaluate_zone_rule("ALLOW_SPECIFIED", target, ["CHƯA XÁC ĐỊNH"]), "VIOLATION")

    def test_candidate_resolution(self):
        class_map = {
            "motorcycle": ["Xe máy điện", "Xe máy số"],
            "car": ["Xe ô tô 4 chỗ"],
        }
        # Known in DB
        res1 = resolve_candidate_labels("motorcycle", "Xe máy", class_map)
        self.assertEqual(res1, ["Xe máy điện", "Xe máy số"])

        # A model class without a DB mapping and without translated label remains unknown
        res2 = resolve_candidate_labels("truck", "truck", class_map)
        self.assertEqual(res2, ["CHƯA XÁC ĐỊNH"])

        # Completely unknown
        res3 = resolve_candidate_labels("alien_vehicle", "", class_map)
        self.assertEqual(res3, ["CHƯA XÁC ĐỊNH"])

    def test_choose_display_label(self):
        candidates = ["Xe máy", "Xe máy điện"]
        # Prefer matching target
        lbl = choose_display_label(candidates, ["Xe máy điện"])
        self.assertEqual(lbl, "Xe máy điện")
        # Fallback to first
        lbl2 = choose_display_label(candidates, ["Xe tải"])
        self.assertEqual(lbl2, "Xe máy")


class TestCandidateLabelPriority(unittest.TestCase):
    class _FakeTensor:
        def __init__(self, value):
            self.value = value

        def cpu(self):
            return self

        def numpy(self):
            return np.array(self.value)

    class _FakeScalar:
        def __init__(self, value):
            self.value = value

        def item(self):
            return self.value

    class _FakeBoxes:
        def __init__(self, box, cls_id=0, conf=0.82):
            self.xyxy = [TestCandidateLabelPriority._FakeTensor(box)]
            self.cls = [TestCandidateLabelPriority._FakeScalar(cls_id)]
            self.conf = [TestCandidateLabelPriority._FakeScalar(conf)]

        def __len__(self):
            return len(self.xyxy)

    class _FakeResult:
        def __init__(self, box, cls_id=0, conf=0.82):
            self.boxes = TestCandidateLabelPriority._FakeBoxes(box, cls_id, conf)

    class _FakeCustomModel:
        names = {0: "Xe nang"}

        def __call__(self, *_args, **_kwargs):
            return [TestCandidateLabelPriority._FakeResult([60, 90, 310, 210])]

    def _retention_detector(self):
        detector = TrackedYoloDetector.__new__(TrackedYoloDetector)
        detector._retained_detections = {}
        detector._retention_frame_index = 0
        detector._retention_next_synthetic_track_id = -1
        detector._retention_frames = 2
        detector._retention_seconds = 0.0
        detector._box_smoothing_alpha = 0.0
        return detector

    def _custom_gate_detector(self):
        detector = TrackedYoloDetector.__new__(TrackedYoloDetector)
        detector._custom_evidence = {}
        detector._custom_evidence_next_id = 1
        detector._custom_frame_index = 0
        detector._custom_promote_confidence = 0.52
        detector._custom_instant_confidence = 0.86
        detector._custom_confirm_frames = 2
        detector._custom_confirm_window = 6
        detector._custom_confirm_window_seconds = 2.5
        detector._reach_stacker_min_aspect = 0.85
        detector._reach_stacker_narrow_min_confidence = 0.92
        detector._reach_stacker_max_area_ratio = 0.20
        detector._reach_stacker_custom_only_compact_aspect = 1.65
        detector._reach_stacker_custom_only_large_area_ratio = 0.035
        detector._reach_stacker_custom_only_compact_min_confidence = 0.80
        detector._reach_stacker_target_compact_aspect = 1.65
        detector._reach_stacker_target_compact_min_confidence = 0.92
        detector._reach_stacker_long_aspect = 1.75
        detector._reach_stacker_long_max_area_ratio = 0.06
        detector._reach_stacker_long_min_confidence = 0.32
        detector._custom_tile_enabled = True
        detector._custom_tile_size = 640
        detector._custom_tile_overlap = 0.25
        detector._custom_tile_max_tiles = 16
        detector._custom_crop_enabled = True
        detector._custom_crop_max_targets = 6
        detector._custom_crop_padding = 0.45
        return detector

    def test_verified_candidate_replaces_old_generic_track_vote(self):
        """A passed custom model must not be displayed as a stale truck/car label."""
        detector = TrackedYoloDetector.__new__(TrackedYoloDetector)
        detector._track_class_history = {}
        detector._track_last_seen = {}
        detector._tracking_frame_index = 0

        first = detector._stabilize_track_classes([{
            "trackId": 17,
            "class": "truck",
            "label": "Xe tải",
            "confidence": 0.92,
        }])
        self.assertEqual(first[0]["label"], "Xe tải")

        refined = detector._stabilize_track_classes([{
            "trackId": 17,
            "class": "forklift",
            "label": "Xe nâng",
            "confidence": 0.76,
            "candidateVersion": "custom-verified",
        }])
        self.assertEqual(refined[0]["class"], "forklift")
        self.assertEqual(refined[0]["label"], "Xe nâng")

    def test_full_frame_custom_candidate_relabels_base_vehicle(self):
        detector = TrackedYoloDetector.__new__(TrackedYoloDetector)
        detector._custom_model = self._FakeCustomModel()
        detector._custom_version_key = "custom-test"
        detector._custom_label_map = {"Xe nang": "reach stacker"}
        detector._custom_track_overrides = {}
        detector._custom_frame_index = 0
        detector._custom_confidence = 0.30
        detector._custom_interval = 1
        detector._custom_full_frame = True
        detector._custom_match_overlap = 0.10
        detector._custom_full_frame_size = 640
        detector._custom_tile_enabled = False
        detector._custom_tile_size = 640
        detector._custom_tile_overlap = 0.25
        detector._custom_tile_max_tiles = 6
        detector._custom_crop_enabled = False
        detector._custom_crop_max_targets = 0
        detector._custom_crop_padding = 0.45
        detector._custom_evidence = {}
        detector._custom_evidence_next_id = 1
        detector._custom_promote_confidence = 0.52
        detector._custom_instant_confidence = 0.86
        detector._custom_confirm_frames = 1
        detector._custom_confirm_window = 6
        detector._reach_stacker_min_aspect = 0.85
        detector._reach_stacker_narrow_min_confidence = 0.92
        detector._reach_stacker_max_area_ratio = 0.20
        detector._reach_stacker_custom_only_compact_aspect = 1.65
        detector._reach_stacker_custom_only_large_area_ratio = 0.035
        detector._reach_stacker_custom_only_compact_min_confidence = 0.80
        detector._reach_stacker_target_compact_aspect = 1.65
        detector._reach_stacker_target_compact_min_confidence = 0.92
        detector._reach_stacker_long_aspect = 1.75
        detector._reach_stacker_long_max_area_ratio = 0.06
        detector._reach_stacker_long_min_confidence = 0.32
        detector.device = "cpu"

        detections = [{
            "trackId": 7,
            "bbox": [120, 120, 180, 180],
            "normalized_bbox": [0.188, 0.25, 0.281, 0.375],
            "class": "truck",
            "label": COCO_VIETNAMESE_MAPPING["truck"],
            "confidence": 0.91,
            "source": "primary",
        }]

        refined = detector._apply_custom_augmentation(
            np.zeros((480, 640, 3), dtype=np.uint8),
            detections,
            640,
            480,
        )

        self.assertEqual(len(refined), 1)
        self.assertEqual(refined[0]["class"], "reach stacker")
        self.assertEqual(refined[0]["label"], "Xe nang")
        self.assertEqual(refined[0]["source"], "custom")
        self.assertEqual(refined[0]["candidateVersion"], "custom-test")
        self.assertEqual(refined[0]["bbox"], [60, 90, 310, 210])

    def test_cross_class_nms_prefers_custom_candidate_over_base_duplicate(self):
        keep = TrackedYoloDetector._cross_class_nms([
            {
                "bbox": [80, 90, 260, 210],
                "class": "reach stacker",
                "label": "Xe nang",
                "confidence": 0.76,
                "source": "custom",
                "candidateVersion": "custom-test",
            },
            {
                "bbox": [110, 110, 250, 205],
                "class": "truck",
                "label": COCO_VIETNAMESE_MAPPING["truck"],
                "confidence": 0.92,
                "source": "primary",
            },
        ])

        self.assertEqual(len(keep), 1)
        self.assertEqual(keep[0]["class"], "reach stacker")

    def test_cross_class_nms_prefers_truck_over_ambiguous_world_duplicate(self):
        keep = TrackedYoloDetector._cross_class_nms([
            {
                "bbox": [100, 100, 240, 220],
                "class": "personnel carrier",
                "label": "Xe cho nguoi",
                "confidence": 0.90,
                "source": "primary",
            },
            {
                "bbox": [110, 105, 245, 225],
                "class": "truck",
                "label": COCO_VIETNAMESE_MAPPING["truck"],
                "confidence": 0.84,
                "source": "primary",
            },
        ])

        self.assertEqual(len(keep), 1)
        self.assertEqual(keep[0]["class"], "truck")

    def test_ambiguous_world_vehicle_is_canonicalized_to_truck(self):
        detector = TrackedYoloDetector.__new__(TrackedYoloDetector)
        detector._track_class_history = {}
        detector._track_last_seen = {}
        detector._tracking_frame_index = 0

        stable = detector._stabilize_track_classes([{
            "trackId": 31,
            "class": "personnel carrier",
            "label": "Xe cho nguoi",
            "confidence": 0.87,
        }])

        self.assertEqual(stable[0]["class"], "truck")
        self.assertEqual(stable[0]["label"], COCO_VIETNAMESE_MAPPING["truck"])
        self.assertEqual(stable[0]["rawClass"], "personnel carrier")

    def test_ambiguous_world_vehicle_is_canonicalized_before_tracking(self):
        class_name, raw_class = TrackedYoloDetector._canonicalize_detection_class("personnel carrier")

        self.assertEqual(class_name, "truck")
        self.assertEqual(raw_class, "personnel carrier")

    def test_retains_recent_tracked_detection_when_frame_misses(self):
        detector = self._retention_detector()
        detection = {
            "trackId": 42,
            "bbox": [80, 90, 260, 210],
            "normalized_bbox": [0.125, 0.188, 0.406, 0.438],
            "class": "truck",
            "label": COCO_VIETNAMESE_MAPPING["truck"],
            "confidence": 0.84,
            "source": "primary",
        }

        first = detector._retain_recent_detections([detection], 640, 480)
        second = detector._retain_recent_detections([], 640, 480)
        third = detector._retain_recent_detections([], 640, 480)
        fourth = detector._retain_recent_detections([], 640, 480)

        self.assertEqual(first[0]["trackId"], 42)
        self.assertTrue(second[0]["retained"])
        self.assertEqual(second[0]["trackId"], 42)
        self.assertTrue(third[0]["retained"])
        self.assertEqual(fourth, [])

    def test_custom_only_detection_gets_synthetic_track_and_retention(self):
        detector = self._retention_detector()
        custom = {
            "trackId": None,
            "bbox": [80, 90, 260, 210],
            "normalized_bbox": [0.125, 0.188, 0.406, 0.438],
            "class": "reach stacker",
            "label": "Xe cau",
            "confidence": 0.76,
            "source": "custom",
            "candidateVersion": "custom-test",
            "customConfirmed": True,
        }

        first = detector._retain_recent_detections([custom], 640, 480)
        second = detector._retain_recent_detections([], 640, 480)

        self.assertEqual(first[0]["trackId"], -1)
        self.assertTrue(second[0]["retained"])
        self.assertEqual(second[0]["trackId"], -1)
        self.assertEqual(second[0]["label"], "Xe cau")

    def test_retained_custom_label_sticks_when_base_detector_temporarily_wins(self):
        detector = self._retention_detector()
        custom = {
            "trackId": 7,
            "bbox": [80, 90, 260, 210],
            "normalized_bbox": [0.125, 0.188, 0.406, 0.438],
            "class": "reach stacker",
            "label": "Xe cau",
            "confidence": 0.76,
            "source": "custom",
            "candidateVersion": "custom-test",
            "customConfirmed": True,
        }
        truck = {
            "trackId": 7,
            "bbox": [84, 92, 262, 212],
            "normalized_bbox": [0.131, 0.192, 0.409, 0.442],
            "class": "truck",
            "label": COCO_VIETNAMESE_MAPPING["truck"],
            "confidence": 0.88,
            "source": "primary",
        }

        detector._retain_recent_detections([custom], 640, 480)
        retained_label = detector._retain_recent_detections([truck], 640, 480)

        self.assertEqual(retained_label[0]["trackId"], 7)
        self.assertEqual(retained_label[0]["class"], "reach stacker")
        self.assertEqual(retained_label[0]["label"], "Xe cau")
        self.assertEqual(retained_label[0]["candidateVersion"], "custom-test")

    def test_custom_candidate_requires_temporal_confirmation_before_relabel(self):
        detector = self._custom_gate_detector()
        custom = {
            "trackId": None,
            "bbox": [70, 90, 274, 210],
            "normalized_bbox": [0.109, 0.188, 0.428, 0.438],
            "class": "reach stacker",
            "label": "Xe cau",
            "confidence": 0.56,
            "source": "custom",
            "candidateVersion": "custom-test",
        }
        truck = {
            "trackId": 7,
            "bbox": [78, 88, 264, 214],
            "class": "truck",
            "label": COCO_VIETNAMESE_MAPPING["truck"],
            "confidence": 0.71,
            "source": "primary",
        }

        detector._custom_frame_index = 1
        self.assertFalse(detector._custom_candidate_confirmed(custom, truck))
        detector._custom_frame_index = 2
        self.assertTrue(detector._custom_candidate_confirmed(custom, truck))

    def test_narrow_reach_stacker_candidate_does_not_relabel_truck_front(self):
        detector = self._custom_gate_detector()
        detector._custom_instant_confidence = 0.50
        detector._custom_promote_confidence = 0.35
        custom = {
            "trackId": None,
            "bbox": [120, 100, 135, 210],
            "normalized_bbox": [0.188, 0.208, 0.210, 0.438],
            "class": "reach stacker",
            "label": "Xe cau",
            "confidence": 0.20,
            "source": "custom",
            "candidateVersion": "custom-test",
        }
        truck = {
            "trackId": 12,
            "bbox": [112, 94, 184, 220],
            "class": "truck",
            "label": COCO_VIETNAMESE_MAPPING["truck"],
            "confidence": 0.83,
            "source": "primary",
        }

        detector._custom_frame_index = 1
        self.assertFalse(detector._custom_candidate_confirmed(custom, truck))
        detector._custom_frame_index = 2
        self.assertFalse(detector._custom_candidate_confirmed(custom, truck))

    def test_compact_reach_stacker_candidate_confirms_valid_detection(self):
        detector = self._custom_gate_detector()
        detector._custom_instant_confidence = 0.40
        custom = {
            "trackId": None,
            "bbox": [100, 100, 240, 210],
            "normalized_bbox": [0.156, 0.208, 0.375, 0.438],
            "class": "reach stacker",
            "label": "Xe cau",
            "confidence": 0.74,
            "source": "custom",
            "candidateVersion": "custom-test",
        }
        truck = {
            "trackId": 12,
            "bbox": [96, 94, 246, 220],
            "class": "truck",
            "label": COCO_VIETNAMESE_MAPPING["truck"],
            "confidence": 0.61,
            "source": "primary",
        }

        detector._custom_frame_index = 1
        # High confidence custom reach stacker candidate promotes
        self.assertTrue(detector._custom_candidate_confirmed(custom, truck))

    def test_large_low_confidence_custom_candidate_is_rejected(self):
        detector = self._custom_gate_detector()
        detector._custom_instant_confidence = 0.48
        detector._custom_promote_confidence = 0.30
        custom = {
            "trackId": None,
            "bbox": [660, 187, 1278, 720],
            "normalized_bbox": [0.5156, 0.2597, 0.9984, 1.0],
            "class": "reach stacker",
            "label": "Xe cau",
            "confidence": 0.15,
            "source": "custom",
            "candidateVersion": "custom-test",
        }

        detector._custom_frame_index = 1
        self.assertFalse(detector._custom_candidate_confirmed(custom, None))

    def test_large_compact_custom_only_reach_stacker_candidate_is_rejected(self):
        detector = self._custom_gate_detector()
        custom = {
            "trackId": None,
            "bbox": [20, 20, 2500, 1400],
            "normalized_bbox": [0.01, 0.01, 0.98, 0.98],
            "class": "reach stacker",
            "label": "Xe cau",
            "confidence": 0.62,
            "source": "custom",
            "candidateVersion": "custom-test",
        }

        detector._custom_frame_index = 1
        self.assertFalse(detector._custom_candidate_confirmed(custom, None))

    def test_long_custom_only_reach_stacker_candidate_promotes_immediately(self):
        detector = self._custom_gate_detector()
        detector._custom_instant_confidence = 0.35
        custom = {
            "trackId": None,
            "bbox": [972, 521, 1352, 639],
            "normalized_bbox": [0.3616, 0.3428, 0.503, 0.4204],
            "class": "reach stacker",
            "label": "Xe cau",
            "confidence": 0.45,
            "source": "custom",
            "candidateVersion": "custom-test",
        }

        detector._custom_frame_index = 1
        self.assertTrue(detector._custom_candidate_confirmed(custom, None))

    def test_compact_custom_only_reach_stacker_candidate_confirms_over_frames(self):
        detector = self._custom_gate_detector()
        detector._custom_instant_confidence = 0.60
        detector._custom_promote_confidence = 0.30
        detector._custom_confirm_frames = 2
        custom = {
            "trackId": None,
            "bbox": [1180, 720, 1355, 855],
            "normalized_bbox": [0.439, 0.474, 0.504, 0.563],
            "class": "reach stacker",
            "label": "Xe cau",
            "confidence": 0.35,
            "source": "custom",
            "candidateVersion": "custom-test",
        }

        detector._custom_frame_index = 1
        self.assertFalse(detector._custom_candidate_confirmed(custom, None))
        detector._custom_frame_index = 2
        self.assertTrue(detector._custom_candidate_confirmed(custom, None))

    def test_tile_windows_cover_large_frames_evenly(self):
        detector = self._custom_gate_detector()
        detector._custom_tile_enabled = True
        detector._custom_tile_size = 640
        detector._custom_tile_overlap = 0.25
        detector._custom_tile_max_tiles = 16

        windows = detector._tile_windows(2560, 1440)

        self.assertLessEqual(len(windows), 16)
        self.assertIn((0, 0, 640, 640), windows)
        self.assertTrue(any(window[2] == 2560 for window in windows))
        self.assertTrue(any(window[3] == 1440 for window in windows))

    def test_tile_custom_augmentation_runs_when_full_frame_disabled(self):
        detector = self._custom_gate_detector()
        detector._custom_model = object()
        detector._custom_interval = 1
        detector._custom_full_frame = False
        detector._custom_match_overlap = 0.18
        detector._custom_version_key = "custom-test"
        detector._custom_label_map = {"Xe cau": "reach stacker"}
        detector._custom_track_overrides = {}
        detector._custom_confidence = 0.18
        detector._custom_full_frame_size = 1280
        detector.device = "cpu"
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        truck = {
            "trackId": 7,
            "bbox": [78, 88, 264, 214],
            "normalized_bbox": [0.122, 0.183, 0.412, 0.446],
            "class": "truck",
            "label": COCO_VIETNAMESE_MAPPING["truck"],
            "confidence": 0.71,
            "source": "primary",
        }
        custom = {
            "trackId": None,
            "bbox": [60, 90, 310, 210],
            "normalized_bbox": [0.094, 0.188, 0.484, 0.438],
            "class": "reach stacker",
            "label": "Xe cau",
            "confidence": 0.56,
            "source": "custom",
            "customInference": "tile",
            "candidateVersion": "custom-test",
        }
        detector._collect_custom_detections = MagicMock(return_value=[])
        detector._collect_custom_tiled_detections = MagicMock(return_value=[custom])
        detector._collect_custom_crop_detections = MagicMock(return_value=[])

        detector._apply_custom_augmentation(frame, [dict(truck)], 640, 480)
        refined = detector._apply_custom_augmentation(frame, [dict(truck)], 640, 480)

        detector._collect_custom_detections.assert_not_called()
        self.assertEqual(detector._collect_custom_tiled_detections.call_count, 2)
        self.assertEqual(refined[0]["class"], "reach stacker")
        self.assertEqual(refined[0]["customInference"], "tile")

    def test_retention_uses_seconds_for_high_fps_streams(self):
        detector = self._retention_detector()
        detector._retention_frames = 2
        detector._retention_seconds = 1.0
        now = [100.0]
        detector._clock = lambda: now[0]
        detection = {
            "trackId": 42,
            "bbox": [80, 90, 260, 210],
            "normalized_bbox": [0.125, 0.188, 0.406, 0.438],
            "class": "truck",
            "label": COCO_VIETNAMESE_MAPPING["truck"],
            "confidence": 0.84,
            "source": "primary",
        }

        detector._retain_recent_detections([detection], 640, 480)
        for _ in range(3):
            now[0] += 0.10
            retained = detector._retain_recent_detections([], 640, 480)

        self.assertTrue(retained)
        self.assertTrue(retained[0]["retained"])
        now[0] += 1.10
        self.assertEqual(detector._retain_recent_detections([], 640, 480), [])

    def test_untracked_custom_detection_reuses_recent_tracked_identity(self):
        detector = self._retention_detector()
        tracked = {
            "trackId": 9,
            "bbox": [80, 90, 260, 210],
            "normalized_bbox": [0.125, 0.188, 0.406, 0.438],
            "class": "reach stacker",
            "label": "Xe cau",
            "confidence": 0.76,
            "source": "custom",
            "candidateVersion": "custom-test",
        }
        custom = {
            "trackId": None,
            "bbox": [82, 91, 258, 209],
            "normalized_bbox": [0.128, 0.19, 0.403, 0.435],
            "class": "reach stacker",
            "label": "Xe cau",
            "confidence": 0.74,
            "source": "custom",
            "candidateVersion": "custom-test",
        }

        detector._retain_recent_detections([tracked], 640, 480)
        reused = detector._retain_recent_detections([custom], 640, 480)

        self.assertEqual(reused[0]["trackId"], 9)
        self.assertEqual(reused[0]["label"], "Xe cau")


class TestViolationStateMachine(unittest.TestCase):
    def setUp(self):
        self.checker = ZoneChecker(
            camera_id="BAI-KIEM",
            grace_frames=3,
            minimum_violation_seconds=0.0,
        )
        self.test_zones = [
            {
                "id": "zone-1",
                "name": "Khu vực cấm xe máy",
                "polygon_points": [
                    {"x": 0.0, "y": 0.0},
                    {"x": 0.5, "y": 0.0},
                    {"x": 0.5, "y": 0.5},
                    {"x": 0.0, "y": 0.5},
                ],
                "rule_type": "PROHIBIT_SPECIFIED",
                "target_labels": ["Xe máy"],
            }
        ]
        self.class_map = {"motorcycle": ["Xe máy"]}

    def test_open_sustain_close_lifecycle(self):
        t0 = datetime(2026, 8, 18, 10, 0, 0, tzinfo=timezone.utc)

        # Frame 1: Track 1 enters zone-1 with motorcycle (inside [0.25, 0.4]) -> STARTED
        det_frame1 = [{
            "trackId": 1,
            "bbox": [100, 100, 200, 200],
            "normalized_bbox": [0.2, 0.2, 0.3, 0.4],
            "class": "motorcycle",
            "label": "Xe máy",
            "confidence": 0.9,
        }]

        annotated, transitions = self.checker.check_detections(
            det_frame1, self.test_zones, self.class_map, timestamp=t0
        )
        self.assertEqual(len(annotated), 1)
        self.assertEqual(annotated[0]["status"], "VIOLATION")
        self.assertEqual(annotated[0]["zoneMatches"][0]["status"], "VIOLATION")
        self.assertEqual(len(transitions), 1)
        self.assertEqual(transitions[0].action, "STARTED")
        self.assertEqual(transitions[0].status, "OPEN")
        self.assertEqual(transitions[0].track_id, 1)
        self.assertEqual(transitions[0].zone_id, "zone-1")

        # Frame 2: Track 1 remains inside -> Sustained (anti-spam: 0 new transitions)
        t1 = t0 + timedelta(seconds=1)
        annotated2, transitions2 = self.checker.check_detections(
            det_frame1, self.test_zones, self.class_map, timestamp=t1
        )
        self.assertEqual(len(annotated2), 1)
        self.assertEqual(annotated2[0]["status"], "VIOLATION")
        self.assertEqual(len(transitions2), 0, "Anti-spam: should not produce new transitions while inside")

        # Frame 3: Track 1 leaves zone (outside) -> Grace frame 1
        t2 = t0 + timedelta(seconds=2)
        det_outside = [{
            "trackId": 1,
            "bbox": [500, 400, 600, 450],
            "normalized_bbox": [0.7, 0.7, 0.9, 0.9],
            "class": "motorcycle",
            "label": "Xe máy",
            "confidence": 0.9,
        }]
        annotated3, transitions3 = self.checker.check_detections(
            det_outside, self.test_zones, self.class_map, timestamp=t2
        )
        self.assertEqual(annotated3[0]["status"], "OUTSIDE")
        self.assertEqual(annotated3[0]["zoneMatches"], [])
        self.assertEqual(len(transitions3), 0, "Grace frame 1: should not close yet")

        # Frame 4: Grace frame 2
        t3 = t0 + timedelta(seconds=3)
        annotated4, transitions4 = self.checker.check_detections(
            det_outside, self.test_zones, self.class_map, timestamp=t3
        )
        self.assertEqual(len(transitions4), 0, "Grace frame 2: should not close yet")

        # Frame 5: Grace frame 3 -> ENDED transition triggered
        t4 = t0 + timedelta(seconds=4)
        annotated5, transitions5 = self.checker.check_detections(
            det_outside, self.test_zones, self.class_map, timestamp=t4
        )
        self.assertEqual(len(transitions5), 1, "Grace frame 3: should close violation")
        end_t = transitions5[0]
        self.assertEqual(end_t.action, "ENDED")
        self.assertEqual(end_t.status, "CLOSED")
        self.assertEqual(end_t.track_id, 1)
        # Exited at should be t1 (last seen inside)
        self.assertEqual(end_t.exited_at, t1)
        self.assertEqual(end_t.duration_seconds, 1)
        self.assertEqual(len(self.checker.active_violations), 0)

    def test_untracked_detection_no_db_violation(self):
        # trackId is None (not yet confirmed by ByteTrack)
        t0 = datetime(2026, 8, 18, 10, 0, 0, tzinfo=timezone.utc)
        det_untracked = [{
            "trackId": None,
            "bbox": [100, 100, 200, 200],
            "normalized_bbox": [0.2, 0.2, 0.3, 0.4],
            "class": "motorcycle",
            "label": "Xe máy",
            "confidence": 0.9,
        }]
        annotated, transitions = self.checker.check_detections(
            det_untracked, self.test_zones, self.class_map, timestamp=t0
        )
        self.assertEqual(annotated[0]["status"], "VIOLATION")
        self.assertEqual(len(transitions), 0, "Untracked detections cannot emit persisted transitions")


    def test_missing_detection_and_track_renumber_do_not_reopen_event(self):
        t0 = datetime(2026, 8, 18, 10, 0, 0, tzinfo=timezone.utc)
        first_track = [{
            "trackId": 1,
            "bbox": [100, 100, 200, 200],
            "normalized_bbox": [0.2, 0.2, 0.3, 0.4],
            "class": "motorcycle",
            "label": "Xe mĂ¡y",
            "confidence": 0.9,
        }]

        _, started = self.checker.check_detections(
            first_track, self.test_zones, self.class_map, timestamp=t0
        )
        self.assertEqual(len(started), 1)
        violation_id = started[0].violation_id

        for seconds in (1, 3):
            _, transitions = self.checker.check_detections(
                [], self.test_zones, self.class_map, timestamp=t0 + timedelta(seconds=seconds)
            )
            self.assertEqual(transitions, [], "Temporary detector loss must keep the violation open")

        renumbered_track = [{**first_track[0], "trackId": 99}]
        _, transitions = self.checker.check_detections(
            renumbered_track, self.test_zones, self.class_map, timestamp=t0 + timedelta(seconds=4)
        )
        self.assertEqual(transitions, [], "A reidentified object must not create another STARTED event")
        self.assertEqual(len(self.checker.active_violations), 1)
        active = next(iter(self.checker.active_violations.values()))
        self.assertEqual(active.violation_id, violation_id)
        self.assertEqual(active.track_id, 99)

    def test_missing_detection_closes_after_time_grace(self):
        t0 = datetime(2026, 8, 18, 10, 0, 0, tzinfo=timezone.utc)
        inside = [{
            "trackId": 1,
            "bbox": [100, 100, 200, 200],
            "normalized_bbox": [0.2, 0.2, 0.3, 0.4],
            "class": "motorcycle",
            "label": "Xe mĂ¡y",
            "confidence": 0.9,
        }]
        self.checker.check_detections(inside, self.test_zones, self.class_map, timestamp=t0)

        _, before_timeout = self.checker.check_detections(
            [], self.test_zones, self.class_map, timestamp=t0 + timedelta(seconds=11.9)
        )
        self.assertEqual(before_timeout, [])

        _, after_timeout = self.checker.check_detections(
            [], self.test_zones, self.class_map, timestamp=t0 + timedelta(seconds=12.0)
        )
        self.assertEqual(len(after_timeout), 1)
        self.assertEqual(after_timeout[0].action, "ENDED")

    def test_outside_detection_is_not_classified_as_allowed(self):
        t0 = datetime(2026, 8, 18, 10, 0, 0, tzinfo=timezone.utc)
        outside = [{
            "trackId": 1,
            "bbox": [500, 300, 600, 450],
            "normalized_bbox": [0.75, 0.5, 0.9, 0.9],
            "class": "motorcycle",
            "label": "Xe mĂ¡y",
            "confidence": 0.9,
        }]

        annotated, transitions = self.checker.check_detections(
            outside, self.test_zones, self.class_map, timestamp=t0
        )
        self.assertEqual(annotated[0]["status"], "OUTSIDE")
        self.assertEqual(annotated[0]["zoneMatches"], [])
        self.assertEqual(transitions, [])

    def test_violation_under_one_second_never_starts_event(self):
        checker = ZoneChecker(
            camera_id="BAI-KIEM",
            grace_frames=3,
            minimum_violation_seconds=1.0,
        )
        t0 = datetime(2026, 8, 18, 10, 0, 0, tzinfo=timezone.utc)
        inside = [{
            "trackId": 1,
            "bbox": [100, 100, 200, 200],
            "normalized_bbox": [0.2, 0.2, 0.3, 0.4],
            "class": "motorcycle",
            "label": "Xe mĂ¡y",
            "confidence": 0.9,
        }]

        _, first_frame = checker.check_detections(
            inside, self.test_zones, self.class_map, timestamp=t0
        )
        self.assertEqual(first_frame, [])
        self.assertEqual(len(checker.pending_violations), 1)

        _, short_exit = checker.check_detections(
            [], self.test_zones, self.class_map, timestamp=t0 + timedelta(seconds=0.9)
        )
        self.assertEqual(short_exit, [])
        self.assertEqual(checker.active_violations, {})
        self.assertEqual(checker.pending_violations, {})

    def test_violation_starts_after_one_second_confirmation(self):
        checker = ZoneChecker(
            camera_id="BAI-KIEM",
            grace_frames=3,
            minimum_violation_seconds=1.0,
        )
        t0 = datetime(2026, 8, 18, 10, 0, 0, tzinfo=timezone.utc)
        inside = [{
            "trackId": 1,
            "bbox": [100, 100, 200, 200],
            "normalized_bbox": [0.2, 0.2, 0.3, 0.4],
            "class": "motorcycle",
            "label": "Xe mĂ¡y",
            "confidence": 0.9,
        }]

        checker.check_detections(inside, self.test_zones, self.class_map, timestamp=t0)
        _, transitions = checker.check_detections(
            inside, self.test_zones, self.class_map, timestamp=t0 + timedelta(seconds=1)
        )

        self.assertEqual([transition.action for transition in transitions], ["STARTED"])
        self.assertEqual(transitions[0].entered_at, t0)

    def test_boundary_jitter_does_not_close_or_reopen_violation(self):
        t0 = datetime(2026, 8, 18, 10, 0, 0, tzinfo=timezone.utc)
        inside = [{
            "trackId": 1,
            "bbox": [100, 100, 200, 200],
            "normalized_bbox": [0.2, 0.2, 0.3, 0.4],
            "class": "motorcycle",
            "label": "Xe mĂ¡y",
            "confidence": 0.9,
        }]
        _, started = self.checker.check_detections(
            inside, self.test_zones, self.class_map, timestamp=t0
        )
        self.assertEqual([transition.action for transition in started], ["STARTED"])
        violation_id = started[0].violation_id

        # The zone edge is x=0.50. A bottom-center x=0.51 is just outside
        # the exact polygon but inside the 0.02 hysteresis buffer.
        edge_jitter = [{
            "trackId": 1,
            "bbox": [300, 100, 360, 200],
            "normalized_bbox": [0.49, 0.2, 0.53, 0.4],
            "class": "motorcycle",
            "label": "Xe mĂ¡y",
            "confidence": 0.9,
        }]
        for seconds in range(1, 6):
            annotated, transitions = self.checker.check_detections(
                edge_jitter,
                self.test_zones,
                self.class_map,
                timestamp=t0 + timedelta(seconds=seconds),
            )
            self.assertEqual(annotated[0]["status"], "VIOLATION")
            self.assertEqual(
                transitions,
                [],
                "Jitter within the boundary buffer must not close or reopen the event",
            )

        active = next(iter(self.checker.active_violations.values()))
        self.assertEqual(active.violation_id, violation_id)
        self.assertEqual(active.consecutive_outside, 0)

        # A point clearly beyond the buffer is a genuine exit and must still
        # close after the existing three observed-frame grace period.
        clearly_outside = [{
            **edge_jitter[0],
            "bbox": [330, 100, 390, 200],
            "normalized_bbox": [0.53, 0.2, 0.57, 0.4],
        }]
        for seconds in (6, 7):
            _, transitions = self.checker.check_detections(
                clearly_outside,
                self.test_zones,
                self.class_map,
                timestamp=t0 + timedelta(seconds=seconds),
            )
            self.assertEqual(transitions, [])

        _, transitions = self.checker.check_detections(
            clearly_outside,
            self.test_zones,
            self.class_map,
            timestamp=t0 + timedelta(seconds=8),
        )
        self.assertEqual(len(transitions), 1)
        self.assertEqual(transitions[0].action, "ENDED")
        self.assertEqual(transitions[0].violation_id, violation_id)
        self.assertEqual(len(self.checker.active_violations), 0)


class TestBrowserCompatibleClipEncoding(unittest.TestCase):
    def test_circular_buffer_writes_h264_mp4(self):
        buffer = CircularBuffer(max_seconds=3.0, target_fps=5.0)
        started_at = 1_000.0
        for index in range(10):
            frame = np.full((48, 64, 3), index * 20, dtype=np.uint8)
            buffer.append(frame, started_at + index * 0.2)

        output_path = (
            Path(parent_dir).parent
            / "data"
            / "clips"
            / f"area_h264_test_{uuid4().hex}.mp4"
        )
        try:
            saved_path = buffer.save_clip(
                str(output_path),
                duration_seconds=2.0,
                end_time=started_at + 1.8,
            )
            self.assertEqual(saved_path, str(output_path))
            self.assertTrue(output_path.exists())

            capture = cv2.VideoCapture(str(output_path))
            self.assertTrue(capture.isOpened())
            fourcc_value = int(capture.get(cv2.CAP_PROP_FOURCC))
            fourcc = "".join(chr((fourcc_value >> (8 * index)) & 0xFF) for index in range(4))
            self.assertEqual(fourcc.lower(), "h264")
            self.assertGreater(capture.get(cv2.CAP_PROP_FRAME_COUNT), 0)
            capture.release()
        finally:
            output_path.unlink(missing_ok=True)


class TestStreamReaderLoopSignal(unittest.TestCase):
    def test_preview_frame_does_not_move_monitored_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            video_path = Path(directory) / "preview.mp4"
            writer = cv2.VideoWriter(str(video_path), cv2.VideoWriter_fourcc(*"mp4v"), 5, (64, 48))
            self.assertTrue(writer.isOpened())
            writer.write(np.zeros((48, 64, 3), dtype=np.uint8))
            writer.write(np.full((48, 64, 3), 255, dtype=np.uint8))
            writer.release()
            reader = StreamReader(source=str(video_path), camera_id="BAI-KIEM", resolution=(32, 24))
            self.assertIsNotNone(reader.cap)
            reader.cap.set(cv2.CAP_PROP_POS_FRAMES, 1)
            before = reader.cap.get(cv2.CAP_PROP_POS_FRAMES)
            preview = reader.preview_frame(0.2)
            self.assertIsNotNone(preview)
            self.assertEqual(preview.shape, (24, 32, 3))
            self.assertEqual(reader.cap.get(cv2.CAP_PROP_POS_FRAMES), before)
            reader.release()

    def test_local_video_rewind_sets_source_reset_signal(self):
        reader = StreamReader(source=None, camera_id="BAI-KIEM", resolution=(64, 48))
        capture = MagicMock()
        capture.isOpened.return_value = True
        frame = np.zeros((48, 64, 3), dtype=np.uint8)
        capture.read.side_effect = [(False, None), (True, frame)]
        reader.cap = capture
        reader.is_image_fallback = False
        reader.is_synthetic = False

        success, output = reader.read_frame()

        self.assertTrue(success)
        self.assertIsNotNone(output)
        self.assertTrue(reader.did_loop)
        capture.set.assert_called_once_with(cv2.CAP_PROP_POS_FRAMES, 0)

    def test_local_video_skips_frames_to_keep_source_speed(self):
        reader = StreamReader(source=None, camera_id="BAI-KIEM", resolution=(64, 48))
        capture = MagicMock()
        capture.isOpened.return_value = True
        capture.read.return_value = (True, np.zeros((48, 64, 3), dtype=np.uint8))
        capture.grab.return_value = True
        reader.cap = capture
        reader.is_image_fallback = False
        reader.is_synthetic = False
        reader.is_local_file = True
        reader.source_fps = 50.0
        reader._last_local_frame_at = 10.0

        with patch("stream.reader.time.monotonic", return_value=10.1):
            success, _ = reader.read_frame()

        self.assertTrue(success)
        self.assertEqual(capture.grab.call_count, 4)


class TestAreaPipelineExecution(unittest.TestCase):
    def test_unreviewed_one_class_model_is_disabled_instead_of_relabeling_vehicles(self):
        detector = MagicMock()
        active = {
            "version_key": "legacy-one-class",
            "artifact_path": "training/models/legacy/best.pt",
            "evaluation_metrics": {"labelMap": {"Xe nâng": "forklift"}},
        }
        with patch.dict(os.environ, {"CUSTOM_AUGMENT_FORCE_DEFAULT": "false"}):
            with patch("detection.area_pipeline.get_active_custom_model", new_callable=AsyncMock, return_value=active):
                pipeline = AreaPipeline(camera_id="BAI-KIEM", source=None, target_fps=1, resolution=(64, 48), detector=detector)
                asyncio.run(pipeline._refresh_custom_model())

        detector.configure_custom_model.assert_called_once_with(None, None, None)

    def test_force_default_custom_model_skips_db_active_override(self):
        detector = MagicMock()
        default_config = {
            "version_key": "custom-default",
            "artifact_path": "D:/tmp/best.pt",
            "label_map": {"Xe cau": "reach stacker"},
        }

        with patch.dict(os.environ, {"CUSTOM_AUGMENT_FORCE_DEFAULT": "true"}):
            with patch.object(TrackedYoloDetector, "default_custom_model_config", return_value=default_config):
                with patch("detection.area_pipeline.get_active_custom_model", new_callable=AsyncMock) as get_active:
                    pipeline = AreaPipeline(
                        camera_id="BAI-KIEM",
                        source=None,
                        target_fps=10.0,
                        resolution=(64, 48),
                        detector=detector,
                    )
                    asyncio.run(pipeline._refresh_custom_model())

        get_active.assert_not_awaited()
        detector.configure_custom_model.assert_called_once_with(
            "custom-default",
            "D:/tmp/best.pt",
            {"Xe cau": "reach stacker"},
        )

    def test_area_pipeline_single_frame(self):
        pipeline = AreaPipeline(
            camera_id="BAI-KIEM",
            source=None,  # triggers synthetic test frame
            target_fps=10.0,
            resolution=(640, 480),
        )
        res = pipeline.process_single_frame()
        self.assertTrue(res["success"])
        self.assertEqual(res["camera_id"], "BAI-KIEM")
        self.assertTrue(res["image_base64"].startswith("data:image/jpeg;base64,"))
        self.assertIn("detections", res)
        self.assertIn("zones", res)
        self.assertIn("transitions", res)
        self.assertGreaterEqual(res["fps"], 0.0)

    def test_strict_whitelist_drops_unconfigured_classes(self):
        checker = ZoneChecker(camera_id="BAI-KIEM")
        zones = [{
            "id": "zone-1",
            "name": "Khu vực bãi",
            "polygon_points": [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 0.0}, {"x": 1.0, "y": 1.0}, {"x": 0.0, "y": 1.0}],
            "rule_type": "PROHIBIT_SPECIFIED",
            "target_labels": ["Xe tải"],
        }]
        class_to_labels = {
            "forklift": ["Xe nâng"],
            "truck": ["Xe tải"],
        }
        detections = [
            {"trackId": 1, "bbox": [10, 10, 100, 100], "normalized_bbox": [0.01, 0.01, 0.1, 0.1], "class": "bus", "label": "Xe buýt", "confidence": 0.85},
            {"trackId": 2, "bbox": [150, 150, 300, 300], "normalized_bbox": [0.15, 0.15, 0.3, 0.3], "class": "truck", "label": "Xe tải", "confidence": 0.88},
            {"trackId": 3, "bbox": [350, 350, 500, 500], "normalized_bbox": [0.35, 0.35, 0.5, 0.5], "class": "reach stacker", "label": "Xe nâng", "confidence": 0.75},
        ]
        annotated, _ = checker.check_detections(detections, zones, class_to_labels)
        # 'bus' must be dropped because it is not in class_to_labels whitelist
        labels = [d["label"] for d in annotated]
        self.assertNotIn("Xe buýt", labels)
        self.assertIn("Xe tải", labels)
        self.assertIn("Xe nâng", labels)
        self.assertEqual(len(annotated), 2)

    def test_assemble_container_trucks_merges_cabin_and_trailer(self):
        detector = TrackedYoloDetector(model_path="yolo11n.pt")
        # Cabin + Trailer touching adjacent boxes
        cabin = {"trackId": 10, "bbox": [200, 100, 260, 180], "class": "car", "confidence": 0.70}
        trailer = {"trackId": 11, "bbox": [255, 95, 450, 185], "class": "truck", "confidence": 0.85}
        assembled = detector._assemble_container_trucks([cabin, trailer], 640, 480)
        self.assertEqual(len(assembled), 1)
        self.assertEqual(assembled[0]["class"], "truck")
        self.assertEqual(assembled[0]["bbox"], [200, 95, 450, 185])
        self.assertEqual(assembled[0]["source"], "assembled")


class TestRainAndStaticContainerStabilization(unittest.TestCase):
    @staticmethod
    def _detection(track_id, confidence, bbox=(100, 100, 200, 220)):
        return {
            "trackId": track_id,
            "bbox": list(bbox),
            "normalized_bbox": [bbox[0] / 640, bbox[1] / 480, bbox[2] / 640, bbox[3] / 480],
            "class": "truck",
            "label": COCO_VIETNAMESE_MAPPING["truck"],
            "confidence": confidence,
            "source": "primary",
        }

    def test_low_confidence_continues_confirmed_track_but_cannot_start_new_one(self):
        detector = TrackedYoloDetector.__new__(TrackedYoloDetector)
        detector._track_initiation_confidence = 0.30
        detector._track_continuation_confidence = 0.14
        detector._confidence_smoothing_alpha = 0.40
        detector._motion_window_frames = 40

        self.assertEqual(detector._apply_track_hysteresis([self._detection(8, 0.20)]), [])

        opened = detector._apply_track_hysteresis([self._detection(8, 0.45)])
        self.assertEqual(len(opened), 1)
        self.assertEqual(opened[0]["confidence"], 0.45)

        continued = detector._apply_track_hysteresis([self._detection(8, 0.16)])
        self.assertEqual(len(continued), 1)
        self.assertEqual(continued[0]["trackId"], 8)
        self.assertAlmostEqual(continued[0]["confidence"], 0.334, places=3)
        self.assertEqual(detector._apply_track_hysteresis([self._detection(9, 0.16)]), [])

    def test_static_container_is_removed_after_motion_window_and_moving_vehicle_returns(self):
        detector = TrackedYoloDetector.__new__(TrackedYoloDetector)
        detector._motion_window_frames = 4
        detector._static_max_speed_px_per_frame = 0.30
        detector._retained_detections = {"track:42": {"detection": self._detection(42, 0.8)}}

        for _ in range(3):
            self.assertEqual(len(detector._suppress_static_detections([self._detection(42, 0.8)])), 1)
        self.assertEqual(detector._suppress_static_detections([self._detection(42, 0.8)]), [])
        self.assertNotIn("track:42", detector._retained_detections)

        moving = self._detection(42, 0.8, bbox=(220, 100, 320, 220))
        self.assertEqual(len(detector._suppress_static_detections([moving])), 1)
        self.assertNotIn(42, detector._static_track_ids)

    def test_reach_stacker_shape_filter_rejects_flat_container_silhouette(self):
        detector = TrackedYoloDetector.__new__(TrackedYoloDetector)
        detector._reach_stacker_min_aspect = 0.65
        detector._reach_stacker_max_aspect = 3.50
        detector._reach_stacker_min_height_ratio = 0.06
        flat_container = {
            "bbox": [10, 100, 510, 130],
            "normalized_bbox": [0.01, 0.20, 0.80, 0.25],
            "class": "reach stacker",
            "confidence": 0.92,
        }
        self.assertFalse(detector._custom_candidate_shape_ok(flat_container, None))

    def test_zone_checker_never_emits_static_suppressed_detection(self):
        checker = ZoneChecker(camera_id="BAI-KIEM")
        zones = [{
            "id": "yard",
            "name": "Yard",
            "polygon_points": [{"x": 0, "y": 0}, {"x": 1, "y": 0}, {"x": 1, "y": 1}],
            "rule_type": "PROHIBIT_SPECIFIED",
            "target_labels": ["Xe táº£i"],
        }]
        detection = self._detection(42, 0.9)
        detection["suppressedStatic"] = True
        annotated, transitions = checker.check_detections(detection and [detection], zones, {"truck": ["Xe táº£i"]})
        self.assertEqual(annotated, [])
        self.assertEqual(transitions, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
