from __future__ import annotations

import json
import csv
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from training.local_video_dataset import (
    CLASS_NAMES,
    LocalVideoPlanError,
    Proposal,
    build_annotation_package,
    create_cvat_archive,
    export_reach_stacker_supplemental_snapshot,
    finalize_reviewed_package,
    merge_proposals,
    repartition_reviewed_snapshot,
    stage_cvat_reviewed_package,
    validate_video_plan,
)


class TestLocalVideoDataset(unittest.TestCase):
    def _video(self, directory: Path, name: str = "source.avi") -> Path:
        path = directory / name
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (96, 64))
        self.assertTrue(writer.isOpened())
        for index in range(40):
            frame = np.full((64, 96, 3), 30 + index, dtype=np.uint8)
            cv2.rectangle(frame, (10 + index, 20), (30 + index, 48), (230, 80, 30), -1)
            writer.write(frame)
        writer.release()
        return path

    def _plan(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "datasetId": "BAI-KIEM-LOCAL-TEST",
            "classes": list(CLASS_NAMES),
            "sources": [
                {
                    "sourceId": "source-a",
                    "fileName": "source.avi",
                    "duplicateGroup": "source-a-originals",
                    "role": "positive",
                    "ranges": [
                        {"startMs": 0, "endMs": 2000, "split": "train", "intervalMs": 1000},
                        {"startMs": 2000, "endMs": 4000, "split": "val", "intervalMs": 1000},
                    ],
                }
            ],
        }

    def test_plan_rejects_duplicate_group_crossing_train_and_test(self) -> None:
        plan = self._plan()
        plan["sources"].append({
            "sourceId": "source-copy",
            "fileName": "source-copy.avi",
            "duplicateGroup": "source-a-originals",
            "role": "positive",
            "ranges": [{"startMs": 0, "endMs": 1000, "split": "test", "intervalMs": 1000}],
        })
        with self.assertRaisesRegex(LocalVideoPlanError, "duplicateGroup"):
            validate_video_plan(plan)

    def test_plan_requires_exact_class_order_and_unique_source_ids(self) -> None:
        plan = self._plan()
        plan["classes"] = ["reach_stacker", "truck"]
        with self.assertRaisesRegex(LocalVideoPlanError, "classes"):
            validate_video_plan(plan)
        plan = self._plan()
        plan["sources"].append(dict(plan["sources"][0]))
        with self.assertRaisesRegex(LocalVideoPlanError, "sourceId"):
            validate_video_plan(plan)

    def test_reach_proposal_suppresses_only_overlapping_truck(self) -> None:
        base = [
            Proposal("truck", 0.8, (10.0, 10.0, 60.0, 60.0), "COCO"),
            Proposal("person", 0.7, (70.0, 10.0, 90.0, 60.0), "COCO"),
            Proposal("truck", 0.6, (70.0, 65.0, 95.0, 95.0), "COCO"),
        ]
        reach = [Proposal("reach_stacker", 0.55, (12.0, 8.0, 61.0, 62.0), "CUSTOM")]
        merged = merge_proposals(base, reach, overlap_threshold=0.35)
        self.assertEqual([item.class_name for item in merged], ["person", "truck", "reach_stacker"])

    def test_package_is_portable_pending_and_split_locked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._video(root)
            plan_path = root / "plan.json"
            plan_path.write_text(json.dumps(self._plan()), encoding="utf-8")

            def predictor(_frame: np.ndarray, _source_id: str, timestamp_ms: int) -> list[Proposal]:
                return [Proposal("reach_stacker", 0.51, (10.0, 10.0, 50.0, 50.0), "CUSTOM")]

            output = root / "package"
            summary = build_annotation_package(
                plan_path,
                root,
                output,
                predictor=predictor,
                output_width=96,
                output_height=64,
                jpeg_quality=90,
                dhash_distance_threshold=0,
            )
            manifest = json.loads((output / "annotation-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["frameCount"], 4)
            self.assertEqual(len(manifest["frames"]), 4)
            self.assertTrue(all(item["reviewStatus"] == "PENDING_REVIEW" for item in manifest["frames"]))
            self.assertTrue(all(not Path(item["imagePath"]).is_absolute() for item in manifest["frames"]))
            self.assertNotIn(str(root), json.dumps(manifest))
            train_images = {path.name for path in (output / "images" / "train").glob("*.jpg")}
            val_images = {path.name for path in (output / "images" / "val").glob("*.jpg")}
            self.assertTrue(train_images)
            self.assertTrue(val_images)
            self.assertFalse(train_images & val_images)
            self.assertTrue((output / "data.yaml").is_file())
            self.assertTrue((output / "review.csv").is_file())
            self.assertTrue((output / "train.txt").read_text(encoding="utf-8").strip())
            self.assertTrue((output / "val.txt").read_text(encoding="utf-8").strip())

            archive_path = create_cvat_archive(output, root / "cvat.zip")
            with zipfile.ZipFile(archive_path) as archive:
                names = archive.namelist()
                self.assertTrue(names)
                self.assertFalse(any("\\" in name for name in names))
                self.assertEqual(len([name for name in names if name.startswith("images/")]), 4)
                self.assertIsNone(archive.testzip())

    def test_finalize_requires_every_frame_reviewed_and_preserves_locked_splits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._video(root)
            plan_path = root / "plan.json"
            plan_path.write_text(json.dumps(self._plan()), encoding="utf-8")
            package = root / "package"
            build_annotation_package(
                plan_path,
                root,
                package,
                predictor=lambda _frame, _source, _timestamp: [],
                output_width=96,
                output_height=64,
                dhash_distance_threshold=0,
            )
            with self.assertRaisesRegex(LocalVideoPlanError, "PENDING_REVIEW"):
                finalize_reviewed_package(package, package, root / "snapshots")

            rows: list[dict[str, str]] = []
            with (package / "review.csv").open("r", newline="", encoding="utf-8-sig") as handle:
                rows = list(csv.DictReader(handle))
            for row in rows:
                row["reviewStatus"] = "REVIEWED"
            with (package / "review.csv").open("w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)

            snapshot = finalize_reviewed_package(package, package, root / "snapshots")
            finalized = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(finalized["schemaVersion"], 3)
            self.assertEqual(finalized["reviewStatus"], "REVIEWED")
            self.assertRegex(finalized["contentHash"], r"^[0-9a-f]{64}$")
            self.assertEqual({item["split"] for item in finalized["frames"]}, {"train", "val"})

    def test_cvat_review_staging_requires_attestation_and_preserves_negative_frames(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._video(root)
            plan_path = root / "plan.json"
            plan_path.write_text(json.dumps(self._plan()), encoding="utf-8")
            package = root / "package"
            build_annotation_package(
                plan_path,
                root,
                package,
                predictor=lambda _frame, _source, _timestamp: [
                    Proposal("reach_stacker", 0.8, (10.0, 10.0, 50.0, 50.0), "CUSTOM")
                ],
                output_width=96,
                output_height=64,
                dhash_distance_threshold=0,
            )
            archive_path = create_cvat_archive(package, root / "export.zip")
            with self.assertRaisesRegex(LocalVideoPlanError, "confirmation"):
                stage_cvat_reviewed_package(
                    package, archive_path, root / "reviewed", reviewer_confirmation=False,
                )

            # Simulate CVAT omitting the label file for one reviewed negative.
            negative_label = json.loads(
                (package / "annotation-manifest.json").read_text(encoding="utf-8")
            )["frames"][0]["labelsPath"]
            without_negative = root / "export-with-negative.zip"
            with zipfile.ZipFile(archive_path) as source, zipfile.ZipFile(without_negative, "w") as destination:
                for info in source.infolist():
                    if info.filename != negative_label:
                        destination.writestr(info, source.read(info))
            reviewed = stage_cvat_reviewed_package(
                package, without_negative, root / "reviewed", reviewer_confirmation=True,
            )
            self.assertEqual((reviewed / negative_label).read_text(encoding="utf-8"), "")
            with (reviewed / "review.csv").open("r", newline="", encoding="utf-8-sig") as handle:
                self.assertTrue(all(row["reviewStatus"] == "REVIEWED" for row in csv.DictReader(handle)))
            snapshot = finalize_reviewed_package(package, reviewed, root / "snapshots")
            self.assertTrue((snapshot / "manifest.json").is_file())

    def test_cvat_review_staging_normalizes_task_export_split_wrapper(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._video(root)
            plan_path = root / "plan.json"
            plan_path.write_text(json.dumps(self._plan()), encoding="utf-8")
            package = root / "package"
            build_annotation_package(
                plan_path,
                root,
                package,
                predictor=lambda _frame, _source, _timestamp: [],
                output_width=96,
                output_height=64,
                dhash_distance_threshold=0,
            )
            archive_path = create_cvat_archive(package, root / "export.zip")
            wrapped_path = root / "wrapped-export.zip"
            with zipfile.ZipFile(archive_path) as source, zipfile.ZipFile(wrapped_path, "w") as destination:
                for info in source.infolist():
                    name = info.filename
                    if name.startswith("images/"):
                        name = f"images/train/{name}"
                    elif name.startswith("labels/"):
                        name = f"labels/train/images/{name.removeprefix('labels/')}"
                    destination.writestr(name, source.read(info))

            reviewed = stage_cvat_reviewed_package(
                package, wrapped_path, root / "reviewed", reviewer_confirmation=True,
            )
            snapshot = finalize_reviewed_package(package, reviewed, root / "snapshots")
            self.assertTrue((snapshot / "manifest.json").is_file())

    def test_finalize_rejects_changed_images_and_invalid_boxes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._video(root)
            plan_path = root / "plan.json"
            plan_path.write_text(json.dumps(self._plan()), encoding="utf-8")
            package = root / "package"
            build_annotation_package(
                plan_path,
                root,
                package,
                predictor=lambda _frame, _source, _timestamp: [],
                output_width=96,
                output_height=64,
                dhash_distance_threshold=0,
            )
            rows: list[dict[str, str]]
            with (package / "review.csv").open("r", newline="", encoding="utf-8-sig") as handle:
                rows = list(csv.DictReader(handle))
            for row in rows:
                row["reviewStatus"] = "REVIEWED"
            with (package / "review.csv").open("w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            first = json.loads((package / "annotation-manifest.json").read_text(encoding="utf-8"))["frames"][0]
            label_path = package / first["labelsPath"]
            label_path.write_text("99 0.5 0.5 0.1 0.1\n", encoding="utf-8")
            with self.assertRaisesRegex(LocalVideoPlanError, "unknown class id"):
                finalize_reviewed_package(package, package, root / "snapshots")
            label_path.write_text("", encoding="utf-8")
            image_path = package / first["imagePath"]
            image_path.write_bytes(image_path.read_bytes() + b"changed")
            with self.assertRaisesRegex(LocalVideoPlanError, "image hash"):
                finalize_reviewed_package(package, package, root / "snapshots")

    def test_reviewed_snapshot_projects_reach_and_all_other_frames_as_negatives(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._video(root)
            plan_path = root / "plan.json"
            plan_path.write_text(json.dumps(self._plan()), encoding="utf-8")
            package = root / "package"
            build_annotation_package(
                plan_path,
                root,
                package,
                predictor=lambda _frame, _source, _timestamp: [
                    Proposal("reach_stacker", 0.8, (10.0, 10.0, 50.0, 50.0), "CUSTOM")
                ],
                output_width=96,
                output_height=64,
                dhash_distance_threshold=0,
            )
            with (package / "review.csv").open("r", newline="", encoding="utf-8-sig") as handle:
                rows = list(csv.DictReader(handle))
            for row in rows:
                row["reviewStatus"] = "REVIEWED"
            with (package / "review.csv").open("w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            manifest = json.loads((package / "annotation-manifest.json").read_text(encoding="utf-8"))
            (package / manifest["frames"][0]["labelsPath"]).write_text("", encoding="utf-8")
            reviewed = finalize_reviewed_package(package, package, root / "reviewed")

            supplemental = export_reach_stacker_supplemental_snapshot(reviewed, root / "supplemental")
            projected = json.loads((supplemental / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(projected["schemaVersion"], 2)
            self.assertEqual(projected["requiredClasses"][0]["baseClass"], "reach_stacker")
            self.assertEqual(len(projected["samples"]), 3)
            self.assertEqual(len(projected["negativeMedia"]), 1)
            self.assertEqual(
                {item["split"] for item in [*projected["samples"], *projected["negativeMedia"]]},
                {"train", "val"},
            )
            self.assertTrue(all(Path(item["mediaPath"]).parts[0] == "media" for item in projected["samples"]))

    def test_repartition_moves_only_locked_time_blocks_and_preserves_labels(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._video(root)
            plan_path = root / "plan.json"
            plan_path.write_text(json.dumps(self._plan()), encoding="utf-8")
            package = root / "package"
            build_annotation_package(
                plan_path, root, package,
                predictor=lambda _frame, _source, _timestamp: [
                    Proposal("reach_stacker", 0.8, (10.0, 10.0, 50.0, 50.0), "CUSTOM")
                ],
                output_width=96, output_height=64, dhash_distance_threshold=0,
            )
            with (package / "review.csv").open("r", newline="", encoding="utf-8-sig") as handle:
                rows = list(csv.DictReader(handle))
            for row in rows:
                row["reviewStatus"] = "REVIEWED"
            with (package / "review.csv").open("w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            reviewed = finalize_reviewed_package(package, package, root / "reviewed")
            original = json.loads((reviewed / "manifest.json").read_text(encoding="utf-8"))

            repartitioned = repartition_reviewed_snapshot(
                reviewed, root / "repartitioned",
                dataset_id="BAI-KIEM-LOCAL-TEST-V2",
                source_policies={
                    "source-a": {
                        "role": "positive",
                        "ranges": [
                            {"startMs": 0, "endMs": 3000, "split": "train", "intervalMs": 1000},
                            {"startMs": 3000, "endMs": 5000, "split": "test", "intervalMs": 1000},
                        ],
                    },
                },
            )
            updated = json.loads((repartitioned / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(updated["parentContentHash"], original["contentHash"])
            self.assertEqual([frame["split"] for frame in updated["frames"]], ["train", "train", "train", "test"])
            self.assertTrue((repartitioned / updated["frames"][-1]["labelsPath"]).is_file())
            self.assertIn("images/test/", (repartitioned / "test.txt").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
