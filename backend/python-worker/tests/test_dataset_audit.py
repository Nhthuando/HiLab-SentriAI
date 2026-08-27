"""Focused tests for the immutable YOLO snapshot audit."""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from training.dataset_audit import audit_dataset, render_markdown


class TestDatasetAudit(unittest.TestCase):
    def _raw_api_fixture(self, root: Path) -> Path:
        snapshot = root / "raw-api-snapshot"
        media = snapshot / "media"
        media.mkdir(parents=True)
        pixels = np.zeros((48, 64, 3), dtype=np.uint8)
        pixels[:, 20:44] = (30, 180, 240)
        encoded_media: list[tuple[str, bytes]] = []
        for suffix in (".png", ".bmp"):
            ok, encoded = cv2.imencode(suffix, pixels)
            self.assertTrue(ok)
            payload = encoded.tobytes()
            digest = hashlib.sha256(payload).hexdigest()
            filename = f"{digest}{suffix}"
            (media / filename).write_bytes(payload)
            encoded_media.append((filename, payload))

        samples = []
        for index, ((filename, payload), split) in enumerate(zip(encoded_media, ("train", "val"), strict=True)):
            samples.append({
                "sampleId": f"route-sample-{index}",
                "label": "Xe nâng container",
                "baseClass": "reach_stacker",
                "sourceId": f"route-source-{index}",
                "mediaKind": "IMAGE",
                "frameTimestampMs": None,
                "bbox": {"x": 0.2, "y": 0.2, "w": 0.2, "h": 0.2},
                "mediaPath": f"media/{filename}",
                "mediaSha256": hashlib.sha256(payload).hexdigest(),
                "split": split,
            })
        manifest = {
            "schemaVersion": 2,
            "profile": "YARD_CUSTOM_V2",
            "requiredClasses": [{"label": "Xe nâng container", "baseClass": "reach_stacker"}],
            "samples": samples,
            "contentHash": "a" * 64,
            "createdAt": "2026-08-22T00:00:00.000Z",
            "excluded": [],
            "ignoredSamples": 0,
            "origin": {
                "kind": "external_yolo_archive",
                "archiveName": "route-fixture.zip",
                "sourceLabelMap": {"stacker": {"label": "Xe nâng container", "baseClass": "reach_stacker"}},
            },
        }
        (snapshot / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return snapshot

    def _fixture(self, root: Path) -> Path:
        snapshot = root / "snapshot"
        for split in ("train", "val", "test"):
            (snapshot / "images" / split).mkdir(parents=True)
            (snapshot / "labels" / split).mkdir(parents=True)

        exact = np.zeros((40, 60, 3), dtype=np.uint8)
        exact[:, 20:40] = 180
        different = np.zeros((50, 50, 3), dtype=np.uint8)
        cv2.circle(different, (25, 25), 14, (255, 255, 255), -1)
        negative = np.full((32, 48, 3), 90, dtype=np.uint8)
        self.assertTrue(cv2.imwrite(str(snapshot / "images" / "train" / "shared-train.png"), exact))
        self.assertTrue(cv2.imwrite(str(snapshot / "images" / "test" / "duplicate.png"), exact))
        self.assertTrue(cv2.imwrite(str(snapshot / "images" / "val" / "shared-val.png"), different))
        self.assertTrue(cv2.imwrite(str(snapshot / "images" / "train" / "negative.png"), negative))

        (snapshot / "labels" / "train" / "shared-train.txt").write_text("0 0.5 0.5 0.05 0.05\n", encoding="utf-8")
        (snapshot / "labels" / "test" / "duplicate.txt").write_text("0 0.4 0.4 0.2 0.2\n", encoding="utf-8")
        (snapshot / "labels" / "val" / "shared-val.txt").write_text("0 0.3 0.25 0.6 0.5\n", encoding="utf-8")
        (snapshot / "labels" / "train" / "negative.txt").write_text("", encoding="utf-8")
        (snapshot / "data.yaml").write_text("names:\n  0: Xe nâng container\n", encoding="utf-8")

        samples = [
            {
                "sampleId": "shared-train", "label": "Xe nâng container", "baseClass": "reach_stacker",
                "sourceId": "source-shared", "mediaKind": "IMAGE", "frameTimestampMs": None,
                "mediaPath": "media/shared-train.png", "split": "train",
            },
            {
                "sampleId": "shared-val", "label": "Xe nâng container", "baseClass": "reach_stacker",
                "sourceId": "source-shared", "mediaKind": "IMAGE", "frameTimestampMs": None,
                "mediaPath": "media/shared-val.png", "split": "val",
            },
            {
                "sampleId": "duplicate", "label": "Xe nâng container", "baseClass": "reach_stacker",
                "sourceId": "source-duplicate", "mediaKind": "IMAGE", "frameTimestampMs": None,
                "mediaPath": "media/duplicate.png", "split": "test",
            },
        ]
        manifest = {"schemaVersion": 2, "profile": "YARD_CUSTOM_V2", "samples": samples}
        (snapshot / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return snapshot

    def test_reports_duplicates_leakage_negatives_sources_and_box_buckets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = audit_dataset(self._fixture(Path(directory)))

        self.assertEqual(report["summary"]["imageCount"], 4)
        self.assertEqual(report["summary"]["bboxCount"], 3)
        self.assertEqual(report["summary"]["sourceCount"], 3)
        self.assertEqual(report["summary"]["negativeImageCount"], 1)
        self.assertEqual(report["summary"]["negativeRatio"], 0.25)
        self.assertEqual(report["perClass"], {"Xe nâng container": 3})
        self.assertEqual(report["bboxAreas"]["buckets"], {
            "smallLt1Pct": 1,
            "medium1To10Pct": 1,
            "largeGte10Pct": 1,
        })
        self.assertEqual(len(report["duplicates"]["exactGroups"]), 1)
        self.assertEqual(report["duplicates"]["exactGroups"][0]["splits"], ["test", "train"])
        self.assertEqual(report["leakage"]["sourcesAcrossSplits"], [
            {"sourceId": "source-shared", "splits": ["train", "val"]},
        ])

    def test_markdown_states_non_semantic_scope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = audit_dataset(self._fixture(Path(directory)))
        markdown = render_markdown(report)
        self.assertIn("Nó không suy đoán loại background", markdown)
        self.assertIn("golden validation set", markdown)

    def test_invalid_annotation_is_not_misreported_as_negative(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            snapshot = self._fixture(Path(directory))
            (snapshot / "labels" / "train" / "negative.txt").write_text("9 0.5 0.5 0.1 0.1\n", encoding="utf-8")
            report = audit_dataset(snapshot)
        self.assertEqual(report["summary"]["negativeImageCount"], 0)
        self.assertEqual(report["summary"]["invalidAnnotationCount"], 1)

    def test_audits_raw_api_snapshot_in_isolated_materialization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            snapshot = self._raw_api_fixture(Path(directory))
            self.assertFalse((snapshot / "images").exists())
            report = audit_dataset(snapshot, prior_median_percent=54.77)
            self.assertFalse((snapshot / "images").exists())

        self.assertEqual(report["summary"]["imageCount"], 2)
        self.assertEqual(report["summary"]["bboxCount"], 2)
        self.assertEqual(report["perClass"], {"Xe nâng container": 2})
        self.assertEqual(len(report["duplicates"]["exactGroups"]), 1)
        self.assertEqual(report["origin"]["archiveName"], "route-fixture.zip")
        self.assertEqual(report["requiredClasses"], [{"label": "Xe nâng container", "baseClass": "reach_stacker"}])
        self.assertEqual(report["evidenceReconciliation"]["priorDocumentedMedianPercent"], 54.77)

        markdown = render_markdown(report)
        self.assertIn("| Exact duplicate groups | 1 |", markdown)
        self.assertIn("Phát hiện 1 exact duplicate group", markdown)
        self.assertIn("Mapping nguồn `stacker` → `Xe nâng container` / `reach_stacker`", markdown)
        self.assertIn("Class contract `Xe nâng container` / `reach_stacker`", markdown)
        self.assertIn("54.77%", markdown)

    def test_audits_reviewed_local_video_snapshot_schema_three(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "local-reviewed"
            for split in ("train", "val", "test"):
                (root / "images" / split).mkdir(parents=True)
                (root / "labels" / split).mkdir(parents=True)
            frames = []
            for index, split in enumerate(("train", "val", "test")):
                frame_id = f"frame-{index}"
                image = np.full((40, 60, 3), 40 + index * 40, dtype=np.uint8)
                image_path = root / "images" / split / f"{frame_id}.jpg"
                self.assertTrue(cv2.imwrite(str(image_path), image))
                label_path = root / "labels" / split / f"{frame_id}.txt"
                label_path.write_text("0 0.5 0.5 0.2 0.2\n" if index < 2 else "", encoding="utf-8")
                frames.append({
                    "frameId": frame_id,
                    "sourceId": f"source-{index}",
                    "split": split,
                    "imagePath": image_path.relative_to(root).as_posix(),
                    "labelsPath": label_path.relative_to(root).as_posix(),
                    "reviewStatus": "REVIEWED",
                })
            (root / "data.yaml").write_text("names:\n  0: reach_stacker\n", encoding="utf-8")
            (root / "manifest.json").write_text(json.dumps({
                "schemaVersion": 3,
                "datasetKind": "LOCAL_VIDEO_REVIEWED",
                "reviewStatus": "REVIEWED",
                "classes": ["reach_stacker"],
                "frames": frames,
            }), encoding="utf-8")
            report = audit_dataset(root)

        self.assertEqual(report["summary"]["imageCount"], 3)
        self.assertEqual(report["summary"]["negativeImageCount"], 1)
        self.assertEqual(report["perClass"], {"reach_stacker": 2})
        self.assertEqual(report["splits"]["test"]["negatives"], 1)
        self.assertEqual(report["leakage"]["sourcesAcrossSplits"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
