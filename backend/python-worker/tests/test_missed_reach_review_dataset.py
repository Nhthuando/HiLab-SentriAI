from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from training.missed_reach_review_dataset import select_temporally_diverse


class TestMissedReachReviewDataset(unittest.TestCase):
    def test_selection_removes_exact_and_adjacent_near_duplicates(self) -> None:
        candidates = [
            {"timestampMs": 0, "sha256": "a", "perceptualHash": "0000000000000000", "isAnchor": True},
            {"timestampMs": 1, "sha256": "a", "perceptualHash": "0000000000000000", "isAnchor": False},
            {"timestampMs": 2, "sha256": "b", "perceptualHash": "0000000000000001", "isAnchor": False},
            {"timestampMs": 3, "sha256": "c", "perceptualHash": "0000000000000003", "isAnchor": False},
        ]

        selected = select_temporally_diverse(candidates, minimum=1, maximum=3, minimum_hash_distance=2)

        self.assertEqual([item["timestampMs"] for item in selected], [0, 3])

    def test_selection_keeps_review_load_within_bounds_and_preserves_anchor(self) -> None:
        candidates = [
            {
                "timestampMs": index,
                "sha256": str(index),
                "perceptualHash": f"{index:016x}",
                "isAnchor": index == 50,
            }
            for index in range(100)
        ]

        selected = select_temporally_diverse(candidates, minimum=60, maximum=80, minimum_hash_distance=0)

        self.assertEqual(len(selected), 80)
        self.assertTrue(any(item["isAnchor"] for item in selected))

    def test_near_duplicate_anchor_is_never_removed(self) -> None:
        candidates = [
            {"timestampMs": 0, "sha256": "a", "perceptualHash": "0000000000000000", "isAnchor": False},
            {"timestampMs": 1, "sha256": "b", "perceptualHash": "0000000000000000", "isAnchor": True},
        ]

        selected = select_temporally_diverse(candidates, minimum=1, maximum=2, minimum_hash_distance=2)

        self.assertEqual([item["timestampMs"] for item in selected], [0, 1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
