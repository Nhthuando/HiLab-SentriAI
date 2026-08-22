"""Focused immutable-snapshot tests for the manual training dataset exporter."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from training.dataset_exporter import materialize
from training.runner import _quality_gate


class TestTrainingDatasetExporter(unittest.TestCase):
    def _manifest(self, root: Path, samples: list[dict]) -> Path:
        snapshot = root / "snapshot"
        snapshot.mkdir(exist_ok=True)
        (snapshot / "manifest.json").write_text(json.dumps({"schemaVersion": 2, "samples": samples}), encoding="utf-8")
        return snapshot / "manifest.json"

    def test_materializes_normalized_image_annotation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media_dir = root / "snapshot" / "media"
            media_dir.mkdir(parents=True)
            image = np.full((50, 100, 3), 120, dtype=np.uint8)
            self.assertTrue(cv2.imwrite(str(media_dir / "image.jpg"), image))
            manifest = self._manifest(root, [{
                "sampleId": "sample-image", "label": "Xe nâng", "baseClass": "forklift", "sourceId": "source-image",
                "mediaKind": "IMAGE", "frameTimestampMs": None, "bbox": {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4},
                "mediaPath": "media/image.jpg", "mediaSha256": "a" * 64, "split": "train",
            }])
            exported = materialize(manifest, root / "materialized")
            self.assertTrue((exported / "images" / "train" / "sample-image.jpg").is_file())
            self.assertEqual((exported / "labels" / "train" / "sample-image.txt").read_text(encoding="utf-8"), "0 0.250000 0.400000 0.300000 0.400000\n")
            self.assertIn(f"path: {exported.resolve().as_posix()}", (exported / "data.yaml").read_text(encoding="utf-8"))

    def test_materializes_selected_video_frame(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media_dir = root / "snapshot" / "media"
            media_dir.mkdir(parents=True)
            video_path = media_dir / "video.mp4"
            writer = cv2.VideoWriter(str(video_path), cv2.VideoWriter_fourcc(*"mp4v"), 5, (64, 48))
            self.assertTrue(writer.isOpened())
            writer.write(np.zeros((48, 64, 3), dtype=np.uint8))
            writer.write(np.full((48, 64, 3), 255, dtype=np.uint8))
            writer.release()
            manifest = self._manifest(root, [{
                "sampleId": "sample-video", "label": "Xe nâng", "baseClass": "forklift", "sourceId": "source-video",
                "mediaKind": "VIDEO", "frameTimestampMs": 200, "bbox": {"x": 0.2, "y": 0.2, "w": 0.4, "h": 0.4},
                "mediaPath": "media/video.mp4", "mediaSha256": "b" * 64, "split": "val",
            }])
            exported = materialize(manifest, root / "materialized")
            frame = cv2.imread(str(exported / "images" / "val" / "sample-video.jpg"))
            self.assertIsNotNone(frame)
            self.assertGreater(float(frame.mean()), 150.0)

    def test_preserves_multiple_boxes_for_one_source_image(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media_dir = root / "snapshot" / "media"
            media_dir.mkdir(parents=True)
            self.assertTrue(cv2.imwrite(str(media_dir / "image.jpg"), np.full((50, 100, 3), 120, dtype=np.uint8)))
            manifest = self._manifest(root, [
                {
                    "sampleId": "box-a", "label": "Xe nâng", "baseClass": "reach stacker", "sourceId": "source-image",
                    "mediaKind": "IMAGE", "frameTimestampMs": None, "bbox": {"x": 0.1, "y": 0.2, "w": 0.2, "h": 0.2},
                    "mediaPath": "media/image.jpg", "mediaSha256": "d" * 64, "split": "train",
                },
                {
                    "sampleId": "box-b", "label": "Xe nâng", "baseClass": "reach stacker", "sourceId": "source-image",
                    "mediaKind": "IMAGE", "frameTimestampMs": None, "bbox": {"x": 0.5, "y": 0.3, "w": 0.2, "h": 0.4},
                    "mediaPath": "media/image.jpg", "mediaSha256": "d" * 64, "split": "train",
                },
            ])
            exported = materialize(manifest, root / "materialized")
            label_files = list((exported / "labels" / "train").glob("*.txt"))
            self.assertEqual(len(label_files), 1)
            self.assertEqual(len(label_files[0].read_text(encoding="utf-8").splitlines()), 2)

    def test_rejects_snapshot_path_outside_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self._manifest(root, [{
                "sampleId": "unsafe", "label": "Xe nâng", "baseClass": "forklift", "sourceId": "source",
                "mediaKind": "IMAGE", "frameTimestampMs": None, "bbox": {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2},
                "mediaPath": "../outside.jpg", "mediaSha256": "c" * 64, "split": "train",
            }])
            with self.assertRaises(ValueError):
                materialize(manifest, root / "materialized")

    def test_yard_profile_requires_each_class_to_pass_evaluation(self) -> None:
        metrics = {
            "map50": 0.8, "precision": 0.8, "recall": 0.8,
            "perClass": {"Container": {"map": 0.7}, "Xe tải": {"map": 0.7}, "Xe nâng": {"map": 0.3}},
        }
        accepted, failures = _quality_gate(metrics, "YARD_VEHICLE_V1")
        self.assertFalse(accepted)
        self.assertIn("Xe nâng mAP below required threshold", failures)


if __name__ == "__main__":
    unittest.main(verbosity=2)
