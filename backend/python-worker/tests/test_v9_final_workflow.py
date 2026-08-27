from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from evaluation.evaluate_v9_multiclass import _choose_thresholds, _read_truth
from training.v9_final_dataset import V9_CLASSES, _read_labels


class V9FinalWorkflowTests(unittest.TestCase):
    def test_final_label_remap_keeps_five_classes_and_deduplicates_exact_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            label = Path(directory) / "frame.txt"
            label.write_text(
                "0 0.5 0.5 0.1 0.2\n"
                "2 0.2 0.2 0.1 0.1\n"
                "2 0.2 0.2 0.1 0.1\n"
                "8 0.7 0.7 0.2 0.2\n",
                encoding="utf-8",
            )
            text, counts, duplicates = _read_labels(
                label,
                ["person", "bicycle", "car", "motorcycle", "bus", "truck", "container_truck", "forklift", "reach_stacker", "mobile_crane"],
            )
            self.assertEqual(duplicates, 1)
            self.assertEqual(counts, {"person": 1, "car": 1, "reach_stacker": 1})
            self.assertEqual([int(row.split()[0]) for row in text.splitlines()], [0, 1, 4])

    def test_unsupported_non_empty_class_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            label = Path(directory) / "frame.txt"
            label.write_text("1 0.5 0.5 0.1 0.1\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unsupported"):
                _read_labels(label, ["person", "bicycle"])

    def test_locked_truth_maps_canonical_ids_by_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            label = Path(directory) / "frame.txt"
            label.write_text("8 0.5 0.5 0.2 0.4\n", encoding="utf-8")
            truths = _read_truth(label, [
                "person", "bicycle", "car", "motorcycle", "bus", "truck",
                "container_truck", "forklift", "reach_stacker", "mobile_crane",
            ])
            self.assertEqual(truths[0]["class"], "reach_stacker")
            self.assertEqual(truths[0]["bbox"], [0.4, 0.3, 0.6, 0.7])

    def test_threshold_selection_prefers_balanced_gate(self) -> None:
        rows = []
        for confidence, precision, recall, f1 in (
            (0.10, 0.70, 0.95, 0.80),
            (0.20, 0.86, 0.88, 0.87),
            (0.30, 0.94, 0.70, 0.80),
        ):
            rows.append({
                "confidence": confidence,
                "metrics": {"perClass": {
                    name: {"precision": precision, "recall": recall, "f1": f1}
                    for name in V9_CLASSES
                }},
            })
        self.assertEqual(_choose_thresholds(rows), {name: 0.20 for name in V9_CLASSES})


if __name__ == "__main__":
    unittest.main()
