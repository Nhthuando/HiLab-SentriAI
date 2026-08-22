"""Safety and normalization checks for a local external YOLO archive."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from training.external_yolo_importer import import_external_yolo_archive


class TestExternalYoloImporter(unittest.TestCase):
    @staticmethod
    def _image_bytes(value: int) -> bytes:
        ok, encoded = cv2.imencode(".jpg", np.full((32, 32, 3), value, dtype=np.uint8))
        if not ok:
            raise RuntimeError("Could not encode fixture image")
        return encoded.tobytes()

    def _archive(self, root: Path) -> Path:
        archive_path = root / "reach-stacker.zip"
        polygon = "0 0.2 0.2 0.8 0.2 0.8 0.6 0.2 0.6\n"
        bbox = "0 0.5 0.5 0.4 0.6\n"
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("data.yaml", "names: ['stacker']\n")
            for split, label, value in (("train", polygon, 120), ("valid", bbox, 140), ("test", bbox, 160)):
                archive.writestr(f"{split}/images/example.jpg", self._image_bytes(value))
                archive.writestr(f"{split}/labels/example.txt", label)
        return archive_path

    def test_imports_segmentation_as_detection_bbox_and_preserves_splits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = import_external_yolo_archive(self._archive(root), root / "datasets")
            self.assertEqual(result["sampleCount"], 3)
            self.assertEqual(result["sourceCount"], 3)
            self.assertEqual(result["splits"], {"train": 1, "val": 1, "test": 1})
            manifest = json.loads(Path(result["manifestPath"]).read_text(encoding="utf-8"))
            train_sample = next(sample for sample in manifest["samples"] if sample["split"] == "train")
            self.assertEqual(train_sample["label"], "Xe nâng")
            self.assertEqual(train_sample["baseClass"], "reach stacker")
            self.assertEqual(train_sample["bbox"], {"x": 0.2, "y": 0.2, "w": 0.6, "h": 0.4})

    def test_rejects_archive_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path = root / "unsafe.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("../outside.jpg", b"not-an-image")
            with self.assertRaisesRegex(ValueError, "Unsafe archive entry"):
                import_external_yolo_archive(archive_path, root / "datasets")

    def test_rejects_conflicting_duplicate_entry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path = root / "duplicate.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("data.yaml", "names: ['stacker']\n")
                archive.writestr("data.yaml", "names: ['other']\n")
            with self.assertRaisesRegex(ValueError, "Conflicting duplicate"):
                import_external_yolo_archive(archive_path, root / "datasets")


if __name__ == "__main__":
    unittest.main(verbosity=2)
