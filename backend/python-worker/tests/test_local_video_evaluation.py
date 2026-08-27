from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.evaluate_local_video_model import _deduplicate_predictions, _predict, choose_threshold
from evaluation.evaluate_area_video import runtime_environment, temporal_continuity
from stream.native_video_frames import NativeVideoFrameLoader


def _point(threshold: float, precision: float, recall: float) -> dict:
    return {
        "threshold": threshold,
        "tp": 1,
        "fp": 1,
        "fn": 1,
        "precision": {"value": precision, "reason": None},
        "recall": {"value": recall, "reason": None},
    }


class TestLocalVideoEvaluation(unittest.TestCase):
    def test_ffmpeg_native_loader_fast_seeks_and_caches_reviewed_frame(self) -> None:
        image = np.full((8, 12, 3), 127, dtype=np.uint8)
        ok, encoded = cv2.imencode(".png", image)
        self.assertTrue(ok)
        manifest = {
            "sources": [{"sourceId": "camera-a", "sourceFile": "camera.asf"}],
        }
        frame = {"frameId": "camera-a-001", "sourceId": "camera-a", "timestampMs": 1234}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "camera.asf").write_bytes(b"video")
            ffmpeg = root / "ffmpeg.exe"
            ffmpeg.write_bytes(b"executable")
            loader = NativeVideoFrameLoader(manifest, root, ffmpeg_path=ffmpeg)
            result = SimpleNamespace(returncode=0, stdout=encoded.tobytes(), stderr=b"")
            with patch("stream.native_video_frames.subprocess.run", return_value=result) as run:
                first = loader(frame)
                second = loader(frame)
            loader.close()

        self.assertEqual(run.call_count, 1)
        self.assertTrue(np.array_equal(first, image))
        self.assertTrue(np.array_equal(second, image))

    def test_full_frame_and_tile_predictions_keep_highest_overlapping_box(self) -> None:
        kept = _deduplicate_predictions([
            {"bbox": [0.1, 0.1, 0.4, 0.4], "confidence": 0.40},
            {"bbox": [0.11, 0.11, 0.41, 0.41], "confidence": 0.85},
            {"bbox": [0.7, 0.7, 0.8, 0.8], "confidence": 0.50},
        ])
        self.assertEqual([item["confidence"] for item in kept], [0.85, 0.50])

    def test_prediction_source_is_bounded_to_avoid_materializing_all_frames(self) -> None:
        calls: list[int] = []

        class FakeModel:
            def predict(self, **kwargs):
                sources = kwargs["source"]
                calls.append(len(sources))
                return [
                    SimpleNamespace(orig_shape=(720, 1280), boxes=None, speed={"inference": 1.0})
                    for _ in sources
                ]

        frames = [
            {"frameId": f"frame-{index}", "imagePath": f"images/frame-{index}.jpg"}
            for index in range(41)
        ]
        with tempfile.TemporaryDirectory() as directory:
            with patch("evaluation.evaluate_local_video_model.torch.cuda.is_available", return_value=False):
                predictions, performance = _predict(
                    FakeModel(), Path(directory), frames,
                    imgsz=768, device="cpu", batch=4, confidence=0.001,
                )

        self.assertEqual(calls, [16, 16, 9])
        self.assertEqual(len(predictions), 41)
        self.assertEqual(performance["frameCount"], 41)

    def test_prefers_recall_among_points_meeting_precision_target(self) -> None:
        selected = choose_threshold([
            _point(0.20, 0.85, 0.90),
            _point(0.30, 0.91, 0.70),
            _point(0.40, 0.95, 0.60),
        ])
        self.assertEqual(selected["threshold"], 0.30)
        self.assertTrue(selected["metPrecisionTarget"])

    def test_falls_back_to_best_f1_without_claiming_target(self) -> None:
        selected = choose_threshold([
            _point(0.20, 0.70, 0.80),
            _point(0.30, 0.85, 0.60),
        ])
        self.assertEqual(selected["threshold"], 0.20)
        self.assertFalse(selected["metPrecisionTarget"])

    def test_temporal_continuity_includes_edges_and_internal_gaps(self) -> None:
        report = temporal_continuity(
            [0, 2000, 4000],
            [100, 300, 900, 3800],
            maximum_label_gap_ms=2500,
        )
        self.assertEqual(report["maxGapSeconds"], 2.9)
        self.assertEqual(len(report["segments"]), 1)

    def test_area_runtime_can_use_smaller_custom_size_than_base_size(self) -> None:
        environment = runtime_environment(
            imgsz=960,
            custom_imgsz=768,
            initiation=0.42,
            continuation=0.28,
            custom_interval=2,
        )
        self.assertEqual(environment["AREA_INFERENCE_SIZE"], "960")
        self.assertEqual(environment["AREA_CUSTOM_INFERENCE_SIZE"], "768")

    def test_area_runtime_defaults_custom_size_to_base_size(self) -> None:
        environment = runtime_environment(
            imgsz=896,
            custom_imgsz=None,
            initiation=0.42,
            continuation=0.28,
            custom_interval=2,
        )
        self.assertEqual(environment["AREA_CUSTOM_INFERENCE_SIZE"], "896")


if __name__ == "__main__":
    unittest.main(verbosity=2)
