"""Regression checks for recoverable custom-model training failures."""
from __future__ import annotations

import json
import tempfile
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from training.local_video_dataset import CLASS_NAMES
from training.runner import _is_system_memory_error, _quality_gate, _training_dataset_contract


class TrainingRunnerTests(unittest.TestCase):
    def test_marks_opencv_host_memory_failure_as_recoverable(self) -> None:
        error = RuntimeError(
            "cv2.error: OpenCV error: (-4:Insufficient memory) Failed to allocate bytes in function"
        )

        self.assertTrue(_is_system_memory_error(error))

    def test_does_not_hide_unrelated_training_failure(self) -> None:
        self.assertFalse(_is_system_memory_error(RuntimeError("dataset yaml is invalid")))

    def test_reviewed_local_video_contract_is_exact_unified_and_source_provenanced(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = []
            for split, class_id in (("train", 5), ("val", 5), ("test", None)):
                (root / "images" / split).mkdir(parents=True, exist_ok=True)
                (root / "labels" / split).mkdir(parents=True, exist_ok=True)
                image_path = root / "images" / split / f"{split}.jpg"
                label_path = root / "labels" / split / f"{split}.txt"
                image_path.write_bytes(b"image")
                label_path.write_text(
                    "" if class_id is None else f"{class_id} 0.5 0.5 0.2 0.2\n",
                    encoding="utf-8",
                )
                frames.append({
                    "frameId": split,
                    "sourceId": f"source-{split}",
                    "split": split,
                    "imagePath": f"images/{split}/{split}.jpg",
                    "labelsPath": f"labels/{split}/{split}.txt",
                })
            (root / "data.yaml").write_text("path: .\ntrain: train.txt\n", encoding="utf-8")
            manifest = {
                "schemaVersion": 3,
                "datasetKind": "LOCAL_VIDEO_REVIEWED",
                "reviewStatus": "REVIEWED",
                "contentHash": "a" * 64,
                "classes": list(CLASS_NAMES),
                "frames": frames,
            }
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            contract = _training_dataset_contract(manifest_path, root / "output")

            self.assertEqual(contract["runtimeMode"], "UNIFIED")
            self.assertEqual(contract["labels"], list(CLASS_NAMES))
            self.assertEqual(contract["labelMap"], {name: name for name in CLASS_NAMES})
            self.assertEqual(contract["counts"], {"train": 1, "val": 1, "test": 1})
            self.assertEqual(contract["validationClasses"], ["reach_stacker"])
            self.assertEqual(contract["sourceSplits"]["source-test"], ["test"])

            manifest["reviewStatus"] = "PENDING_REVIEW"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "REVIEWED"):
                _training_dataset_contract(manifest_path, root / "output")

    def test_unified_quality_gate_rejects_undefined_or_sub_090_reach_metrics(self) -> None:
        base = {
            "map50": 0.95,
            "precision": 0.95,
            "recall": 0.95,
            "perClass": {"reach_stacker": {"map": 0.9, "precision": None, "recall": 0.89}},
        }
        accepted, failures = _quality_gate(base, ["reach_stacker"], "UNIFIED")
        self.assertFalse(accepted)
        self.assertIn("reach_stacker precision is undefined", failures)
        self.assertIn("reach_stacker recall below 0.90", failures)


if __name__ == "__main__":
    unittest.main()
