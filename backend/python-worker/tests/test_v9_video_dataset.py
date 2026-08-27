from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from training.v9_video_dataset import (
    CandidateFrame,
    SourceVideo,
    V9DatasetError,
    assign_source_splits,
    audit_review_package,
    select_diverse_frames,
)


class V9VideoDatasetTests(unittest.TestCase):
    def _sources(self) -> list[SourceVideo]:
        return [
            SourceVideo("cam-a-original", "a.mp4", 100_000, 25.0, 2592, 1520, "hevc", "sig-a", "same-a", "2026-01-01T00:00:00Z"),
            SourceVideo("cam-a-transcode", "a-low.mp4", 100_000, 20.0, 1280, 720, "h264", "sig-b", "same-a", "2026-01-01T00:00:00Z"),
            SourceVideo("cam-b", "b.mp4", 80_000, 25.0, 2688, 1520, "hevc", "sig-c", "cam-b", "2026-01-01T00:00:00Z"),
            SourceVideo("cam-c", "c.mp4", 70_000, 25.0, 2688, 1520, "hevc", "sig-d", "cam-c", "2026-01-01T00:00:00Z"),
        ]

    def test_duplicate_groups_never_cross_splits_and_test_is_not_mineable(self) -> None:
        plan = assign_source_splits(self._sources())
        split_by_group: dict[str, set[str]] = {}
        for source in plan:
            split_by_group.setdefault(source["duplicateGroup"], set()).add(source["split"])
            if source["split"] == "test":
                self.assertFalse(source["mineForTraining"])
        self.assertTrue(all(len(splits) == 1 for splits in split_by_group.values()))

    def test_explicit_split_map_rejects_duplicate_group_leakage(self) -> None:
        with self.assertRaises(V9DatasetError):
            assign_source_splits(self._sources(), {"a.mp4": "train", "a-low.mp4": "test"})

    def test_selection_suppresses_near_duplicates_but_keeps_disagreement(self) -> None:
        frames = [
            CandidateFrame("f0", "s", 0, "0.jpg", "0000000000000000", 120.0, 80.0, 1.0),
            CandidateFrame("f1", "s", 3_000, "1.jpg", "0000000000000000", 120.0, 80.0, 1.0),
            CandidateFrame("f2", "s", 6_000, "2.jpg", "ffffffffffffffff", 120.0, 80.0, 20.0, disagreement_count=1),
        ]
        selected = select_diverse_frames(frames, target=2, max_hamming=4, minimum_gap_ms=1_000)
        self.assertEqual({frame.frame_id for frame in selected}, {"f0", "f2"})

    def test_locked_package_has_empty_labels_and_no_private_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "images/test").mkdir(parents=True)
            (root / "labels/test").mkdir(parents=True)
            image = np.zeros((48, 64, 3), dtype=np.uint8)
            cv2.imwrite(str(root / "images/test/f.jpg"), image)
            (root / "labels/test/f.txt").write_text("", encoding="utf-8")
            manifest = {
                "schemaVersion": 4,
                "datasetId": "locked",
                "classes": ["person", "bicycle", "car", "motorcycle", "bus", "truck", "container_truck", "forklift", "reach_stacker", "mobile_crane"],
                "lockedBlind": True,
                "sources": [{"sourceId": "s", "fileName": "video.mp4", "split": "test", "selectedFrames": 1}],
                "frames": [{"frameId": "f", "sourceId": "s", "timestampMs": 0, "split": "test", "imagePath": "images/test/f.jpg", "labelsPath": "labels/test/f.txt", "proposalCount": 0}],
            }
            (root / "annotation-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            report = audit_review_package(root)
            self.assertEqual(report["absolutePathLeaks"], 0)
            self.assertEqual(report["nonEmptyLockedLabels"], 0)
            self.assertEqual(report["errors"], [])


if __name__ == "__main__":
    unittest.main()
