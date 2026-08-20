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
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
