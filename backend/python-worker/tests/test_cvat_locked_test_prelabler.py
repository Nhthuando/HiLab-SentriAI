from __future__ import annotations

import unittest

from training.cvat_locked_test_prelabler import (
    build_prediction_shapes,
    filter_locked_proposals,
    merge_domain_and_base_candidates,
    validate_frame_mapping,
    verify_preapply_guards,
)


class CvatLockedTestPrelabelerTests(unittest.TestCase):
    def test_frame_mapping_requires_exact_name_and_dimensions(self) -> None:
        package_frames = [
            {"imagePath": "images/test/a.jpg", "originalResolution": [2592, 1520]},
            {"imagePath": "images/test/b.jpg", "originalResolution": [2688, 1520]},
        ]
        meta_frames = [
            {"name": "images/test/a.jpg", "width": 2592, "height": 1520},
            {"name": "images/test/b.jpg", "width": 2688, "height": 1520},
        ]
        validate_frame_mapping(package_frames, meta_frames)

        changed = [dict(meta_frames[0]), {**meta_frames[1], "width": 2592}]
        with self.assertRaisesRegex(ValueError, "mapping differs at frame 1"):
            validate_frame_mapping(package_frames, changed)

    def test_filter_prioritizes_recall_and_suppresses_cross_class_duplicates(self) -> None:
        proposals = [
            {"class": "forklift", "confidence": 0.24, "bbox": [0.1, 0.1, 0.4, 0.5]},
            {"class": "truck", "confidence": 0.23, "bbox": [0.1, 0.1, 0.4, 0.5]},
            {"class": "person", "confidence": 0.34, "bbox": [0.6, 0.2, 0.7, 0.7]},
            {"class": "car", "confidence": 0.30, "bbox": [0.7, 0.5, 0.9, 0.8]},
        ]
        kept = filter_locked_proposals(proposals)

        self.assertEqual([item["class"] for item in kept], ["car", "forklift"])

    def test_filter_removes_night_camera_timestamp_overlay(self) -> None:
        proposals = [
            {"class": "truck", "confidence": 0.9, "bbox": [0.0, 0.0, 0.24, 0.08]},
            {"class": "truck", "confidence": 0.8, "bbox": [0.4, 0.3, 0.7, 0.6]},
        ]

        kept = filter_locked_proposals(proposals, frame_index=127)

        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["bbox"], [0.4, 0.3, 0.7, 0.6])

    def test_filter_removes_static_container_row_misclassified_as_truck(self) -> None:
        proposals = [
            {"class": "truck", "confidence": 0.8, "bbox": [0.1, 0.5, 0.45, 0.7]},
            {"class": "truck", "confidence": 0.7, "bbox": [0.6, 0.5, 0.8, 0.7]},
        ]

        kept = filter_locked_proposals(proposals, frame_index=36)

        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["bbox"], [0.6, 0.5, 0.8, 0.7])

    def test_domain_helper_wins_over_overlapping_generic_bus_label(self) -> None:
        helper = [
            {"class": "truck", "confidence": 0.6, "bbox": [0.2, 0.2, 0.6, 0.6], "source": "task9-helper"}
        ]
        base = [
            {"class": "bus", "confidence": 0.9, "bbox": [0.21, 0.21, 0.59, 0.59], "source": "official-yolo11n-fallback"}
        ]

        kept = merge_domain_and_base_candidates(helper, base)

        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["class"], "truck")

    def test_build_prediction_shapes_converts_normalized_boxes_to_pixels(self) -> None:
        predictions = {
            "0": [{"class": "car", "confidence": 0.8, "bbox": [0.1, 0.2, 0.5, 0.8]}]
        }
        shapes = build_prediction_shapes(
            predictions,
            [{"width": 1000, "height": 500}],
            {"car": 13},
        )

        self.assertEqual(len(shapes), 1)
        self.assertEqual(shapes[0]["frame"], 0)
        self.assertEqual(shapes[0]["label_id"], 13)
        self.assertEqual(shapes[0]["points"], [100.0, 100.0, 500.0, 400.0])
        self.assertEqual(shapes[0]["source"], "auto")

    def test_preapply_guards_reject_changed_source_or_locked_annotations(self) -> None:
        verify_preapply_guards(
            expected_train_hash="train-hash",
            live_train_hash="train-hash",
            expected_locked_hash="locked-hash",
            live_locked_hash="locked-hash",
            expected_checkpoint_hash="checkpoint-hash",
            live_checkpoint_hash="checkpoint-hash",
        )

        with self.assertRaisesRegex(RuntimeError, "task 9"):
            verify_preapply_guards(
                expected_train_hash="train-hash",
                live_train_hash="changed",
                expected_locked_hash="locked-hash",
                live_locked_hash="locked-hash",
                expected_checkpoint_hash="checkpoint-hash",
                live_checkpoint_hash="checkpoint-hash",
            )
        with self.assertRaisesRegex(RuntimeError, "task 10"):
            verify_preapply_guards(
                expected_train_hash="train-hash",
                live_train_hash="train-hash",
                expected_locked_hash="locked-hash",
                live_locked_hash="changed",
                expected_checkpoint_hash="checkpoint-hash",
                live_checkpoint_hash="checkpoint-hash",
            )


if __name__ == "__main__":
    unittest.main()
