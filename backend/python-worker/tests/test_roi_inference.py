from __future__ import annotations

import os
import unittest
from functools import partial
from unittest.mock import MagicMock, patch

import numpy as np

from detection.roi_inference import (
    RoiConfigurationError,
    RoiScheduler,
    RoiSpec,
    TileWindow,
    build_tiles,
    class_aware_deduplicate,
    remap_detection,
)
from detection.policy import DetectionPolicy
from detection.tracked_detector import TrackedYoloDetector
from ultralytics.trackers.track import on_predict_postprocess_end, on_predict_start


class TestRoiGeometry(unittest.TestCase):
    def test_roi_spec_rejects_invalid_geometry_and_detector_scope(self) -> None:
        invalid_values = (
            {"name": "short", "polygon": ((0.0, 0.0), (1.0, 1.0)), "detectors": frozenset({"base"})},
            {"name": "outside", "polygon": ((-0.1, 0.0), (1.0, 0.0), (1.0, 1.0)), "detectors": frozenset({"base"})},
            {"name": "scope", "polygon": ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0)), "detectors": frozenset({"world"})},
        )
        for value in invalid_values:
            with self.subTest(value=value), self.assertRaises(RoiConfigurationError):
                RoiSpec(**value)

    def test_build_tiles_is_clipped_deterministic_and_bounded(self) -> None:
        roi = RoiSpec(
            name="far-yard",
            polygon=((0.5, 0.0), (1.0, 0.0), (1.0, 1.0), (0.5, 1.0)),
            detectors=frozenset({"base", "custom"}),
        )
        tiles = build_tiles(1920, 1080, (roi,), tile_size=640, overlap=0.20, max_tiles=8)
        self.assertEqual(
            tiles,
            [
                TileWindow("far-yard", 960, 0, 1600, 640),
                TileWindow("far-yard", 1280, 0, 1920, 640),
                TileWindow("far-yard", 960, 440, 1600, 1080),
                TileWindow("far-yard", 1280, 440, 1920, 1080),
            ],
        )
        self.assertEqual(len(build_tiles(1920, 1080, (roi,), max_tiles=2)), 2)

        full_frame = RoiSpec(
            name="small-frame",
            polygon=((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)),
            detectors=frozenset({"base"}),
        )
        clipped = build_tiles(800, 500, (full_frame,), tile_size=640, overlap=0.20, max_tiles=8)
        self.assertEqual(clipped, [
            TileWindow("small-frame", 0, 0, 640, 500),
            TileWindow("small-frame", 160, 0, 800, 500),
        ])

    def test_remap_detection_clips_and_recomputes_normalized_bbox(self) -> None:
        tile = TileWindow("far", 100, 50, 500, 350)
        remapped = remap_detection(
            {"bbox": [-10, 20, 450, 400], "canonicalClass": "truck", "confidence": 0.8},
            tile,
            frame_width=640,
            frame_height=480,
        )
        self.assertEqual(remapped["bbox"], [100, 70, 500, 350])
        self.assertEqual(remapped["normalized_bbox"], [0.1562, 0.1458, 0.7812, 0.7292])
        self.assertEqual(remapped["roiName"], "far")


class TestRoiScheduler(unittest.TestCase):
    def setUp(self) -> None:
        self.roi = RoiSpec(
            name="far",
            polygon=((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)),
            detectors=frozenset({"base"}),
        )
        self.frame = np.zeros((480, 640, 3), dtype=np.uint8)

    def test_every_third_frame_and_disabled_state_make_expected_calls(self) -> None:
        calls: list[tuple[int, int]] = []

        def callback(tile: np.ndarray):
            calls.append(tile.shape[:2])
            return [{"bbox": [10, 20, 30, 40], "canonicalClass": "truck", "confidence": 0.7}]

        disabled = RoiScheduler(enabled=False, rois=(self.roi,))
        self.assertEqual(disabled.infer(self.frame, frame_index=3, callbacks={"base": callback}), [])
        self.assertEqual(calls, [])

        scheduler = RoiScheduler(enabled=True, rois=(self.roi,), interval=3)
        self.assertEqual(scheduler.infer(self.frame, frame_index=1, callbacks={"base": callback}), [])
        self.assertEqual(scheduler.infer(self.frame, frame_index=2, callbacks={"base": callback}), [])
        result = scheduler.infer(self.frame, frame_index=3, callbacks={"base": callback})
        self.assertEqual(len(result), 1)
        self.assertEqual(calls, [(480, 640)])
        self.assertEqual(result[0]["roiDetector"], "base")
        self.assertEqual(result[0]["roiInferenceIndex"], 1)

    def test_environment_defaults_are_off_and_configuration_is_strict(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            scheduler = RoiScheduler.from_environment()
        self.assertFalse(scheduler.enabled)
        self.assertEqual(scheduler.interval, 3)
        self.assertEqual(scheduler.tile_size, 640)
        self.assertEqual(scheduler.overlap, 0.20)
        self.assertEqual(scheduler.max_tiles, 8)

        with patch.dict(os.environ, {"AREA_ROI_ENABLED": "true", "AREA_ROI_CONFIG_JSON": "not-json"}, clear=True):
            with self.assertRaises(RoiConfigurationError):
                RoiScheduler.from_environment()

    def test_class_aware_dedup_keeps_semantics_and_custom_supersession_is_explicit(self) -> None:
        detections = [
            {"bbox": [0, 0, 100, 100], "canonicalClass": "truck", "confidence": 0.9, "trackId": 7},
            {"bbox": [2, 2, 98, 98], "canonicalClass": "truck", "confidence": 0.95, "trackId": None},
            {"bbox": [2, 2, 98, 98], "canonicalClass": "reach_stacker", "confidence": 0.8, "customConfirmed": False},
        ]
        kept = class_aware_deduplicate(detections)
        self.assertEqual([item["canonicalClass"] for item in kept], ["truck", "reach_stacker"])
        self.assertEqual(kept[0]["trackId"], 7)

        detections[-1]["customConfirmed"] = True
        promoted = class_aware_deduplicate(detections)
        self.assertEqual([item["canonicalClass"] for item in promoted], ["reach_stacker"])


class TestTrackedDetectorRoiIntegration(unittest.TestCase):
    @staticmethod
    def _detector(scheduler: RoiScheduler) -> TrackedYoloDetector:
        detector = TrackedYoloDetector.__new__(TrackedYoloDetector)
        detector._roi_scheduler = scheduler
        detector._policy = DetectionPolicy()
        detector._enabled_coco_classes = frozenset({"truck"})
        detector._enabled_custom_classes = frozenset()
        detector._base_frame_index = 3
        detector._base_track_state = {}
        detector._roi_base_candidates = {}
        detector._custom_candidates = {}
        detector._custom_windows = {}
        detector._custom_frame_index = 0
        detector._roi_opportunity_index = 0
        detector._custom_match_overlap = 0.20
        detector._next_synthetic_track_id = -1
        detector._custom_model = None
        detector.model = object()
        return detector

    def test_disabled_detector_hook_does_not_call_an_engine(self) -> None:
        roi = RoiSpec(
            "far", ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)), frozenset({"base"})
        )
        detector = self._detector(RoiScheduler(enabled=False, rois=(roi,)))
        detector._collect_roi_base_detections = MagicMock(return_value=[])
        result = detector._collect_roi_candidates(np.zeros((480, 640, 3), dtype=np.uint8))
        self.assertEqual(result, [])
        detector._collect_roi_base_detections.assert_not_called()
        baseline = [{"bbox": [1, 1, 20, 20], "canonicalClass": "truck", "confidence": 0.8}]
        self.assertIs(detector._merge_roi_base_candidates(baseline, []), baseline)

    def test_tile_prediction_does_not_advance_full_frame_tracker_callbacks(self) -> None:
        class FakeModel:
            def __init__(self) -> None:
                self.callbacks = {
                    "on_predict_start": [partial(on_predict_start, persist=True)],
                    "on_predict_postprocess_end": [partial(on_predict_postprocess_end, persist=True)],
                }
                self.callback_counts: tuple[int, int] | None = None

            def __call__(self, _frame: np.ndarray, **_kwargs: object):
                self.callback_counts = (
                    len(self.callbacks["on_predict_start"]),
                    len(self.callbacks["on_predict_postprocess_end"]),
                )
                return []

        model = FakeModel()
        original = {event: callbacks for event, callbacks in model.callbacks.items()}
        result = TrackedYoloDetector._predict_without_tracking_callbacks(
            model, np.zeros((20, 20, 3), dtype=np.uint8), suppress=True
        )
        self.assertEqual(result, [])
        self.assertEqual(model.callback_counts, (0, 0))
        self.assertIs(model.callbacks["on_predict_start"], original["on_predict_start"])
        self.assertIs(model.callbacks["on_predict_postprocess_end"], original["on_predict_postprocess_end"])

    def test_roi_only_base_candidate_gets_stable_identity_and_low_confidence_is_rejected(self) -> None:
        detector = self._detector(RoiScheduler())
        candidate = {
            "bbox": [100, 100, 180, 180],
            "canonicalClass": "truck",
            "class": "truck",
            "confidence": 0.8,
            "roiInferenceIndex": 1,
            "roiDetector": "base",
        }
        first = detector._merge_roi_base_candidates([], [candidate])
        second = detector._merge_roi_base_candidates([], [{**candidate, "bbox": [102, 101, 182, 181], "roiInferenceIndex": 2}])
        self.assertEqual(first[0]["trackId"], second[0]["trackId"])
        self.assertTrue(first[0]["canInitiate"])

        continued = detector._merge_roi_base_candidates(
            [], [{**candidate, "confidence": 0.20, "bbox": [103, 102, 183, 182], "roiInferenceIndex": 3}]
        )
        self.assertEqual(continued[0]["trackId"], first[0]["trackId"])
        self.assertFalse(continued[0]["canInitiate"])
        self.assertTrue(continued[0]["canContinue"])

        weak = detector._merge_roi_base_candidates([], [{**candidate, "confidence": 0.20, "bbox": [300, 300, 360, 360]}])
        self.assertEqual(weak, [])

    def test_empty_roi_opportunity_expires_base_identity_before_low_confidence_reuse(self) -> None:
        detector = self._detector(RoiScheduler())
        candidate = {
            "bbox": [100, 100, 180, 180],
            "canonicalClass": "truck",
            "class": "truck",
            "confidence": 0.8,
            "roiInferenceIndex": 1,
            "roiDetector": "base",
        }
        opened = detector._merge_roi_base_candidates([], [candidate])
        self.assertEqual(len(opened), 1)

        detector._roi_opportunity_index = 100
        self.assertEqual(detector._merge_roi_base_candidates([], []), [])
        self.assertEqual(detector._roi_base_candidates, {})

        ancient_low_confidence = detector._merge_roi_base_candidates(
            [], [{**candidate, "confidence": 0.20, "roiInferenceIndex": 100}]
        )
        self.assertEqual(ancient_low_confidence, [])

    def test_roi_custom_confirmation_uses_two_of_three_roi_opportunities(self) -> None:
        detector = self._detector(RoiScheduler())
        detector._enabled_custom_classes = frozenset({"reach_stacker"})
        detector._custom_model = object()
        detector._custom_version_key = "custom-v1"
        detector._custom_interval = 100
        candidate = {
            "bbox": [100, 100, 180, 180],
            "canonicalClass": "reach_stacker",
            "class": "reach_stacker",
            "label": "Reach stacker",
            "confidence": 0.8,
            "roiInferenceIndex": 1,
            "roiDetector": "custom",
        }
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        first = detector._apply_custom_augmentation(frame, [], 640, 480, [candidate])
        second = detector._apply_custom_augmentation(
            frame, [], 640, 480, [{**candidate, "roiInferenceIndex": 2}]
        )
        self.assertEqual(first, [])
        self.assertEqual(len(second), 1)
        self.assertTrue(second[0]["customConfirmed"])
        self.assertTrue(second[0]["canInitiate"])

    def test_roi_custom_evidence_survives_more_than_ten_full_frame_custom_opportunities(self) -> None:
        detector = self._detector(RoiScheduler())
        detector._enabled_custom_classes = frozenset({"reach_stacker"})
        detector._custom_model = object()
        detector._custom_version_key = "custom-v1"
        detector._custom_interval = 1
        detector._collect_custom_detections = MagicMock(return_value=[])
        candidate = {
            "bbox": [100, 100, 180, 180],
            "canonicalClass": "reach_stacker",
            "class": "reach_stacker",
            "label": "Reach stacker",
            "confidence": 0.8,
            "roiInferenceIndex": 1,
            "roiDetector": "custom",
        }
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        self.assertEqual(detector._apply_custom_augmentation(frame, [], 640, 480, [candidate]), [])

        for _ in range(11):
            detector._base_frame_index += 1
            self.assertEqual(detector._apply_custom_augmentation(frame, [], 640, 480), [])

        confirmed = detector._apply_custom_augmentation(
            frame, [], 640, 480, [{**candidate, "roiInferenceIndex": 2}]
        )
        self.assertEqual(len(confirmed), 1)
        self.assertTrue(confirmed[0]["customConfirmed"])


if __name__ == "__main__":
    unittest.main()
