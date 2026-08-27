from __future__ import annotations

import unittest

from training.cvat_pull_reviewed_package import _shape_to_yolo
from training.v9_profile import EXPECTED_V9_CLASSES


class CvatPullReviewedPackageTests(unittest.TestCase):
    def test_rectangle_is_normalized_and_reversed_points_are_supported(self) -> None:
        result = _shape_to_yolo(
            {"type": "rectangle", "points": [80.0, 60.0, 20.0, 10.0]},
            width=100, height=100,
        )
        self.assertEqual(result, (0.5, 0.35, 0.6, 0.5))

    def test_invalid_or_unsupported_shapes_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported"):
            _shape_to_yolo({"type": "polygon", "points": [0, 0, 1, 1]}, 100, 100)
        with self.assertRaisesRegex(ValueError, "outside"):
            _shape_to_yolo({"type": "rectangle", "points": [-2, 0, 10, 10]}, 100, 100)

    def test_v9_round_trip_class_order_keeps_confusion_pairs_distinct(self) -> None:
        classes = list(EXPECTED_V9_CLASSES)
        selected = ["car", "truck", "forklift", "reach_stacker"]
        encoded = [classes.index(name) for name in selected]
        decoded = [classes[class_id] for class_id in encoded]
        self.assertEqual(decoded, selected)


if __name__ == "__main__":
    unittest.main()
