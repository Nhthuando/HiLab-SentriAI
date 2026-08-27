from __future__ import annotations

import unittest

from training.cvat_annotation_assist import (
    annotation_helper_train_options,
    audit_frame_indices,
    canonical_shape_hash,
    class_agnostic_nms,
    deterministic_split,
    filter_proposals_for_review,
    merge_preserving_prefix,
    shape_to_yolo,
)


def _shape(frame: int, label_id: int, points: list[float], *, shape_id: int = 1) -> dict:
    return {
        "id": shape_id,
        "type": "rectangle",
        "frame": frame,
        "label_id": label_id,
        "points": points,
        "occluded": False,
        "outside": False,
        "z_order": 0,
        "rotation": 0.0,
        "attributes": [],
        "source": "manual",
    }


class CvatAnnotationAssistTests(unittest.TestCase):
    def test_canonical_hash_ignores_server_ids_but_detects_review_changes(self) -> None:
        first = _shape(4, 10, [10.0, 20.0, 30.0, 40.0], shape_id=1)
        same = {**first, "id": 99}
        self.assertEqual(canonical_shape_hash([first]), canonical_shape_hash([same]))
        changed = {**same, "points": [10.0, 20.0, 31.0, 40.0]}
        self.assertNotEqual(canonical_shape_hash([first]), canonical_shape_hash([changed]))

    def test_shape_to_yolo_normalizes_rectangle(self) -> None:
        self.assertEqual(
            shape_to_yolo(_shape(0, 1, [20.0, 10.0, 80.0, 60.0]), 100, 100),
            (0.5, 0.35, 0.6, 0.5),
        )
        with self.assertRaisesRegex(ValueError, "outside"):
            shape_to_yolo(_shape(0, 1, [-1.0, 0.0, 10.0, 10.0]), 100, 100)

    def test_deterministic_split_keeps_train_and_validation_nonempty(self) -> None:
        train, val = deterministic_split(list(range(21)), val_stride=7)
        self.assertEqual(val, [6, 13, 20])
        self.assertEqual(len(train), 18)
        self.assertTrue(set(train).isdisjoint(val))

    def test_class_agnostic_nms_suppresses_cross_class_duplicate(self) -> None:
        proposals = [
            {"class": "reach_stacker", "confidence": 0.82, "bbox": [0.1, 0.1, 0.5, 0.5]},
            {"class": "truck", "confidence": 0.65, "bbox": [0.11, 0.1, 0.51, 0.5]},
            {"class": "person", "confidence": 0.70, "bbox": [0.7, 0.2, 0.75, 0.5]},
        ]
        kept = class_agnostic_nms(proposals, iou_threshold=0.5)
        self.assertEqual([item["class"] for item in kept], ["reach_stacker", "person"])

    def test_merge_preserves_only_prefix_and_replaces_remaining_shapes(self) -> None:
        prefix = _shape(209, 1, [1.0, 2.0, 3.0, 4.0], shape_id=5)
        stale = _shape(210, 1, [5.0, 6.0, 7.0, 8.0], shape_id=6)
        prediction = _shape(210, 2, [10.0, 11.0, 12.0, 13.0], shape_id=7)
        merged = merge_preserving_prefix([prefix, stale], [prediction], boundary=210)
        self.assertEqual(len(merged), 2)
        self.assertEqual(canonical_shape_hash([merged[0]]), canonical_shape_hash([prefix]))
        self.assertEqual(merged[1]["label_id"], 2)
        self.assertNotIn("id", merged[0])
        self.assertNotIn("id", merged[1])

    def test_merge_protects_manual_suffix_and_drops_overlapping_prediction(self) -> None:
        prefix = _shape(810, 1, [1.0, 2.0, 3.0, 4.0], shape_id=5)
        protected = _shape(820, 2, [100.0, 100.0, 200.0, 200.0], shape_id=6)
        stale_auto = {**_shape(820, 3, [300.0, 300.0, 400.0, 400.0], shape_id=7), "source": "auto"}
        duplicate_prediction = {**_shape(820, 4, [105.0, 105.0, 198.0, 198.0], shape_id=8), "source": "auto"}
        fresh_prediction = {**_shape(821, 4, [10.0, 10.0, 20.0, 20.0], shape_id=9), "source": "auto"}
        merged = merge_preserving_prefix(
            [prefix, protected, stale_auto],
            [duplicate_prediction, fresh_prediction],
            boundary=811,
            preserve_manual_suffix=True,
        )
        self.assertEqual([(shape["frame"], shape["source"]) for shape in merged], [
            (810, "manual"), (820, "manual"), (821, "auto"),
        ])

    def test_helper_training_is_low_resource_and_never_reuses_v8(self) -> None:
        options = annotation_helper_train_options("runs", epochs=40, device=0, boundary=210)
        self.assertEqual(options["batch"], 1)
        self.assertEqual(options["workers"], 0)
        self.assertFalse(options["cache"])
        self.assertTrue(options["amp"])
        self.assertEqual(options["epochs"], 40)
        self.assertNotIn("resume", options)
        self.assertEqual(options["name"], "baikiem-v9-annotation-assist-210")

    def test_second_iteration_has_boundary_run_name_and_lower_fine_tune_rate(self) -> None:
        options = annotation_helper_train_options(
            "runs", epochs=25, device=0, boundary=600, fine_tune=True,
        )
        self.assertEqual(options["name"], "baikiem-v9-annotation-assist-600")
        self.assertEqual(options["lr0"], 0.0005)
        self.assertEqual(options["warmup_epochs"], 1.0)

    def test_audit_frames_span_only_the_current_remaining_range(self) -> None:
        selected = audit_frame_indices(boundary=600, total_frames=1000, limit=12)
        self.assertEqual(selected[0], 600)
        self.assertEqual(selected[-1], 999)
        self.assertEqual(len(selected), 12)
        self.assertEqual(selected, sorted(set(selected)))

    def test_review_filter_raises_thresholds_and_removes_second_camera_overlay(self) -> None:
        proposals = [
            {"class": "person", "confidence": 0.90, "bbox": [0.10, 0.04, 0.12, 0.09]},
            {"class": "person", "confidence": 0.49, "bbox": [0.40, 0.40, 0.43, 0.55]},
            {"class": "person", "confidence": 0.80, "bbox": [0.40, 0.40, 0.43, 0.55]},
            {"class": "reach_stacker", "confidence": 0.20, "bbox": [0.50, 0.40, 0.70, 0.70]},
            {"class": "truck", "confidence": 0.80, "bbox": [0.60, 0.40, 0.80, 0.70]},
        ]
        filtered = filter_proposals_for_review(300, proposals)
        self.assertEqual([(item["class"], item["confidence"]) for item in filtered], [
            ("person", 0.80), ("truck", 0.80),
        ])


if __name__ == "__main__":
    unittest.main()
