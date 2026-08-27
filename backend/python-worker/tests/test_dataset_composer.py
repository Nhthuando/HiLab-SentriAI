"""Composition checks for immutable reach-stacker training snapshots."""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from training.dataset_composer import TARGET_LABEL, compose_snapshots


class TestDatasetComposer(unittest.TestCase):
    @staticmethod
    def _snapshot(
        root: Path,
        name: str,
        *,
        label: str,
        base_class: str,
        source_id: str,
        split: str,
        include_negative: bool = False,
    ) -> Path:
        directory = root / name
        media_dir = directory / "media"
        media_dir.mkdir(parents=True)
        positive = f"positive-{name}".encode()
        positive_hash = hashlib.sha256(positive).hexdigest()
        (media_dir / f"{positive_hash}.jpg").write_bytes(positive)
        manifest: dict[str, object] = {
            "schemaVersion": 2,
            "samples": [{
                "sampleId": f"sample-{name}", "label": label, "baseClass": base_class,
                "sourceId": source_id, "mediaKind": "IMAGE", "frameTimestampMs": None,
                "bbox": {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4},
                "mediaPath": f"media/{positive_hash}.jpg", "mediaSha256": positive_hash, "split": split,
            }],
        }
        if include_negative:
            negative = f"negative-{name}".encode()
            negative_hash = hashlib.sha256(negative).hexdigest()
            (media_dir / f"{negative_hash}.jpg").write_bytes(negative)
            manifest["negativeMedia"] = [{
                "negativeId": f"negative-{name}", "sourceId": f"negative-source-{name}",
                "mediaKind": "IMAGE", "frameTimestampMs": None,
                "mediaPath": f"media/{negative_hash}.jpg", "mediaSha256": negative_hash,
                "split": split, "reasonClasses": ["Dump Truck"],
            }]
        path = directory / "manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return path

    def test_composes_legacy_and_canonical_snapshots_with_negatives(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = self._snapshot(
                root, "legacy", label="Xe nâng", base_class="reach stacker",
                source_id="legacy-source", split="train",
            )
            canonical = self._snapshot(
                root, "canonical", label="Xe nâng container", base_class="reach_stacker",
                source_id="canonical-source", split="val", include_negative=True,
            )
            result = compose_snapshots([legacy, canonical], root / "output")
            manifest = json.loads(Path(result["manifestPath"]).read_text(encoding="utf-8"))
            self.assertEqual(manifest["requiredClasses"], [{
                "label": "Xe nâng container", "baseClass": "reach_stacker",
            }])
            self.assertEqual({sample["label"] for sample in manifest["samples"]}, {"Xe nâng container"})
            self.assertEqual({sample["baseClass"] for sample in manifest["samples"]}, {"reach_stacker"})
            self.assertEqual(len(manifest["samples"]), 2)
            self.assertEqual(len(manifest["negativeMedia"]), 1)
            self.assertEqual(result["positiveBoxCount"], 2)
            self.assertEqual(result["negativeImageCount"], 1)
            for record in [*manifest["samples"], *manifest["negativeMedia"]]:
                self.assertTrue((Path(result["directory"]) / record["mediaPath"]).is_file())

    def test_rejects_one_source_across_composed_splits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            train = self._snapshot(
                root, "train", label="Xe nâng", base_class="reach stacker",
                source_id="shared", split="train",
            )
            val = self._snapshot(
                root, "val", label="Xe nâng container", base_class="reach_stacker",
                source_id="shared", split="val",
            )
            with self.assertRaisesRegex(ValueError, "multiple splits"):
                compose_snapshots([train, val], root / "output")

    def test_can_exclude_consumed_parent_source_from_one_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            consumed = self._snapshot(
                root, "old-test", label="Xe nĂ¢ng container", base_class="reach_stacker",
                source_id="local:old:test", split="test", include_negative=True,
            )
            consumed_manifest = json.loads(consumed.read_text(encoding="utf-8"))
            consumed_manifest["contentHash"] = "old-content"
            consumed_manifest["samples"][0]["parentSourceId"] = "consumed-recording"
            consumed_manifest["negativeMedia"][0]["parentSourceId"] = "consumed-recording"
            consumed.write_text(json.dumps(consumed_manifest), encoding="utf-8")
            current = self._snapshot(
                root, "current", label="Xe nĂ¢ng container", base_class="reach_stacker",
                source_id="local:current:train", split="train",
            )

            current_manifest = json.loads(current.read_text(encoding="utf-8"))
            current_manifest["samples"][0]["label"] = TARGET_LABEL
            current.write_text(json.dumps(current_manifest), encoding="utf-8")

            result = compose_snapshots(
                [consumed, current],
                root / "output",
                excluded_parent_sources={"old-content": {"consumed-recording"}},
            )

            manifest = json.loads(Path(result["manifestPath"]).read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["samples"]), 1)
            self.assertEqual(len(manifest["negativeMedia"]), 0)
            self.assertEqual(
                manifest["origin"]["excludedParentSourceIds"],
                {"old-content": ["consumed-recording"]},
            )

    def test_can_exclude_exact_cross_split_media_from_older_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            older = self._snapshot(
                root, "older", label=TARGET_LABEL, base_class="reach_stacker",
                source_id="older-train", split="train",
            )
            older_manifest = json.loads(older.read_text(encoding="utf-8"))
            older_manifest["contentHash"] = "older-content"
            media_hash = older_manifest["samples"][0]["mediaSha256"]
            older.write_text(json.dumps(older_manifest), encoding="utf-8")
            locked = self._snapshot(
                root, "locked", label=TARGET_LABEL, base_class="reach_stacker",
                source_id="locked-test", split="test",
            )

            result = compose_snapshots(
                [older, locked],
                root / "output",
                excluded_media_hashes={"older-content": {media_hash}},
            )

            manifest = json.loads(Path(result["manifestPath"]).read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["samples"]), 1)
            self.assertEqual(
                manifest["origin"]["excludedMediaSha256"],
                {"older-content": [media_hash]},
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
