from __future__ import annotations

import unittest

from training.multiclass_hard_review_dataset import (
    evaluate_hard_cases,
    merge_prelabels,
    select_balanced_frames,
)


class MulticlassHardReviewDatasetTests(unittest.TestCase):
    def test_evaluation_separates_false_negative_and_low_confidence(self) -> None:
        frames = [{
            "frameId": "frame-1",
            "groundTruth": [
                {"class": "person", "bbox": [0.1, 0.1, 0.2, 0.3]},
                {"class": "reach_stacker", "bbox": [0.3, 0.3, 0.6, 0.7]},
                {"class": "forklift", "bbox": [0.7, 0.4, 0.9, 0.8]},
            ],
        }]
        predictions = {"frame-1": [
            {"class": "person", "bbox": [0.1, 0.1, 0.2, 0.3], "confidence": 0.90},
            {"class": "reach_stacker", "bbox": [0.3, 0.3, 0.6, 0.7], "confidence": 0.10},
        ]}
        metrics, details = evaluate_hard_cases(frames, predictions, confidence=0.25)

        self.assertEqual(metrics["person"]["tp"], 1)
        self.assertEqual(metrics["reach_stacker"]["fn"], 1)
        self.assertEqual(metrics["forklift"]["fn"], 1)
        reasons = {(item["class"], item["reason"]) for item in details["frame-1"]["hardObjects"]}
        self.assertIn(("reach_stacker", "low_confidence"), reasons)
        self.assertIn(("forklift", "false_negative"), reasons)

    def test_merge_keeps_reviewed_projection_and_only_unmatched_model_boxes(self) -> None:
        reviewed = [{"class": "reach_stacker", "bbox": [0.2, 0.2, 0.6, 0.7], "source": "reviewed_projection"}]
        predictions = [
            {"class": "reach_stacker", "bbox": [0.2, 0.2, 0.6, 0.7], "confidence": 0.9, "source": "custom"},
            {"class": "truck", "bbox": [0.2, 0.2, 0.6, 0.7], "confidence": 0.8, "source": "base"},
            {"class": "car", "bbox": [0.7, 0.4, 0.9, 0.7], "confidence": 0.1, "source": "base"},
        ]
        merged = merge_prelabels(reviewed, predictions, confidence=0.15)

        self.assertEqual([item["class"] for item in merged], ["reach_stacker", "truck"])

    def test_balanced_selection_suppresses_temporally_adjacent_frames(self) -> None:
        metrics = {
            name: {
                "gt": 1 if name == "reach_stacker" else 0,
                "recall": 0.2 if name == "reach_stacker" else None,
            }
            for name in ("person", "bicycle", "car", "motorcycle", "truck", "reach_stacker", "forklift")
        }
        frames = [{
            "frameId": f"frame-{index}",
            "sourceId": "source-1",
            "timestampMs": index * 10_000,
            "split": "train",
            "perceptualHash": f"{index:016x}",
            "groundTruth": [{"class": "reach_stacker", "bbox": [0.2, 0.2, 0.5, 0.6]}],
            "hardClasses": ["reach_stacker"],
            "hardObjects": [{"class": "reach_stacker", "reason": "false_negative"}],
        } for index in range(13)]

        selected, removals = select_balanced_frames(
            frames, metrics, target=5, minimum=4,
            minimum_gap_ms=30_000, minimum_hash_distance=0,
        )

        self.assertGreaterEqual(len(selected), 4)
        timestamps = sorted(int(item["timestampMs"]) for item in selected)
        self.assertTrue(all(right - left >= 30_000 for left, right in zip(timestamps, timestamps[1:])))
        self.assertGreater(removals.get("temporalNearDuplicate", 0), 0)


if __name__ == "__main__":
    unittest.main()
