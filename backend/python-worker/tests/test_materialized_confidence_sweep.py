from __future__ import annotations

import unittest

from evaluation.sweep_materialized_confidence import evaluate_threshold


class MaterializedConfidenceSweepTests(unittest.TestCase):
    def test_exact_counts_change_with_confidence(self) -> None:
        truths = {"frame": [[0.1, 0.1, 0.3, 0.3], [0.6, 0.6, 0.9, 0.9]]}
        predictions = {"frame": [
            {"bbox": [0.1, 0.1, 0.3, 0.3], "confidence": 0.8},
            {"bbox": [0.6, 0.6, 0.9, 0.9], "confidence": 0.2},
            {"bbox": [0.4, 0.1, 0.5, 0.2], "confidence": 0.3},
        ]}

        low = evaluate_threshold(truths, predictions, 0.1)
        high = evaluate_threshold(truths, predictions, 0.5)

        self.assertEqual((low["tp"], low["fp"], low["fn"]), (2, 1, 0))
        self.assertEqual((high["tp"], high["fp"], high["fn"]), (1, 0, 1))


if __name__ == "__main__":
    unittest.main()
