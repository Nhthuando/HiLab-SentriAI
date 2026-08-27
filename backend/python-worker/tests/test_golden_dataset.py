from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.golden_dataset import (
    GoldenManifestError,
    difference_hash,
    evaluatable_records,
    extract_golden_frames,
    hash_distance,
    load_manifest,
    scan_contact_hard_cases,
    validate_manifest,
)


class TestGoldenDataset(unittest.TestCase):
    def _video(self, directory: Path) -> Path:
        path = directory / "source.avi"
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (96, 64))
        self.assertTrue(writer.isOpened())
        for index in range(30):
            frame = np.full((64, 96, 3), 20 + index * 5, dtype=np.uint8)
            cv2.rectangle(frame, (index * 2 % 70, 15), (index * 2 % 70 + 20, 45), (240, 80, 30), -1)
            writer.write(frame)
        writer.release()
        return path

    def test_manifest_status_gate_and_portability(self) -> None:
        record = {
            "frameId": "bai-kiem-000120000", "sourceId": "BAI-KIEM-20260820",
            "timestampMs": 120000, "imagePath": "images/bai-kiem-000120000.jpg",
            "sha256": "a" * 64, "perceptualHash": "b" * 16,
            "annotationStatus": "PENDING", "labelsPath": None, "tags": ["interval"],
            "timeBlock": "BAI-KIEM-20260820-tb001", "split": "validation",
        }
        manifest = {
            "schemaVersion": 1, "datasetId": "BAI-KIEM-GOLDEN-V1",
            "source": {"sourceId": "BAI-KIEM-20260820", "sourceFile": "camera.mp4", "durationMs": 600000},
            "extraction": {"timeBlockSeconds": 120},
            "frames": [record],
        }
        self.assertEqual(validate_manifest(manifest), manifest)
        self.assertEqual(evaluatable_records(manifest), [])
        record["annotationStatus"] = "NEGATIVE"
        self.assertEqual(len(evaluatable_records(manifest)), 1)
        record["annotationStatus"] = "ANNOTATED"
        record["labelsPath"] = "labels/bai-kiem-000120000.txt"
        self.assertEqual(len(evaluatable_records(manifest)), 1)
        record["imagePath"] = "D:/private/camera.jpg"
        with self.assertRaises(GoldenManifestError):
            validate_manifest(manifest)
        record["imagePath"] = "images/bai-kiem-000120000.jpg"
        record["timeBlock"] = "BAI-KIEM-20260820-tb004"
        record["split"] = "test"
        with self.assertRaises(GoldenManifestError):
            validate_manifest(manifest)

    def test_sequential_extraction_writes_only_pending_relative_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self._video(root)
            output = root / "golden"
            manifest, summary = extract_golden_frames(
                source, output, source_id="BAI-KIEM-TEST", dataset_id="BAI-KIEM-GOLDEN-V1",
                interval_seconds=1.0, hard_case_timestamps_ms=[1500], dhash_distance_threshold=0,
            )
            loaded = load_manifest(output / "golden-manifest.json")
            self.assertEqual(loaded, manifest)
            self.assertGreaterEqual(summary.accepted, 3)
            self.assertTrue(all(record["annotationStatus"] == "PENDING" for record in manifest["frames"]))
            self.assertTrue(all(record["labelsPath"] is None for record in manifest["frames"]))
            self.assertTrue(all(not Path(record["imagePath"]).is_absolute() for record in manifest["frames"]))
            self.assertTrue(any("hard-case" in record["tags"] for record in manifest["frames"]))
            self.assertTrue((output / "labels").is_dir())
            self.assertTrue(all(record["timeBlock"] and record["split"] in {"calibration", "validation", "test"} for record in manifest["frames"]))
            block_splits = {(record["timeBlock"], record["split"]) for record in manifest["frames"]}
            self.assertEqual(len({block for block, _split in block_splits}), len(block_splits))
            self.assertNotIn(str(root), json.dumps(manifest))
            self.assertEqual(evaluatable_records(manifest), [])

    def test_dhash_collision_does_not_erase_spaced_small_object_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "small-change.avi"
            writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (160, 96))
            self.assertTrue(writer.isOpened())
            for index in range(31):
                frame = np.full((96, 160, 3), 80, dtype=np.uint8)
                if 9 <= index <= 11:
                    cv2.rectangle(frame, (79, 47), (81, 49), (255, 255, 255), -1)
                if 19 <= index <= 21:
                    cv2.rectangle(frame, (119, 67), (121, 69), (255, 255, 255), -1)
                writer.write(frame)
            writer.release()
            manifest, summary = extract_golden_frames(
                path, root / "golden", source_id="BAI-KIEM-SMALL", dataset_id="BAI-KIEM-SMALL-V1",
                interval_seconds=1.0, dhash_distance_threshold=4, dhash_dedupe_window_seconds=0.2,
            )
        self.assertGreaterEqual(summary.accepted, 3)
        self.assertGreaterEqual(len({record["timestampMs"] // 1000 for record in manifest["frames"]}), 3)

    def test_hash_and_contact_scan_are_deterministic(self) -> None:
        image = np.tile(np.arange(90, dtype=np.uint8), (80, 1))
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        digest = difference_hash(image)
        self.assertRegex(digest, r"^[0-9a-f]{16}$")
        self.assertEqual(hash_distance(digest, digest), 0)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self._video(root)
            first = scan_contact_hard_cases(source, sample_interval_seconds=0.5, maximum_results=4)
            second = scan_contact_hard_cases(source, sample_interval_seconds=0.5, maximum_results=4)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 4)
        self.assertTrue(all("selectionReason" in item for item in first))


if __name__ == "__main__":
    unittest.main(verbosity=2)
