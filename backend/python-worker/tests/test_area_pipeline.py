"""Regression tests for Area tracking, lifecycle, clips, and stream behaviour."""
from __future__ import annotations

import hashlib
import asyncio
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType
from unittest.mock import AsyncMock, MagicMock, patch

import cv2
import numpy as np
from shapely.geometry import Point

CURRENT_DIR = Path(__file__).resolve().parent
WORKER_DIR = CURRENT_DIR.parent
if str(WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(WORKER_DIR))

from buffer.circular_buffer import CircularBuffer
from db.repositories import delete_zone_violations
from detection.area_pipeline import AreaPipeline
from detection.policy import DetectionPolicy
from detection.tracked_detector import TrackedYoloDetector
from stream.reader import StreamReader
from zone.activity_tracker import ActivityTransition
from zone.zone_checker import ActiveViolation, PendingViolation, ViolationTransition, ZoneChecker, evaluate_zone_rule, get_detection_bottom_center, parse_polygon, resolve_candidate_labels
from zone.zone_sync import ZoneSnapshot


def detection(
    track_id: int | None,
    canonical_class: str,
    confidence: float = 0.90,
    *,
    bbox: list[int] | None = None,
    can_initiate: bool = True,
) -> dict[str, object]:
    box = bbox or [100, 100, 200, 200]
    return {
        "trackId": track_id,
        "bbox": box,
        "normalized_bbox": [box[0] / 640, box[1] / 480, box[2] / 640, box[3] / 480],
        "class": canonical_class,
        "canonicalClass": canonical_class,
        "label": canonical_class,
        "confidence": confidence,
        "source": "COCO",
        "customConfirmed": False,
        "canInitiate": can_initiate,
        "canContinue": can_initiate,
    }


def detection_at_bottom_center(
    track_id: int,
    canonical_class: str,
    center_x: float,
    bottom_y: float,
) -> dict[str, object]:
    item = detection(track_id, canonical_class)
    item["normalized_bbox"] = [
        center_x - 0.01,
        bottom_y - 0.1,
        center_x + 0.01,
        bottom_y,
    ]
    return item


class TestZoneGeometryAndRules(unittest.TestCase):
    def test_polygon_parsing_and_boundary(self):
        polygon = parse_polygon([
            {"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 0.0},
            {"x": 1.0, "y": 1.0}, {"x": 0.0, "y": 1.0},
        ])
        self.assertIsNotNone(polygon)
        self.assertTrue(polygon.covers(Point(1.0, 0.5)))
        self.assertFalse(polygon.covers(Point(1.1, 0.5)))
        self.assertIsNone(parse_polygon([{"x": 0.0, "y": 0.0}]))

    def test_immutable_snapshot_polygon_produces_live_zone_match(self):
        frozen_points = (
            MappingProxyType({"x": 0.0, "y": 0.0}),
            MappingProxyType({"x": 1.0, "y": 0.0}),
            MappingProxyType({"x": 1.0, "y": 1.0}),
            MappingProxyType({"x": 0.0, "y": 1.0}),
        )
        polygon = parse_polygon(frozen_points)
        self.assertIsNotNone(polygon)

        checker = ZoneChecker(camera_id="BAI-KIEM", minimum_violation_seconds=0)
        annotated, _ = checker.check_detections(
            [detection(7, "truck", bbox=[200, 100, 300, 300])],
            [MappingProxyType({
                "id": "zone-frozen",
                "name": "Frozen zone",
                "polygon_points": frozen_points,
                "rule_type": "ALLOW_SPECIFIED",
                "target_labels": ("Xe tải",),
            })],
            {"truck": ("Xe tải",)},
        )

        self.assertEqual(annotated[0]["status"], "ALLOWED")
        self.assertEqual(annotated[0]["zoneMatches"], [{
            "zoneId": "zone-frozen",
            "zoneName": "Frozen zone",
            "status": "ALLOWED",
        }])

    def test_bottom_center_and_rule_matrix(self):
        bottom_x, bottom_y = get_detection_bottom_center([0.2, 0.1, 0.4, 0.7])
        self.assertAlmostEqual(bottom_x, 0.3)
        self.assertAlmostEqual(bottom_y, 0.7)
        self.assertEqual(evaluate_zone_rule("PROHIBIT_SPECIFIED", ["Xe máy"], ["Xe máy"]), "VIOLATION")
        self.assertEqual(evaluate_zone_rule("ALLOW_SPECIFIED", ["Xe máy"], ["Xe tải"]), "VIOLATION")

    def test_pixel_tolerance_includes_eleven_pixels_but_excludes_thirteen(self):
        checker = ZoneChecker(boundary_tolerance_pixels=12.0)
        zones = [{
            "id": "zone-edge",
            "name": "Edge",
            "polygon_points": [
                {"x": 0.0, "y": 0.0}, {"x": 0.5, "y": 0.0},
                {"x": 0.5, "y": 1.0}, {"x": 0.0, "y": 1.0},
            ],
            "rule_type": "ALLOW_SPECIFIED",
            "target_labels": ["Xe nâng container"],
        }]
        class_map = {"reach_stacker": ["Xe nâng container"]}
        near = detection_at_bottom_center(
            1, "reach_stacker", (320 + 11) / 640, 0.8,
        )
        far = detection_at_bottom_center(
            2, "reach_stacker", (320 + 13) / 640, 0.8,
        )

        annotated, _ = checker.check_detections(
            [near, far], zones, class_map, frame_size=(640, 480),
        )

        self.assertEqual(annotated[0]["status"], "ALLOWED")
        self.assertEqual(len(annotated[0]["zoneMatches"]), 1)
        self.assertEqual(annotated[1]["status"], "OUTSIDE")
        self.assertEqual(annotated[1]["zoneMatches"], [])

    def test_pixel_tolerance_applies_to_new_violation(self):
        checker = ZoneChecker(
            boundary_tolerance_pixels=12.0,
            minimum_violation_seconds=0.0,
        )
        zones = [{
            "id": "zone-edge",
            "name": "Edge",
            "polygon_points": [
                {"x": 0.0, "y": 0.0}, {"x": 0.5, "y": 0.0},
                {"x": 0.5, "y": 1.0}, {"x": 0.0, "y": 1.0},
            ],
            "rule_type": "PROHIBIT_SPECIFIED",
            "target_labels": ["Xe nâng container"],
        }]
        near = detection_at_bottom_center(
            1, "reach_stacker", (320 + 11) / 640, 0.8,
        )

        annotated, transitions = checker.check_detections(
            [near],
            zones,
            {"reach_stacker": ["Xe nâng container"]},
            frame_size=(640, 480),
        )

        self.assertEqual(annotated[0]["status"], "VIOLATION")
        self.assertEqual(len(annotated[0]["zoneMatches"]), 1)
        self.assertEqual([item.action for item in transitions], ["STARTED"])

    def test_pixel_tolerance_is_resolution_independent(self):
        zones = [{
            "id": "zone-edge",
            "name": "Edge",
            "polygon_points": [
                {"x": 0.0, "y": 0.0}, {"x": 0.5, "y": 0.0},
                {"x": 0.5, "y": 1.0}, {"x": 0.0, "y": 1.0},
            ],
            "rule_type": "ALLOW_SPECIFIED",
            "target_labels": ["Xe nâng container"],
        }]
        class_map = {"reach_stacker": ["Xe nâng container"]}

        statuses = []
        for width, height in ((640, 480), (1280, 720)):
            checker = ZoneChecker(boundary_tolerance_pixels=12.0)
            near = detection_at_bottom_center(
                1, "reach_stacker", ((width * 0.5) + 11) / width, 0.8,
            )
            annotated, _ = checker.check_detections(
                [near], zones, class_map, frame_size=(width, height),
            )
            statuses.append(annotated[0]["status"])

        self.assertEqual(statuses, ["ALLOWED", "ALLOWED"])

    def test_registry_resolution_keeps_unknowns_out(self):
        class_map = {"motorcycle": ["Xe máy"], "truck": ["Xe tải"]}
        self.assertEqual(resolve_candidate_labels("motorcycle", "Xe máy", class_map), ["Xe máy"])
        self.assertEqual(resolve_candidate_labels("alien", "", class_map), [])
        self.assertEqual(resolve_candidate_labels("truck", "untrusted display text", class_map), ["Xe tải"])

    def test_registry_resolution_never_crosses_canonical_classes(self):
        class_map = {
            "truck": ["Xe tải"],
            "container_truck": ["Xe đầu kéo container"],
            "shipping_container": ["Container tĩnh"],
            "reach_stacker": ["Xe nâng container"],
            "forklift": ["Xe nâng hàng"],
            "mobile_crane": ["Xe cẩu tự hành"],
        }
        self.assertEqual(resolve_candidate_labels("truck", "Xe tải", class_map), ["Xe tải"])
        for canonical_class in (
            "container_truck",
            "shipping_container",
            "reach_stacker",
            "forklift",
            "mobile_crane",
        ):
            self.assertNotIn("Xe tải", resolve_candidate_labels(canonical_class, "Xe tải", class_map))
        self.assertEqual(resolve_candidate_labels("container handler", "Xe nâng", class_map), [])


class TestDetectorControl(unittest.TestCase):
    class _Scalar:
        def __init__(self, value: float | int):
            self.value = value

        def item(self):
            return self.value

    class _Tensor:
        def __init__(self, value: list[float]):
            self.value = value

        def cpu(self):
            return self

        def numpy(self):
            return np.array(self.value)

    class _Boxes:
        def __init__(self, confidence: float):
            self.xyxy = [TestDetectorControl._Tensor([100, 100, 240, 230])]
            self.cls = [TestDetectorControl._Scalar(0)]
            self.conf = [TestDetectorControl._Scalar(confidence)]

        def __len__(self):
            return 1

    class _Result:
        def __init__(self, confidence: float):
            self.boxes = TestDetectorControl._Boxes(confidence)

    class _CustomModel:
        names = {0: "Reach stacker"}

        def __init__(self, confidence: float = 0.70):
            self.confidence = confidence

        def __call__(self, *_args, **_kwargs):
            return [TestDetectorControl._Result(self.confidence)]

    @staticmethod
    def _detector() -> TrackedYoloDetector:
        detector = TrackedYoloDetector.__new__(TrackedYoloDetector)
        detector._policy = DetectionPolicy()
        detector._enabled_coco_classes = frozenset({"truck", "bus"})
        detector._enabled_custom_classes = frozenset({"reach_stacker"})
        detector._base_track_state = {}
        detector._base_frame_index = 0
        detector._custom_model = TestDetectorControl._CustomModel()
        detector._custom_version_key = "custom-v1"
        detector._custom_artifact_path = None
        detector._custom_artifact_sha256 = None
        detector._custom_label_map = {"Reach stacker": "reach_stacker"}
        detector._custom_frame_index = 0
        detector._custom_windows = {}
        detector._custom_candidates = {}
        detector._next_synthetic_track_id = -1
        detector._custom_interval = 1
        detector._custom_match_overlap = 0.20
        detector._custom_hold_opportunities = 5
        detector._custom_box_ema_alpha = 0.65
        detector._custom_max_edge_step_ratio = 0.015
        detector.inference_size = 640
        detector.custom_inference_size = 768
        detector.device = "cpu"
        detector._reset_tracker_on_next_frame = False
        detector._detection_control_fingerprint = None
        return detector

    def test_identical_detection_control_preserves_tracking_and_temporal_state(self):
        detector = self._detector()
        detector._custom_model = None
        detector._custom_version_key = None
        detector._custom_label_map = {}

        with tempfile.TemporaryDirectory() as temp_dir:
            artifact = Path(temp_dir) / "best.pt"
            artifact.write_bytes(b"verified model")
            active_model = {
                "version_key": "custom-v1",
                "artifact_path": str(artifact),
                "artifact_sha256": hashlib.sha256(b"verified model").hexdigest(),
                "label_map": {"Reach stacker": "reach_stacker"},
            }
            loaded_model = MagicMock()
            with patch("detection.tracked_detector.YOLO", return_value=loaded_model) as yolo:
                detector.configure_detection_control(
                    coco_classes=frozenset({"truck"}),
                    custom_classes=frozenset({"reach_stacker"}),
                    active_model=active_model,
                )
                detector._reset_tracker_on_next_frame = False
                base_state = {17: {"canonical_class": "truck"}}
                custom_window = MagicMock()
                custom_candidate = {"last_seen": 2}
                detector._base_track_state = base_state
                detector._custom_windows = {"track:17:reach_stacker": custom_window}
                detector._custom_candidates = {"track:17:reach_stacker": custom_candidate}

                detector.configure_detection_control(
                    coco_classes=frozenset({"truck"}),
                    custom_classes=frozenset({"reach_stacker"}),
                    active_model={**active_model, "label_map": dict(reversed(list(active_model["label_map"].items())))},
                )

        self.assertIs(detector._base_track_state, base_state)
        self.assertIs(detector._custom_windows["track:17:reach_stacker"], custom_window)
        self.assertIs(detector._custom_candidates["track:17:reach_stacker"], custom_candidate)
        self.assertFalse(detector._reset_tracker_on_next_frame)
        yolo.assert_called_once_with(str(artifact))

    def test_actual_detection_control_change_resets_tracking_state(self):
        detector = self._detector()
        detector._detection_control_fingerprint = (
            ("truck",),
            (),
            None,
            None,
            None,
            (),
        )
        detector._enabled_coco_classes = frozenset({"truck"})
        detector._enabled_custom_classes = frozenset()
        detector._base_track_state = {17: {"canonical_class": "truck"}}
        detector._custom_windows = {"candidate": MagicMock()}
        detector._custom_candidates = {"candidate": {"last_seen": 2}}

        detector.configure_detection_control(
            coco_classes=frozenset({"truck", "bus"}),
            custom_classes=frozenset(),
            active_model=None,
        )

        self.assertEqual(detector._base_track_state, {})
        self.assertEqual(detector._custom_windows, {})
        self.assertEqual(detector._custom_candidates, {})
        self.assertTrue(detector._reset_tracker_on_next_frame)

    def test_unified_runtime_uses_one_tracked_model_and_keeps_custom_two_of_three(self):
        detector = self._detector()
        detector._runtime_mode = "UNIFIED"
        detector._enabled_coco_classes = frozenset()
        detector._enabled_custom_classes = frozenset({"reach_stacker"})
        detector._custom_label_map = {"reach_stacker": "reach_stacker"}
        detector.model = MagicMock()
        detector.tracker = "bytetrack.yaml"
        detector.inference_quantize = None

        boxes = MagicMock()
        boxes.__len__.return_value = 1
        boxes.xyxy = np.array([[100.0, 100.0, 240.0, 230.0]])
        boxes.cls = np.array([0.0])
        boxes.conf = np.array([0.80])
        boxes.id = MagicMock()
        boxes.id.int.return_value.cpu.return_value.numpy.return_value.tolist.return_value = [42]
        result = MagicMock(boxes=boxes)
        unified_model = MagicMock()
        unified_model.names = {0: "reach_stacker"}
        unified_model.track.return_value = [result]
        detector._custom_model = unified_model

        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        self.assertEqual(detector.track(frame), [])
        second = detector.track(frame)

        self.assertEqual(len(second), 1)
        self.assertEqual(second[0]["canonicalClass"], "reach_stacker")
        self.assertEqual(second[0]["trackId"], 42)
        self.assertTrue(second[0]["customConfirmed"])
        self.assertEqual(unified_model.track.call_count, 2)
        detector.model.track.assert_not_called()

    def test_unified_load_failure_falls_back_to_registry_coco_classes(self):
        detector = self._detector()
        detector._custom_model = None
        detector._custom_version_key = None
        detector._custom_label_map = {}
        with tempfile.TemporaryDirectory() as temp_dir:
            artifact = Path(temp_dir) / "broken.pt"
            artifact.write_bytes(b"not a real checkpoint")
            with patch("detection.tracked_detector.YOLO", side_effect=RuntimeError("corrupt model")):
                detector.configure_detection_control(
                    coco_classes=frozenset(),
                    custom_classes=frozenset({"truck", "reach_stacker"}),
                    active_model={
                        "version_key": "unified-broken",
                        "artifact_path": str(artifact),
                        "artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                        "label_map": {"truck": "truck", "reach_stacker": "reach_stacker"},
                        "runtime_mode": "UNIFIED",
                    },
                )

        self.assertEqual(detector._runtime_mode, "SUPPLEMENTAL")
        self.assertEqual(detector._enabled_coco_classes, frozenset({"truck"}))
        self.assertEqual(detector._enabled_custom_classes, frozenset())

    def test_bus_stays_bus_train_is_not_whitelisted(self):
        detector = self._detector()
        bus = detector._new_base_detection(
            bbox=[10, 10, 100, 100], width=640, height=480,
            canonical_class="bus", confidence=0.80, track_id=7,
        )
        train = detector._new_base_detection(
            bbox=[120, 10, 220, 100], width=640, height=480,
            canonical_class="train", confidence=0.90, track_id=8,
        )
        observed = detector._filter_and_gate_base([bus, train])
        self.assertEqual([item["canonicalClass"] for item in observed], ["bus"])
        self.assertEqual(observed[0]["class"], "bus")
        self.assertEqual(TrackedYoloDetector._canonicalize_detection_class("train"), ("train", None))

    def test_static_shipping_container_cannot_become_truck(self):
        detector = self._detector()
        container = detector._new_base_detection(
            bbox=[10, 10, 100, 100], width=640, height=480,
            canonical_class="shipping_container", confidence=0.99, track_id=1,
        )
        self.assertEqual(detector._filter_and_gate_base([container]), [])

    def test_low_confidence_can_continue_but_cannot_initiate(self):
        detector = self._detector()
        strong = detector._new_base_detection(
            bbox=[10, 10, 100, 100], width=640, height=480,
            canonical_class="truck", confidence=0.80, track_id=3,
        )
        self.assertTrue(detector._filter_and_gate_base([strong])[0]["canInitiate"])
        weak = detector._new_base_detection(
            bbox=[11, 10, 101, 100], width=640, height=480,
            canonical_class="truck", confidence=0.20, track_id=3,
        )
        continued = detector._filter_and_gate_base([weak])
        self.assertEqual(len(continued), 1)
        self.assertFalse(continued[0]["canInitiate"])
        self.assertTrue(continued[0]["canContinue"])
        new_weak = detector._new_base_detection(
            bbox=[10, 10, 100, 100], width=640, height=480,
            canonical_class="truck", confidence=0.20, track_id=4,
        )
        self.assertEqual(detector._filter_and_gate_base([new_weak]), [])

    def test_ultralytics_precision_uses_quantize_without_deprecated_half(self):
        detector = self._detector()
        detector.device = "cuda"
        detector.inference_quantize = 16
        model = MagicMock()
        model.names = {0: "Reach stacker"}
        model.return_value = [self._Result(0.70)]
        detector._custom_model = model

        detector._collect_custom_detections(np.zeros((480, 640, 3), dtype=np.uint8), 640, 480)

        kwargs = model.call_args.kwargs
        self.assertEqual(kwargs["quantize"], 16)
        self.assertEqual(kwargs["imgsz"], 768)
        self.assertNotIn("half", kwargs)

    def test_warmup_runs_normal_tracking_path_and_always_resets_state(self):
        detector = self._detector()
        detector.track = MagicMock(side_effect=RuntimeError("warmup failure"))
        detector.reset_tracking = MagicMock()

        with self.assertRaisesRegex(RuntimeError, "warmup failure"):
            detector.warmup((640, 480))

        frame = detector.track.call_args.args[0]
        self.assertEqual(frame.shape, (480, 640, 3))
        detector.reset_tracking.assert_called_once_with()

    def test_unconfirmed_custom_overlap_does_not_relabel_base_track(self):
        detector = self._detector()
        base = detector._new_base_detection(
            bbox=[100, 100, 240, 230], width=640, height=480,
            canonical_class="truck", confidence=0.85, track_id=11,
        )
        base = detector._filter_and_gate_base([base])
        result = detector._apply_custom_augmentation(np.zeros((480, 640, 3), dtype=np.uint8), base, 640, 480)
        self.assertEqual(result[0]["canonicalClass"], "truck")
        self.assertFalse(result[0]["customConfirmed"])

    def test_custom_relabels_only_after_exact_two_of_three(self):
        detector = self._detector()
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        first = detector._filter_and_gate_base([detector._new_base_detection(
            bbox=[100, 100, 240, 230], width=640, height=480,
            canonical_class="truck", confidence=0.85, track_id=11,
        )])
        first = detector._apply_custom_augmentation(frame, first, 640, 480)
        self.assertEqual(first[0]["canonicalClass"], "truck")
        second = detector._filter_and_gate_base([detector._new_base_detection(
            bbox=[100, 100, 240, 230], width=640, height=480,
            canonical_class="truck", confidence=0.85, track_id=11,
        )])
        second = detector._apply_custom_augmentation(frame, second, 640, 480)
        self.assertEqual(second[0]["canonicalClass"], "reach_stacker")
        self.assertTrue(second[0]["customConfirmed"])
        self.assertLess(second[0]["trackId"], 0)
        self.assertTrue(second[0]["canInitiate"])

    def test_custom_identity_survives_changed_or_missing_base_track(self):
        detector = self._detector()
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        def base_detection(track_id):
            if track_id is None:
                return []
            return detector._filter_and_gate_base([detector._new_base_detection(
                bbox=[110, 110, 210, 200], width=640, height=480,
                canonical_class="truck", confidence=0.85, track_id=track_id,
            )])

        first = detector._apply_custom_augmentation(frame, base_detection(11), 640, 480)
        self.assertEqual(first[0]["canonicalClass"], "truck")
        second = detector._apply_custom_augmentation(frame, base_detection(27), 640, 480)
        self.assertEqual([item["canonicalClass"] for item in second], ["reach_stacker"])
        custom_track_id = second[0]["trackId"]
        self.assertLess(custom_track_id, 0)

        third = detector._apply_custom_augmentation(frame, base_detection(None), 640, 480)
        self.assertEqual([item["canonicalClass"] for item in third], ["reach_stacker"])
        self.assertEqual(third[0]["trackId"], custom_track_id)

    def test_confirmed_custom_class_is_retained_on_interval_frame(self):
        detector = self._detector()
        detector._custom_interval = 2
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        outputs = []
        for _ in range(5):
            base = detector._filter_and_gate_base([detector._new_base_detection(
                bbox=[110, 110, 210, 200], width=640, height=480,
                canonical_class="truck", confidence=0.85, track_id=11,
            )])
            outputs.append(detector._apply_custom_augmentation(frame, base, 640, 480))

        self.assertEqual(outputs[3][0]["canonicalClass"], "reach_stacker")
        retained = outputs[4][0]
        self.assertEqual(retained["canonicalClass"], "reach_stacker")
        self.assertLess(retained["trackId"], 0)
        self.assertEqual(retained["bbox"], [100, 100, 240, 230])
        self.assertFalse(retained["canInitiate"])
        self.assertTrue(retained["canContinue"])

    def test_confirmed_custom_expires_after_custom_and_base_grace_are_both_exhausted(self):
        detector = self._detector()
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        def base_detection():
            return detector._filter_and_gate_base([detector._new_base_detection(
                bbox=[100, 100, 240, 230], width=640, height=480,
                canonical_class="truck", confidence=0.85, track_id=11,
            )])

        detector._apply_custom_augmentation(frame, base_detection(), 640, 480)
        confirmed = detector._apply_custom_augmentation(frame, base_detection(), 640, 480)
        self.assertEqual(confirmed[0]["canonicalClass"], "reach_stacker")

        detector._collect_custom_detections = MagicMock(return_value=[])
        held = []
        for _ in range(12):
            detector._base_frame_index += 1
            held.append(detector._apply_custom_augmentation(frame, [], 640, 480))
        for output in held:
            self.assertEqual([item["canonicalClass"] for item in output], ["reach_stacker"])
        detector._base_frame_index += 1
        expired = detector._apply_custom_augmentation(frame, [], 640, 480)
        self.assertEqual(expired, [])

    def test_spatial_base_support_carries_custom_label_through_long_model_gap(self):
        detector = self._detector()
        detector._custom_base_hold_frames = 12
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        def base_detection(track_id, offset=0):
            return detector._filter_and_gate_base([detector._new_base_detection(
                bbox=[110 + offset, 110, 210 + offset, 200], width=640, height=480,
                canonical_class="truck", confidence=0.85, track_id=track_id,
            )])

        detector._apply_custom_augmentation(frame, base_detection(11), 640, 480)
        confirmed = detector._apply_custom_augmentation(frame, base_detection(11), 640, 480)
        custom_track_id = confirmed[0]["trackId"]
        detector._collect_custom_detections = MagicMock(return_value=[])

        for index in range(15):
            output = detector._apply_custom_augmentation(
                frame,
                base_detection(20 + index, offset=index),
                640,
                480,
            )
            self.assertEqual([item["canonicalClass"] for item in output], ["reach_stacker"])
            self.assertEqual(output[0]["trackId"], custom_track_id)
        self.assertGreater(output[0]["bbox"][0], confirmed[0]["bbox"][0])

    def test_confirmed_low_confidence_custom_label_is_visible_between_inferences(self):
        detector = self._detector()
        detector._custom_interval = 2
        detector._custom_model = self._CustomModel(confidence=0.35)
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        outputs = []
        for _ in range(5):
            base = detector._filter_and_gate_base([detector._new_base_detection(
                bbox=[110, 110, 210, 200], width=640, height=480,
                canonical_class="truck", confidence=0.85, track_id=11,
            )])
            outputs.append(detector._apply_custom_augmentation(frame, base, 640, 480))

        self.assertEqual(outputs[3][0]["canonicalClass"], "reach_stacker")
        self.assertFalse(outputs[3][0]["canInitiate"])
        self.assertEqual(outputs[4][0]["canonicalClass"], "reach_stacker")
        self.assertFalse(outputs[4][0]["canInitiate"])

    def test_confirmed_custom_box_uses_ema_and_bounded_edge_step(self):
        detector = self._detector()
        detector._enabled_coco_classes = frozenset()
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        def candidate(box):
            return {
                "trackId": None,
                "bbox": box,
                "normalized_bbox": [box[0] / 640, box[1] / 480, box[2] / 640, box[3] / 480],
                "class": "reach_stacker",
                "canonicalClass": "reach_stacker",
                "label": "Reach stacker",
                "confidence": 0.82,
                "source": "CUSTOM",
                "candidateVersion": "custom-v1",
                "customConfirmed": False,
                "canInitiate": False,
                "canContinue": False,
            }

        detector._collect_custom_detections = MagicMock(side_effect=[
            [candidate([100, 100, 240, 230])],
            [candidate([100, 100, 240, 230])],
            [candidate([180, 100, 320, 230])],
        ])
        self.assertEqual(detector._apply_custom_augmentation(frame, [], 640, 480), [])
        confirmed = detector._apply_custom_augmentation(frame, [], 640, 480)
        moved = detector._apply_custom_augmentation(frame, [], 640, 480)

        self.assertEqual(confirmed[0]["bbox"], [100, 100, 240, 230])
        self.assertEqual(moved[0]["bbox"], [110, 100, 250, 230])
        self.assertEqual(moved[0]["trackId"], confirmed[0]["trackId"])

    def test_base_carried_custom_box_uses_the_same_bounded_edge_step(self):
        detector = self._detector()
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        def base(box, track_id):
            return detector._filter_and_gate_base([detector._new_base_detection(
                bbox=box,
                width=640,
                height=480,
                canonical_class="truck",
                confidence=0.85,
                track_id=track_id,
            )])

        detector._apply_custom_augmentation(
            frame, base([100, 100, 240, 230], 11), 640, 480,
        )
        confirmed = detector._apply_custom_augmentation(
            frame, base([100, 100, 240, 230], 11), 640, 480,
        )
        detector._collect_custom_detections = MagicMock(return_value=[])
        carried = detector._apply_custom_augmentation(
            frame, base([140, 100, 280, 230], 27), 640, 480,
        )

        self.assertEqual(carried[0]["canonicalClass"], "reach_stacker")
        self.assertEqual(carried[0]["trackId"], confirmed[0]["trackId"])
        self.assertEqual(carried[0]["bbox"], [110, 100, 250, 230])

    def test_person_component_suppression_is_narrow_and_preserves_grounded_people(self):
        detector = self._detector()
        confirmed_reach = [{
            "class": "reach_stacker",
            "canonicalClass": "reach_stacker",
            "confirmed": True,
            "bbox": [100, 100, 300, 350],
        }]

        def person(box, confidence=0.44):
            return {
                "class": "person",
                "canonicalClass": "person",
                "bbox": box,
                "confidence": confidence,
                "source": "COCO",
            }

        floating_component = person([150, 120, 210, 260])
        grounded_person = person([150, 190, 210, 340])
        high_confidence_person = person([150, 120, 210, 260], confidence=0.70)
        outside_person = person([320, 120, 380, 300])

        self.assertTrue(detector._is_person_component_false_positive(
            floating_component, confirmed_reach,
        ))
        self.assertFalse(detector._is_person_component_false_positive(
            grounded_person, confirmed_reach,
        ))
        self.assertFalse(detector._is_person_component_false_positive(
            high_confidence_person, confirmed_reach,
        ))
        self.assertFalse(detector._is_person_component_false_positive(
            outside_person, confirmed_reach,
        ))

    def test_confirmed_reach_output_removes_only_the_floating_person_component(self):
        detector = self._detector()
        detector._custom_candidates = {
            "spatial:reach_stacker:1": {
                "class": "reach_stacker",
                "clock_domain": "full_frame_custom_opportunity",
                "confirmed": True,
                "trackId": -1,
                "bbox": [100, 100, 300, 350],
                "normalized_bbox": [100 / 640, 100 / 480, 300 / 640, 350 / 480],
                "last_seen": 0,
                "label": "Xe nâng",
                "confidence": 0.62,
            },
        }
        floating_component = {
            "class": "person",
            "canonicalClass": "person",
            "bbox": [150, 120, 210, 260],
            "normalized_bbox": [150 / 640, 120 / 480, 210 / 640, 260 / 480],
            "confidence": 0.44,
            "trackId": 2,
            "source": "COCO",
        }

        output = detector._retain_confirmed_custom_tracks([floating_component])

        self.assertEqual(
            [detection["canonicalClass"] for detection in output],
            ["reach_stacker"],
        )

    def test_confirmed_custom_only_candidate_keeps_its_synthetic_identity(self):
        detector = self._detector()
        detector._enabled_coco_classes = frozenset()
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        detector._base_frame_index = 1
        first = detector._apply_custom_augmentation(frame, [], 640, 480)
        self.assertEqual(first, [])
        detector._base_frame_index = 2
        second = detector._apply_custom_augmentation(frame, [], 640, 480)
        self.assertEqual(len(second), 1)
        self.assertTrue(second[0]["customConfirmed"])
        track_id = second[0]["trackId"]
        detector._base_frame_index = 3
        third = detector._apply_custom_augmentation(frame, [], 640, 480)
        self.assertEqual(third[0]["trackId"], track_id)

    def test_confirmed_custom_only_candidate_is_retained_between_inferences(self):
        detector = self._detector()
        detector._enabled_coco_classes = frozenset()
        detector._custom_interval = 2
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        outputs = []
        for base_frame_index in range(1, 6):
            detector._base_frame_index = base_frame_index
            outputs.append(detector._apply_custom_augmentation(frame, [], 640, 480))
        self.assertEqual(outputs[0], [])
        self.assertEqual(outputs[1], [])
        self.assertEqual(outputs[2], [])
        self.assertTrue(outputs[3][0]["canInitiate"])
        self.assertEqual(outputs[4][0]["trackId"], outputs[3][0]["trackId"])
        self.assertFalse(outputs[4][0]["canInitiate"])
        self.assertTrue(outputs[4][0]["canContinue"])

    def test_same_class_nms_never_merges_different_semantics(self):
        kept = TrackedYoloDetector._same_class_nms([
            {"bbox": [10, 10, 100, 100], "canonicalClass": "truck", "confidence": 0.9},
            {"bbox": [12, 12, 102, 102], "canonicalClass": "reach_stacker", "confidence": 0.8},
        ])
        self.assertEqual({item["canonicalClass"] for item in kept}, {"truck", "reach_stacker"})


class TestViolationStateMachine(unittest.TestCase):
    def setUp(self):
        self.checker = ZoneChecker(camera_id="BAI-KIEM", grace_frames=3, minimum_violation_seconds=1.0)
        self.zones = [{
            "id": "zone-1", "name": "Yard",
            "polygon_points": [{"x": 0, "y": 0}, {"x": 0.5, "y": 0}, {"x": 0.5, "y": 0.5}, {"x": 0, "y": 0.5}],
            "rule_type": "PROHIBIT_SPECIFIED", "target_labels": ["Xe máy"],
        }]
        self.class_map = {"motorcycle": ["Xe máy"]}

    def _inside(self, track_id: int = 1) -> dict[str, object]:
        item = detection(track_id, "motorcycle", bbox=[100, 100, 200, 200])
        item["label"] = "Xe máy"
        return item

    def test_one_second_confirmation_then_observed_exit(self):
        t0 = datetime(2026, 8, 18, 10, 0, tzinfo=timezone.utc)
        _, initial = self.checker.check_detections([self._inside()], self.zones, self.class_map, timestamp=t0)
        self.assertEqual(initial, [])
        _, started = self.checker.check_detections([self._inside()], self.zones, self.class_map, timestamp=t0 + timedelta(seconds=1))
        self.assertEqual([transition.action for transition in started], ["STARTED"])
        outside = self._inside()
        outside["bbox"] = [500, 400, 600, 450]
        outside["normalized_bbox"] = [0.7, 0.7, 0.9, 0.9]
        for second in (2, 3):
            _, transitions = self.checker.check_detections([outside], self.zones, self.class_map, timestamp=t0 + timedelta(seconds=second))
            self.assertEqual(transitions, [])
        _, ended = self.checker.check_detections([outside], self.zones, self.class_map, timestamp=t0 + timedelta(seconds=4))
        self.assertEqual([transition.action for transition in ended], ["ENDED"])

    def test_missing_track_reconnects_before_twelve_seconds(self):
        t0 = datetime(2026, 8, 18, 10, 0, tzinfo=timezone.utc)
        self.checker.check_detections([self._inside()], self.zones, self.class_map, timestamp=t0)
        _, started = self.checker.check_detections([self._inside()], self.zones, self.class_map, timestamp=t0 + timedelta(seconds=1))
        violation_id = started[0].violation_id
        _, transitions = self.checker.check_detections([], self.zones, self.class_map, timestamp=t0 + timedelta(seconds=11))
        self.assertEqual(transitions, [])
        reidentified = self._inside(track_id=99)
        _, transitions = self.checker.check_detections([reidentified], self.zones, self.class_map, timestamp=t0 + timedelta(seconds=11.5))
        self.assertEqual(transitions, [])
        active = next(iter(self.checker.active_violations.values()))
        self.assertEqual(active.violation_id, violation_id)
        self.assertEqual(active.track_id, 99)

    def test_missing_track_closes_at_twelve_second_grace(self):
        t0 = datetime(2026, 8, 18, 10, 0, tzinfo=timezone.utc)
        self.checker.check_detections([self._inside()], self.zones, self.class_map, timestamp=t0)
        self.checker.check_detections([self._inside()], self.zones, self.class_map, timestamp=t0 + timedelta(seconds=1))
        _, before_timeout = self.checker.check_detections([], self.zones, self.class_map, timestamp=t0 + timedelta(seconds=12.9))
        self.assertEqual(before_timeout, [])
        _, ended = self.checker.check_detections([], self.zones, self.class_map, timestamp=t0 + timedelta(seconds=13.0))
        self.assertEqual([transition.action for transition in ended], ["ENDED"])

    def test_failed_close_restores_exact_state_and_same_class_track_sustains(self):
        t0 = datetime(2026, 8, 18, 10, 0, tzinfo=timezone.utc)
        inside = self._inside()
        expected_bbox = tuple(inside["normalized_bbox"])
        self.checker.check_detections([inside], self.zones, self.class_map, timestamp=t0)
        _, started = self.checker.check_detections(
            [inside], self.zones, self.class_map, timestamp=t0 + timedelta(seconds=1)
        )
        violation_id = started[0].violation_id

        outside = self._inside()
        outside["bbox"] = [500, 400, 600, 450]
        outside["normalized_bbox"] = [0.7, 0.7, 0.9, 0.9]
        for second in (2, 3):
            self.checker.check_detections(
                [outside], self.zones, self.class_map, timestamp=t0 + timedelta(seconds=second)
            )
        _, ended = self.checker.check_detections(
            [outside], self.zones, self.class_map, timestamp=t0 + timedelta(seconds=4)
        )
        transition = ended[0]

        # These are the persistence-facing close values and must not be changed
        # by an in-memory retry restoration.
        self.assertEqual(transition.exited_at, t0 + timedelta(seconds=1))
        self.assertEqual(transition.duration_seconds, 1)
        self.checker.restore_ended_transition(transition)
        self.assertEqual(transition.exited_at, t0 + timedelta(seconds=1))
        self.assertEqual(transition.duration_seconds, 1)

        restored = next(iter(self.checker.active_violations.values()))
        self.assertEqual(restored.violation_id, violation_id)
        self.assertEqual(restored.yolo_class, "motorcycle")
        self.assertEqual(restored.normalized_bbox, expected_bbox)
        self.assertEqual(restored.last_seen_inside, t0 + timedelta(seconds=1))
        self.assertEqual(restored.consecutive_outside, self.checker.grace_frames)

        weak_inside = self._inside()
        weak_inside["canInitiate"] = False
        weak_inside["canContinue"] = True
        _, transitions = self.checker.check_detections(
            [weak_inside], self.zones, self.class_map, timestamp=t0 + timedelta(seconds=5)
        )
        self.assertEqual(transitions, [])
        sustained = next(iter(self.checker.active_violations.values()))
        self.assertEqual(sustained.violation_id, violation_id)
        self.assertEqual(sustained.last_seen_inside, t0 + timedelta(seconds=5))
        self.assertEqual(sustained.consecutive_outside, 0)

    def test_boundary_buffer_does_not_close_a_live_event(self):
        t0 = datetime(2026, 8, 18, 10, 0, tzinfo=timezone.utc)
        self.checker.check_detections([self._inside()], self.zones, self.class_map, timestamp=t0)
        _, started = self.checker.check_detections([self._inside()], self.zones, self.class_map, timestamp=t0 + timedelta(seconds=1))
        edge = self._inside()
        edge["bbox"] = [300, 100, 360, 200]
        edge["normalized_bbox"] = [0.49, 0.2, 0.53, 0.4]
        for second in (2, 3, 4):
            annotated, transitions = self.checker.check_detections([edge], self.zones, self.class_map, timestamp=t0 + timedelta(seconds=second))
            self.assertEqual(transitions, [])
            self.assertEqual(annotated[0]["status"], "VIOLATION")
        self.assertEqual(len(self.checker.active_violations), 1)

    def test_low_confidence_cannot_open_pending_but_can_sustain_same_class(self):
        t0 = datetime(2026, 8, 18, 10, 0, tzinfo=timezone.utc)
        weak = self._inside()
        weak["canInitiate"] = False
        weak["canContinue"] = True
        _, transitions = self.checker.check_detections([weak], self.zones, self.class_map, timestamp=t0)
        self.assertEqual(transitions, [])
        self.assertEqual(self.checker.pending_violations, {})
        self.assertEqual(self.checker.active_violations, {})

        self.checker.check_detections([self._inside()], self.zones, self.class_map, timestamp=t0 + timedelta(seconds=1))
        _, started = self.checker.check_detections([self._inside()], self.zones, self.class_map, timestamp=t0 + timedelta(seconds=2))
        self.assertEqual([transition.action for transition in started], ["STARTED"])
        active_before = next(iter(self.checker.active_violations.values()))
        _, transitions = self.checker.check_detections([weak], self.zones, self.class_map, timestamp=t0 + timedelta(seconds=3))
        self.assertEqual(transitions, [])
        active_after = next(iter(self.checker.active_violations.values()))
        self.assertEqual(active_after.violation_id, active_before.violation_id)
        self.assertEqual(active_after.last_seen_inside, t0 + timedelta(seconds=3))

    def test_reidentification_requires_exact_canonical_class(self):
        t0 = datetime(2026, 8, 18, 10, 0, tzinfo=timezone.utc)
        self.checker.check_detections([self._inside()], self.zones, self.class_map, timestamp=t0)
        _, started = self.checker.check_detections([self._inside()], self.zones, self.class_map, timestamp=t0 + timedelta(seconds=1))
        original_id = started[0].violation_id

        zones = [{**self.zones[0], "target_labels": ["Xe máy", "Xe tải"]}]
        class_map = {**self.class_map, "truck": ["Xe tải"]}
        incompatible = detection(99, "truck", bbox=[100, 100, 200, 200])
        incompatible["label"] = "Xe tải"
        _, transitions = self.checker.check_detections([incompatible], zones, class_map, timestamp=t0 + timedelta(seconds=2))
        self.assertEqual(transitions, [])
        active = next(iter(self.checker.active_violations.values()))
        self.assertEqual(active.violation_id, original_id)
        self.assertEqual(active.track_id, 1)
        self.assertIn(("BAI-KIEM", 99, "zone-1"), self.checker.pending_violations)


    def test_end_all_returns_one_close_per_active_and_clears_pending(self):
        t0 = datetime(2026, 8, 25, 9, 0, tzinfo=timezone.utc)
        self.checker.active_violations[("BAI-KIEM", 7, "zone-1")] = ActiveViolation(
            violation_id="violation-active",
            camera_id="BAI-KIEM",
            track_id=7,
            zone_id="zone-1",
            zone_name="JJJMới 1",
            object_label="Xe nâng",
            entered_at=t0,
            last_seen_inside=t0 + timedelta(seconds=3),
            normalized_bbox=(0.1, 0.1, 0.3, 0.4),
            yolo_class="reach_stacker",
        )
        self.checker.pending_violations[("BAI-KIEM", 8, "zone-1")] = PendingViolation(
            camera_id="BAI-KIEM",
            track_id=8,
            zone_id="zone-1",
            zone_name="JJJMới 1",
            object_label="Người",
            entered_at=t0 + timedelta(seconds=1),
            last_seen_inside=t0 + timedelta(seconds=2),
            normalized_bbox=(0.5, 0.2, 0.55, 0.5),
            yolo_class="person",
        )

        transitions = self.checker.end_all(t0 + timedelta(seconds=10))

        self.assertEqual([item.action for item in transitions], ["ENDED"])
        self.assertEqual(transitions[0].violation_id, "violation-active")
        self.assertEqual(transitions[0].duration_seconds, 10)
        self.assertEqual(self.checker.active_violations, {})
        self.assertEqual(self.checker.pending_violations, {})

    def test_clear_runtime_state_reports_counts_without_emitting(self):
        t0 = datetime(2026, 8, 25, 9, 0, tzinfo=timezone.utc)
        self.checker.active_violations[("BAI-KIEM", 7, "zone-1")] = ActiveViolation(
            "violation-active", "BAI-KIEM", 7, "zone-1", "JJJMới 1", "Xe nâng", t0, t0
        )
        self.checker.pending_violations[("BAI-KIEM", 8, "zone-1")] = PendingViolation(
            "BAI-KIEM", 8, "zone-1", "JJJMới 1", "Người", t0, t0,
            (0.5, 0.2, 0.55, 0.5), "person"
        )

        self.assertEqual(self.checker.clear_runtime_state(), (1, 1))
        self.assertEqual(self.checker.active_violations, {})
        self.assertEqual(self.checker.pending_violations, {})


class TestAreaPipelineControl(unittest.TestCase):
    def _pipeline(self, detector: MagicMock, snapshot: ZoneSnapshot) -> AreaPipeline:
        sync = MagicMock()
        sync.get_snapshot.return_value = snapshot
        return AreaPipeline(
            camera_id="BAI-KIEM", source=None, target_fps=1, resolution=(64, 48),
            detector=detector, zone_sync=sync,
        )

    def test_prepare_loads_detection_control_and_warms_without_consuming_video(self):
        detector = MagicMock()
        snapshot = ZoneSnapshot(
            coco_classes=frozenset({"truck"}),
            custom_classes=frozenset(),
            active_model=None,
        )
        sync = MagicMock()
        sync.refresh_now = AsyncMock(return_value=True)
        sync.get_snapshot.return_value = snapshot
        reader = MagicMock()
        pipeline = AreaPipeline(
            camera_id="BAI-KIEM",
            source=None,
            target_fps=10,
            resolution=(1280, 720),
            detector=detector,
            zone_sync=sync,
            reader=reader,
        )

        prepared = asyncio.run(pipeline.prepare())

        self.assertTrue(prepared)
        sync.refresh_now.assert_awaited_once_with()
        detector.configure_detection_control.assert_called_once_with(
            coco_classes=frozenset({"truck"}),
            custom_classes=frozenset(),
            active_model=None,
        )
        detector.warmup.assert_called_once_with((1280, 720))
        reader.read_frame.assert_not_called()

    def test_empty_active_model_disables_custom_despite_legacy_environment(self):
        detector = MagicMock()
        detector.track.return_value = []
        snapshot = ZoneSnapshot(coco_classes=frozenset({"truck"}), custom_classes=frozenset(), active_model=None)
        with patch.dict(os.environ, {"CUSTOM_AUGMENT_FORCE_DEFAULT": "true", "CUSTOM_AUGMENT_ARTIFACT": "ignored.pt"}):
            pipeline = self._pipeline(detector, snapshot)
            response = pipeline.process_single_frame()
        self.assertTrue(response["success"])
        detector.configure_detection_control.assert_called_once_with(
            coco_classes=frozenset({"truck"}), custom_classes=frozenset(), active_model=None,
        )

    def test_process_single_frame_returns_complete_area_feed_shape(self):
        detector = MagicMock()
        detector.track.return_value = []
        snapshot = ZoneSnapshot(
            zones=(MappingProxyType({
                "id": "zone-1",
                "name": "Khu vực kiểm tra",
                "polygon_points": (
                    MappingProxyType({"x": 0.0, "y": 0.0}),
                    MappingProxyType({"x": 1.0, "y": 0.0}),
                    MappingProxyType({"x": 1.0, "y": 1.0}),
                ),
                "rule_type": "PROHIBIT_SPECIFIED",
                "target_labels": ("Xe tải",),
            }),),
            class_to_labels={"truck": ("Xe tải",)},
            coco_classes=frozenset({"truck"}),
        )
        pipeline = self._pipeline(detector, snapshot)

        response = pipeline.process_single_frame()

        self.assertTrue(response["success"])
        self.assertEqual(response["camera_id"], "BAI-KIEM")
        self.assertIsInstance(response["timestamp"], int)
        self.assertEqual(response["frame"].shape, (48, 64, 3))
        self.assertTrue(response["image_base64"].startswith("data:image/jpeg;base64,"))
        self.assertEqual(response["detections"], [])
        self.assertEqual(response["transitions"], [])
        self.assertEqual(response["zones"], [{
            "id": "zone-1",
            "name": "Khu vực kiểm tra",
            "polygon": [
                {"x": 0.0, "y": 0.0},
                {"x": 1.0, "y": 0.0},
                {"x": 1.0, "y": 1.0},
            ],
            "ruleType": "PROHIBIT_SPECIFIED",
            "targetLabels": ["Xe tải"],
        }])
        json.dumps(response["zones"])
        self.assertGreaterEqual(response["fps"], 0.0)
        self.assertFalse(response["source_reset"])
        detector.track.assert_called_once()

    def test_process_single_frame_passes_actual_frame_size_to_zone_checker(self):
        detector = MagicMock()
        detector.track.return_value = []
        snapshot = ZoneSnapshot(coco_classes=frozenset({"truck"}))
        pipeline = self._pipeline(detector, snapshot)
        zone_checker = MagicMock()
        zone_checker.check_detections.return_value = ([], [])
        pipeline.zone_checker = zone_checker

        response = pipeline.process_single_frame()

        self.assertTrue(response["success"])
        zone_checker.check_detections.assert_called_once()
        self.assertEqual(
            zone_checker.check_detections.call_args.kwargs["frame_size"],
            (64, 48),
        )

    def test_source_reset_clears_tracking_before_processing_new_timeline(self):
        detector = MagicMock()
        detector.track.return_value = []
        snapshot = ZoneSnapshot(coco_classes=frozenset({"truck"}))
        pipeline = self._pipeline(detector, snapshot)
        reader = MagicMock()
        reader.read_frame.return_value = (True, np.zeros((48, 64, 3), dtype=np.uint8))
        reader.did_loop = True
        pipeline.reader = reader
        pipeline.buffer = MagicMock()

        response = pipeline.process_single_frame()

        self.assertTrue(response["source_reset"])
        detector.reset_tracking.assert_called_once_with()
        pipeline.buffer.clear.assert_called_once_with()
        detector.track.assert_called_once()

    def test_completed_local_source_closes_first_pass_then_suppresses_replay_rows(self):
        detector = MagicMock()
        detector.track.return_value = []
        snapshot = ZoneSnapshot(coco_classes=frozenset({"truck"}))
        reader = MagicMock()
        reader.did_loop = True
        reader.read_frame.return_value = (True, np.zeros((48, 64, 3), dtype=np.uint8))
        reader.get_source_context.return_value = {
            "source_kind": "LOCAL_FILE",
            "source_ref": "sample.mp4",
            "source_position_seconds": 0.0,
            "source_timestamp": None,
        }
        reader.get_playback_state.return_value = {"durationSeconds": 10.0}
        sync = MagicMock()
        sync.get_snapshot.return_value = snapshot
        pipeline = AreaPipeline(
            camera_id="BAI-KIEM",
            source=None,
            target_fps=10,
            resolution=(64, 48),
            detector=detector,
            zone_sync=sync,
            reader=reader,
            persistence=MagicMock(),
        )
        fingerprint = pipeline._coverage_source()[1]
        completed = datetime.now(timezone.utc)
        pipeline.activity_coverage.restore(
            "LOCAL_FILE",
            fingerprint,
            10.0,
            [[0.0, 10.0]],
            completed,
            completed,
        )
        ended = ActivityTransition(
            action="ENDED", session_id="first-pass", camera_id="BAI-KIEM",
            track_id=1, zone_id="zone-1", zone_name="Zone", object_label="Xe táº£i",
            canonical_class="truck", policy_result="ALLOWED", entered_at=completed,
            last_seen_at=completed, entry_point=(0.5, 0.5), exited_at=completed,
            duration_seconds=1,
        )
        replay_started = ActivityTransition(
            action="STARTED", session_id="replay", camera_id="BAI-KIEM",
            track_id=2, zone_id="zone-1", zone_name="Zone", object_label="Xe táº£i",
            canonical_class="truck", policy_result="ALLOWED", entered_at=completed,
            last_seen_at=completed, entry_point=(0.5, 0.5),
        )
        pipeline.activity_tracker = MagicMock()
        pipeline.activity_tracker.end_all.return_value = [ended]
        pipeline.activity_tracker.check_detections.return_value = [replay_started]
        pipeline.zone_checker = MagicMock()
        pipeline.zone_checker.check_detections.return_value = ([], [])

        response = pipeline.process_single_frame()

        self.assertTrue(pipeline._activity_replay_read_only)
        self.assertEqual(response["activity_transitions"], [ended])
        self.assertIsNone(replay_started.source_metadata)

    def test_publish_result_uses_injected_no_write_persistence_and_emitter(self):
        class PersistenceSink:
            def __init__(self):
                self.created = []

            async def create(self, **payload):
                self.created.append(payload)
                return payload

            async def close(self, **payload):
                return payload

            async def update_clip(self, violation_id, filename):
                return {"violationId": violation_id, "filename": filename}

        class EmitterSink:
            def __init__(self):
                self.frames = []
                self.events = []
                self.alerts = []

            async def emit_frame(self, **payload):
                self.frames.append(payload)
                return True

            async def emit_area_event(self, payload):
                self.events.append(payload)
                return True

            async def emit_alert(self, payload):
                self.alerts.append(payload)
                return True

        persistence = PersistenceSink()
        emitter = EmitterSink()
        detector = MagicMock()
        pipeline = AreaPipeline(
            camera_id="BAI-KIEM", detector=detector, zone_sync=MagicMock(),
            persistence=persistence, emitter=emitter, record_violation_clips=False,
        )
        pipeline.set_viewer_active(True)
        entered_at = datetime(2026, 8, 22, tzinfo=timezone.utc)
        transition = ViolationTransition(
            action="STARTED", violation_id="violation-1", camera_id="BAI-KIEM", track_id=7,
            zone_id="zone-1", zone_name="Benchmark", object_label="Xe tải", status="OPEN",
            entered_at=entered_at,
        )
        result = {
            "success": True, "image_base64": "data:image/jpeg;base64,YWJj", "detections": [],
            "fps": 10.0, "zones": [], "source_reset": False, "transitions": [transition],
        }

        async def scenario():
            pipeline._event_queue.start()
            await pipeline.publish_result(result)
            await pipeline._event_queue.join()
            await pipeline._event_queue.stop()

        asyncio.run(scenario())
        self.assertEqual(len(emitter.frames), 1)
        self.assertEqual(len(emitter.events), 1)
        self.assertEqual(len(emitter.alerts), 1)
        self.assertEqual(len(persistence.created), 1)
        self.assertEqual(persistence.created[0]["violation_id"], "violation-1")
        self.assertEqual(persistence.created[0]["source_kind"], "UNAVAILABLE")
        self.assertFalse(hasattr(pipeline, "_clip_tasks"))
        self.assertEqual(emitter.events[0]["clipStatus"], "NOT_REQUESTED")

    def test_viewer_disconnect_skips_frame_but_keeps_activity_analytics(self):
        class ActivitySink:
            def __init__(self):
                self.created = []

            async def create(self, **payload):
                self.created.append(payload)
                return {"id": payload["session_id"], "was_inserted": True}

            async def close(self, **payload):
                return payload

            async def delete_all(self, _camera_id):
                return 0

            async def update_coverage(self, **_payload):
                return None

        emitter = MagicMock()
        emitter.emit_frame = AsyncMock(return_value=True)
        activity = ActivitySink()
        pipeline = AreaPipeline(
            camera_id="BAI-KIEM",
            detector=MagicMock(),
            zone_sync=MagicMock(),
            persistence=MagicMock(),
            activity_persistence=activity,
            emitter=emitter,
        )
        pipeline.set_viewer_active(False)
        entered = datetime(2026, 8, 28, tzinfo=timezone.utc)
        transition = ActivityTransition(
            action="STARTED", session_id="55555555-5555-4555-8555-555555555555",
            camera_id="BAI-KIEM", track_id=5, zone_id="zone-1", zone_name="Zone 1",
            object_label="Xe tải", canonical_class="truck", policy_result="ALLOWED",
            entered_at=entered, last_seen_at=entered, entry_point=(0.5, 0.8),
            source_metadata={
                "source_kind": "LOCAL_FILE", "source_ref": "sample.mp4",
                "source_position_seconds": 10.0, "source_timestamp": None,
                "event_fingerprint": "c" * 64,
            },
        )
        result = {
            "success": True, "image_base64": "data:image/jpeg;base64,YWJj", "detections": [],
            "fps": 10.0, "zones": [], "source_reset": False, "transitions": [],
            "activity_transitions": [transition],
        }

        async def scenario():
            pipeline._activity_queue.start()
            await pipeline.publish_result(result)
            await pipeline._activity_queue.join()
            await pipeline._activity_queue.stop()

        asyncio.run(scenario())
        emitter.emit_frame.assert_not_awaited()
        self.assertEqual(len(activity.created), 1)
        self.assertEqual(activity.created[0]["canonical_class"], "truck")

    def test_started_violation_persists_local_source_context_without_eager_clip(self):
        class PersistenceSink:
            def __init__(self):
                self.created = []

            async def create(self, **payload):
                self.created.append(payload)
                return payload

            async def close(self, **payload):
                return payload

        reader = MagicMock()
        reader.source = r"D:\video_test\sample.mp4"
        reader.get_source_context.return_value = {
            "source_kind": "LOCAL_FILE",
            "source_ref": reader.source,
            "source_position_seconds": 42.5,
            "source_timestamp": None,
        }
        persistence = PersistenceSink()
        emitter = MagicMock()
        emitter.emit_area_event = AsyncMock(return_value=True)
        emitter.emit_alert = AsyncMock(return_value=True)
        entered_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        transition = ViolationTransition(
            action="STARTED", violation_id="local-source", camera_id="BAI-KIEM", track_id=7,
            zone_id="zone-1", zone_name="Benchmark", object_label="Xe tải", status="OPEN",
            entered_at=entered_at,
        )

        with tempfile.TemporaryDirectory() as clips_dir:
            pipeline = AreaPipeline(
                camera_id="BAI-KIEM", detector=MagicMock(), zone_sync=MagicMock(),
                reader=reader, persistence=persistence, emitter=emitter,
                clips_dir=clips_dir, record_violation_clips=True,
            )
            asyncio.run(pipeline._process_transition_once(transition, 0))
            self.assertEqual(list(Path(clips_dir).glob("area_*.mp4")), [])

        created = persistence.created[0]
        self.assertEqual(created["source_kind"], "LOCAL_FILE")
        self.assertEqual(created["source_ref"], reader.source)
        self.assertGreater(created["source_position_seconds"], 40.0)
        self.assertLess(created["source_position_seconds"], 42.5)
        self.assertFalse(hasattr(pipeline, "_clip_tasks"))

    def test_local_activity_fingerprint_is_stable_for_small_replay_jitter(self):
        reader = MagicMock()
        reader.source = r"D:\video_test\sample.mp4"
        pipeline = AreaPipeline(
            camera_id="BAI-KIEM",
            detector=MagicMock(),
            zone_sync=MagicMock(),
            reader=reader,
            persistence=MagicMock(),
            emitter=MagicMock(),
        )

        def fingerprint(position: float, entry_point: tuple[float, float]) -> str:
            reader.get_source_context.return_value = {
                "source_kind": "LOCAL_FILE",
                "source_ref": reader.source,
                "source_position_seconds": position,
                "source_timestamp": None,
            }
            transition = ActivityTransition(
                action="STARTED",
                session_id="session",
                camera_id="BAI-KIEM",
                track_id=7,
                zone_id="zone-1",
                zone_name="Benchmark",
                object_label="Xe nâng",
                canonical_class="forklift",
                policy_result="ALLOWED",
                entered_at=datetime.now(timezone.utc),
                last_seen_at=datetime.now(timezone.utc),
                entry_point=entry_point,
            )
            return pipeline._activity_source_metadata(transition)["event_fingerprint"]

        first = fingerprint(42.1, (320 / 640, 384 / 480))
        replay = fingerprint(42.3, (326 / 640, 390 / 480))
        different_moment = fingerprint(44.1, (320 / 640, 384 / 480))

        self.assertEqual(first, replay)
        self.assertNotEqual(first, different_moment)

    def test_activity_persistence_uses_source_metadata_frozen_at_detection_time(self):
        class ActivityPersistenceSink:
            def __init__(self):
                self.created = []

            async def create(self, **payload):
                self.created.append(payload)
                return {"id": payload["session_id"]}

            async def close(self, **payload):
                return payload

        reader = MagicMock()
        reader.get_source_context.return_value = {
            "source_kind": "LOCAL_FILE",
            "source_ref": "advanced.mp4",
            "source_position_seconds": 99.0,
            "source_timestamp": None,
        }
        activity_persistence = ActivityPersistenceSink()
        pipeline = AreaPipeline(
            camera_id="BAI-KIEM",
            detector=MagicMock(),
            zone_sync=MagicMock(),
            reader=reader,
            persistence=MagicMock(),
            activity_persistence=activity_persistence,
            emitter=MagicMock(),
        )
        transition = ActivityTransition(
            action="STARTED",
            session_id="session-frozen",
            camera_id="BAI-KIEM",
            track_id=7,
            zone_id="zone-1",
            zone_name="Benchmark",
            object_label="Xe nâng",
            canonical_class="forklift",
            policy_result="ALLOWED",
            entered_at=datetime.now(timezone.utc),
            last_seen_at=datetime.now(timezone.utc),
            entry_point=(0.5, 0.8),
            source_metadata={
                "source_kind": "LOCAL_FILE",
                "source_ref": "sample.mp4",
                "source_position_seconds": 42.0,
                "source_timestamp": None,
                "event_fingerprint": "f" * 64,
            },
        )

        asyncio.run(pipeline._process_activity_transition_once(transition, 0))

        self.assertEqual(activity_persistence.created[0]["source_ref"], "sample.mp4")
        self.assertEqual(activity_persistence.created[0]["source_position_seconds"], 42.0)
        self.assertEqual(activity_persistence.created[0]["event_fingerprint"], "f" * 64)

    def test_local_replay_does_not_recalculate_existing_activity(self):
        class ReplayPersistenceSink:
            def __init__(self):
                self.closed = []

            async def create(self, **_payload):
                return {"id": "existing-activity", "was_inserted": False}

            async def close(self, **payload):
                self.closed.append(payload)
                return payload

        activity_persistence = ReplayPersistenceSink()
        pipeline = AreaPipeline(
            camera_id="BAI-KIEM",
            detector=MagicMock(),
            zone_sync=MagicMock(),
            reader=MagicMock(),
            persistence=MagicMock(),
            activity_persistence=activity_persistence,
            emitter=MagicMock(),
        )
        entered_at = datetime.now(timezone.utc) - timedelta(seconds=30)
        started = ActivityTransition(
            action="STARTED",
            session_id="replayed-session",
            camera_id="BAI-KIEM",
            track_id=1,
            zone_id="zone-1",
            zone_name="Benchmark",
            object_label="Xe nâng container",
            canonical_class="reach_stacker",
            policy_result="ALLOWED",
            entered_at=entered_at,
            last_seen_at=entered_at,
            entry_point=(0.5, 0.8),
            source_metadata={
                "source_kind": "LOCAL_FILE",
                "source_ref": "sample.mp4",
                "source_position_seconds": 42.0,
                "source_timestamp": None,
                "event_fingerprint": "a" * 64,
            },
        )
        ended = ActivityTransition(
            **{
                **vars(started),
                "action": "ENDED",
                "last_seen_at": entered_at + timedelta(seconds=30),
                "exited_at": entered_at + timedelta(seconds=30),
                "duration_seconds": 30,
            }
        )

        async def scenario():
            await pipeline._process_activity_transition_once(started, 0)
            await pipeline._process_activity_transition_once(ended, 0)

        asyncio.run(scenario())

        self.assertEqual(activity_persistence.closed, [])
        self.assertNotIn("replayed-session", pipeline._activity_replay_session_ids)

    def test_live_source_context_never_persists_rtsp_credentials(self):
        reader = StreamReader.__new__(StreamReader)
        reader.camera_id = "BAI-KIEM"
        reader.source = "rtsp://secret-user:secret-password@example.test/live"
        reader.is_local_file = False

        context = reader.get_source_context()

        self.assertEqual(context["source_kind"], "LIVE")
        self.assertEqual(context["source_ref"], "BAI-KIEM")
        self.assertNotIn("secret-user", str(context))
        self.assertNotIn("secret-password", str(context))

    def test_publish_result_does_not_wait_for_slow_persistence(self):
        persistence_started = asyncio.Event()
        release_persistence = asyncio.Event()

        class SlowPersistence:
            async def create(self, **payload):
                persistence_started.set()
                await release_persistence.wait()
                return payload

            async def close(self, **payload):
                return payload

            async def update_clip(self, violation_id, filename):
                return {"violationId": violation_id, "filename": filename}

        class EmitterSink:
            def __init__(self):
                self.frames = []

            async def emit_frame(self, **payload):
                self.frames.append(payload)
                return True

            async def emit_area_event(self, payload):
                return True

            async def emit_alert(self, payload):
                return True

        emitter = EmitterSink()
        pipeline = AreaPipeline(
            camera_id="BAI-KIEM",
            detector=MagicMock(),
            zone_sync=MagicMock(),
            persistence=SlowPersistence(),
            emitter=emitter,
            record_violation_clips=False,
        )
        pipeline.set_viewer_active(True)
        entered_at = datetime(2026, 8, 25, tzinfo=timezone.utc)
        item = ViolationTransition(
            action="STARTED", violation_id="slow-start", camera_id="BAI-KIEM", track_id=7,
            zone_id="zone-1", zone_name="Benchmark", object_label="Xe nâng", status="OPEN",
            entered_at=entered_at,
        )
        result = {
            "success": True, "image_base64": "data:image/jpeg;base64,YWJj", "detections": [],
            "fps": 10.0, "zones": [], "source_reset": False, "transitions": [item],
        }

        async def scenario():
            pipeline._event_queue.start()
            await asyncio.wait_for(pipeline.publish_result(result), timeout=0.2)
            self.assertEqual(len(emitter.frames), 1)
            await asyncio.wait_for(persistence_started.wait(), timeout=0.2)
            self.assertFalse(release_persistence.is_set())
            release_persistence.set()
            await pipeline._event_queue.join()
            await pipeline._event_queue.stop()

        asyncio.run(scenario())

    def test_missing_closed_row_is_terminal_and_not_restored(self):
        class MissingClosePersistence:
            def __init__(self):
                self.close_calls = 0

            async def create(self, **payload):
                return payload

            async def close(self, **payload):
                self.close_calls += 1
                return None

            async def update_clip(self, violation_id, filename):
                return {"violationId": violation_id, "filename": filename}

        persistence = MissingClosePersistence()
        emitter = MagicMock()
        emitter.emit_frame = AsyncMock(return_value=True)
        emitter.emit_area_event = AsyncMock(return_value=True)
        emitter.emit_alert = AsyncMock(return_value=True)
        pipeline = AreaPipeline(
            camera_id="BAI-KIEM", detector=MagicMock(), zone_sync=MagicMock(),
            persistence=persistence, emitter=emitter, record_violation_clips=False,
        )
        entered_at = datetime(2026, 8, 25, tzinfo=timezone.utc)
        item = ViolationTransition(
            action="ENDED", violation_id="already-deleted", camera_id="BAI-KIEM", track_id=7,
            zone_id="zone-1", zone_name="Benchmark", object_label="Người", status="CLOSED",
            entered_at=entered_at, exited_at=entered_at + timedelta(seconds=5), duration_seconds=5,
        )
        result = {
            "success": True, "image_base64": "data:image/jpeg;base64,YWJj", "detections": [],
            "fps": 10.0, "zones": [], "source_reset": False, "transitions": [item],
        }

        async def scenario():
            pipeline._event_queue.start()
            await pipeline.publish_result(result)
            await pipeline._event_queue.join()
            await pipeline._event_queue.stop()

        asyncio.run(scenario())
        self.assertEqual(persistence.close_calls, 1)
        self.assertEqual(pipeline.zone_checker.active_violations, {})

    def test_seek_ends_active_timeline_and_clears_pending_state(self):
        class PersistenceSink:
            def __init__(self):
                self.closed = []

            async def create(self, **payload):
                return payload

            async def close(self, **payload):
                self.closed.append(payload)
                return payload

            async def update_clip(self, violation_id, filename):
                return {"violationId": violation_id, "filename": filename}

        persistence = PersistenceSink()
        detector = MagicMock()
        reader = MagicMock()
        reader.request_seek.return_value = {"seekable": True, "positionSeconds": 181.0}
        pipeline = AreaPipeline(
            camera_id="BAI-KIEM", detector=detector, zone_sync=MagicMock(), reader=reader,
            persistence=persistence, emitter=MagicMock(), record_violation_clips=False,
        )
        pipeline.buffer = MagicMock()
        t0 = datetime(2026, 8, 25, 9, 0, tzinfo=timezone.utc)
        pipeline.zone_checker.active_violations[("BAI-KIEM", 7, "zone-1")] = ActiveViolation(
            "seek-active", "BAI-KIEM", 7, "zone-1", "Benchmark", "Xe nâng", t0, t0
        )
        pipeline.zone_checker.pending_violations[("BAI-KIEM", 8, "zone-1")] = PendingViolation(
            "BAI-KIEM", 8, "zone-1", "Benchmark", "Người", t0, t0,
            (0.5, 0.2, 0.55, 0.5), "person"
        )

        async def scenario():
            pipeline._event_queue.start()
            state = await pipeline.request_seek(181.0)
            await pipeline._event_queue.join()
            await pipeline._event_queue.stop()
            return state

        state = asyncio.run(scenario())
        self.assertTrue(state["seekable"])
        self.assertEqual(pipeline.zone_checker.active_violations, {})
        self.assertEqual(pipeline.zone_checker.pending_violations, {})
        self.assertEqual(len(persistence.closed), 1)
        self.assertEqual(persistence.closed[0]["violation_id"], "seek-active")
        reader.request_seek.assert_called_once_with(181.0)
        detector.reset_tracking.assert_called_once_with()
        pipeline.buffer.clear.assert_called_once_with()

    def test_delete_zone_violations_is_scoped_to_camera(self):
        async def scenario():
            executor = AsyncMock()
            executor.execute.return_value = "DELETE 3"
            count = await delete_zone_violations(
                "BAI-KIEM",
                conn_or_pool=executor,
            )
            return executor, count

        executor, count = asyncio.run(scenario())
        self.assertEqual(count, 3)
        query, camera_id = executor.execute.await_args.args
        self.assertIn("WHERE camera_id = $1", query)
        self.assertEqual(camera_id, "BAI-KIEM")

    def test_delete_all_events_invalidates_runtime_generation(self):
        create_started = asyncio.Event()
        release_create = asyncio.Event()
        committed: list[str] = []

        class PersistenceSink:
            async def create(self, **payload):
                create_started.set()
                await release_create.wait()
                committed.append(payload["violation_id"])
                return payload

            async def close(self, **payload):
                return payload

            async def update_clip(self, violation_id, filename):
                return {"violationId": violation_id, "filename": filename}

            async def delete_all(self, camera_id):
                self.deleted_camera_id = camera_id
                return 3

        persistence = PersistenceSink()
        pipeline = AreaPipeline(
            camera_id="BAI-KIEM", detector=MagicMock(), zone_sync=MagicMock(),
            persistence=persistence, emitter=MagicMock(), record_violation_clips=False,
        )
        t0 = datetime(2026, 8, 25, 9, 0, tzinfo=timezone.utc)
        pipeline.zone_checker.active_violations[("BAI-KIEM", 7, "zone-1")] = ActiveViolation(
            "active-before-delete", "BAI-KIEM", 7, "zone-1", "Benchmark", "Xe nâng", t0, t0
        )
        pipeline.zone_checker.pending_violations[("BAI-KIEM", 8, "zone-1")] = PendingViolation(
            "BAI-KIEM", 8, "zone-1", "Benchmark", "Người", t0, t0,
            (0.5, 0.2, 0.55, 0.5), "person"
        )
        queued = ViolationTransition(
            action="STARTED", violation_id="queued-before-delete", camera_id="BAI-KIEM", track_id=9,
            zone_id="zone-1", zone_name="Benchmark", object_label="Người", status="OPEN",
            entered_at=t0,
        )

        async def scenario():
            pipeline._event_queue.start()
            pipeline._event_queue.enqueue(queued, generation=0)
            await asyncio.wait_for(create_started.wait(), timeout=0.2)
            result = await pipeline.delete_all_events()
            await pipeline._event_queue.stop()
            return result

        result = asyncio.run(scenario())
        self.assertEqual(result, {
            "deleted_records": 3,
            "cleared_active": 1,
            "cleared_pending": 1,
        })
        self.assertEqual(pipeline._runtime_generation, 1)
        self.assertEqual(pipeline.zone_checker.active_violations, {})
        self.assertEqual(pipeline.zone_checker.pending_violations, {})
        self.assertEqual(committed, [])
        self.assertEqual(persistence.deleted_camera_id, "BAI-KIEM")

    def test_active_model_requires_path_and_checksum_below_data(self):
        detector = MagicMock()
        pipeline = self._pipeline(detector, ZoneSnapshot())
        backend_data = WORKER_DIR.parent / "data"
        with tempfile.TemporaryDirectory(dir=backend_data) as temp_dir:
            artifact = Path(temp_dir) / "best.pt"
            artifact.write_bytes(b"verified model")
            digest = hashlib.sha256(b"verified model").hexdigest()
            relative = artifact.relative_to(backend_data)
            resolved = pipeline._resolve_active_model({
                "version_key": "custom-v1", "artifact_path": str(relative),
                "artifact_sha256": digest, "label_map": {"Reach stacker": "reach_stacker"},
                "runtime_mode": "UNIFIED",
            })
            rejected = pipeline._resolve_active_model({
                "version_key": "custom-v1", "artifact_path": str(relative),
                "artifact_sha256": "0" * 64, "label_map": {"Reach stacker": "reach_stacker"},
            })
        self.assertIsNotNone(resolved)
        self.assertTrue(Path(str(resolved["artifact_path"])).is_absolute())
        self.assertEqual(resolved["runtime_mode"], "UNIFIED")
        self.assertIsNone(rejected)
        self.assertIsNone(pipeline._resolve_active_model({
            "version_key": "custom-v1", "artifact_path": "../outside.pt",
            "artifact_sha256": "0" * 64, "label_map": {},
        }))

    def test_new_snapshot_with_identical_effective_control_does_not_reconfigure_detector(self):
        detector = MagicMock()
        detector.track.return_value = []
        backend_data = WORKER_DIR.parent / "data"
        with tempfile.TemporaryDirectory(dir=backend_data) as temp_dir:
            artifact = Path(temp_dir) / "best.pt"
            artifact.write_bytes(b"verified model")
            digest = hashlib.sha256(b"verified model").hexdigest()
            relative = artifact.relative_to(backend_data)
            active_model = {
                "version_key": "custom-v1",
                "artifact_path": str(relative),
                "artifact_sha256": digest,
                "label_map": {"Reach stacker": "reach_stacker"},
            }
            first = ZoneSnapshot(
                zones=({"id": "zone-1", "name": "A", "polygon": []},),
                coco_classes=frozenset({"truck"}),
                custom_classes=frozenset({"reach_stacker"}),
                active_model=active_model,
            )
            second = ZoneSnapshot(
                zones=({"id": "zone-2", "name": "B", "polygon": []},),
                coco_classes=frozenset({"truck"}),
                custom_classes=frozenset({"reach_stacker"}),
                active_model={**active_model, "label_map": dict(active_model["label_map"])},
            )
            pipeline = self._pipeline(detector, first)
            pipeline.zone_sync.get_snapshot.side_effect = [first, second]

            self.assertTrue(pipeline.process_single_frame()["success"])
            self.assertTrue(pipeline.process_single_frame()["success"])

            detector.configure_detection_control.assert_called_once_with(
                coco_classes=frozenset({"truck"}),
                custom_classes=frozenset({"reach_stacker"}),
                active_model={
                    "version_key": "custom-v1",
                    "artifact_path": str(artifact.resolve()),
                    "artifact_sha256": digest,
                    "label_map": {"Reach stacker": "reach_stacker"},
                    "runtime_mode": "SUPPLEMENTAL",
                },
            )


class TestBrowserCompatibleClipEncoding(unittest.TestCase):
    def test_circular_buffer_writes_h264_mp4(self):
        buffer = CircularBuffer(max_seconds=3.0, target_fps=5.0)
        for index in range(10):
            buffer.append(np.full((48, 64, 3), index * 20, dtype=np.uint8), 1000.0 + index * 0.2)
        with tempfile.TemporaryDirectory() as directory:
            saved = buffer.save_clip(str(Path(directory) / "area.mp4"), duration_seconds=2.0, end_time=1002.0)
            self.assertTrue(saved)
            self.assertTrue(Path(saved).is_file())
            capture = cv2.VideoCapture(str(saved))
            try:
                self.assertTrue(capture.isOpened())
                fourcc_value = int(capture.get(cv2.CAP_PROP_FOURCC))
                fourcc = "".join(chr((fourcc_value >> (8 * index)) & 0xFF) for index in range(4))
                self.assertEqual(fourcc.lower(), "h264")
                self.assertGreater(capture.get(cv2.CAP_PROP_FRAME_COUNT), 0)
            finally:
                capture.release()


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
            try:
                self.assertIsNotNone(reader.cap)
                reader.cap.set(cv2.CAP_PROP_POS_FRAMES, 1)
                before = reader.cap.get(cv2.CAP_PROP_POS_FRAMES)

                preview = reader.preview_frame(0.2)

                self.assertIsNotNone(preview)
                self.assertEqual(preview.shape, (24, 32, 3))
                self.assertEqual(reader.cap.get(cv2.CAP_PROP_POS_FRAMES), before)
            finally:
                reader.release()

    def test_local_video_rewind_sets_source_reset_signal(self):
        reader = StreamReader(source=None, camera_id="BAI-KIEM", resolution=(64, 48))
        capture = MagicMock()
        capture.isOpened.return_value = True
        capture.read.side_effect = [(False, None), (True, np.zeros((48, 64, 3), dtype=np.uint8))]
        reader.cap = capture
        reader.is_image_fallback = False
        reader.is_synthetic = False
        success, _ = reader.read_frame()
        self.assertTrue(success)
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
        # Source frames are 50 FPS while target cadence is 10 FPS. At the
        # observed 0.1-second interval the reader correctly drops two frames
        # after accounting for the decoded frame itself.
        self.assertEqual(capture.grab.call_count, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
