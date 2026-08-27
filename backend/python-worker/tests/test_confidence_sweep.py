from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.sweep_local_video_confidence import false_negative_records


class TestConfidenceSweep(unittest.TestCase):
    def test_false_negative_export_matches_by_confidence_and_iou(self) -> None:
        frames = [{"frameId": "f1", "sourceId": "s1", "timestampMs": 1000}]
        truth = {"f1": [
            {"class": "reach_stacker", "bbox": [0.1, 0.1, 0.3, 0.3]},
            {"class": "reach_stacker", "bbox": [0.6, 0.6, 0.8, 0.8]},
        ]}
        predictions = {"f1": [
            {"class": "reach_stacker", "confidence": 0.20, "bbox": [0.1, 0.1, 0.3, 0.3]},
            {"class": "reach_stacker", "confidence": 0.40, "bbox": [0.61, 0.61, 0.79, 0.79]},
        ]}

        missed = false_negative_records(frames, truth, predictions, 0.25)

        self.assertEqual([item["groundTruthIndex"] for item in missed], [0])
        self.assertEqual(missed[0]["bestPredictionConfidence"], 0.2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
