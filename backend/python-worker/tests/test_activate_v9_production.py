from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from training.activate_v9_production import (
    EXPECTED_CONFIRMATION,
    ActivationInputError,
    build_activation_metadata,
    build_rollback_receipt,
    validate_activation_inputs,
)


class ActivateV9ProductionTests(unittest.TestCase):
    def test_metadata_preserves_failed_gate_and_records_exact_owner_override(self) -> None:
        evaluation = {
            "runtimeMode": "UNIFIED",
            "qualityGate": {"passed": False, "failures": ["precision"]},
            "validation": {"precision": 0.73},
        }
        original = deepcopy(evaluation)
        result = build_activation_metadata(
            evaluation,
            {"person": "person", "reach_stacker": "reach_stacker"},
            artifact_sha256="a" * 64,
            dataset_content_hash="b" * 64,
            approved_at="2026-08-26T10:00:00+00:00",
        )

        self.assertEqual(evaluation, original)
        self.assertFalse(result["qualityGate"]["passed"])
        self.assertEqual(result["labelMap"]["person"], "person")
        self.assertEqual(result["manualProductionApproval"], {
            "approved": True,
            "approvedBy": "project-owner",
            "approvedAt": "2026-08-26T10:00:00+00:00",
            "reason": "Owner accepted current V9 metrics for production video testing",
            "allowPartialUnified": True,
            "artifactSha256": "a" * 64,
            "datasetContentHash": "b" * 64,
        })

    def test_input_validation_requires_confirmation_hash_and_five_classes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "best.pt"
            labels = root / "labels.json"
            evaluation = root / "evaluation.json"
            manifest = root / "dataset-manifest.json"
            model.write_bytes(b"v9-model")
            model_hash = hashlib.sha256(b"v9-model").hexdigest()
            labels.write_text(json.dumps({
                "person": "person",
                "car": "car",
                "truck": "truck",
                "forklift": "forklift",
                "reach_stacker": "reach_stacker",
            }), encoding="utf-8")
            evaluation.write_text(json.dumps({
                "runtimeMode": "UNIFIED",
                "artifactSha256": model_hash,
                "datasetContentHash": "b" * 64,
                "qualityGate": {"passed": False},
            }), encoding="utf-8")
            manifest.write_text(json.dumps({
                "contentHash": "b" * 64,
                "classes": ["person", "car", "truck", "forklift", "reach_stacker"],
                "frames": {"train": 10, "val": 2},
            }), encoding="utf-8")

            with self.assertRaises(ActivationInputError):
                validate_activation_inputs(model, labels, evaluation, manifest, "wrong")
            validated = validate_activation_inputs(
                model, labels, evaluation, manifest, EXPECTED_CONFIRMATION,
            )
            self.assertEqual(validated["artifactSha256"], model_hash)
            self.assertEqual(validated["datasetContentHash"], "b" * 64)

            model.write_bytes(b"changed")
            with self.assertRaises(ActivationInputError):
                validate_activation_inputs(
                    model, labels, evaluation, manifest, EXPECTED_CONFIRMATION,
                )

    def test_rollback_receipt_keeps_prior_active_and_v8_identity(self) -> None:
        receipt = build_rollback_receipt(
            version_key="baikiem-v9",
            artifact_sha256="a" * 64,
            previous_active=[{"id": "old-model", "versionKey": "old"}],
            configured_v8={
                "CUSTOM_AUGMENT_ARTIFACT": "training/models/v8/best.pt",
                "CUSTOM_AUGMENT_VERSION_KEY": "v8",
                "CUSTOM_AUGMENT_SHA256": "c" * 64,
            },
            labels=[{"id": "label-1", "vietnameseName": "Xe tải", "baseClass": "truck"}],
            receipt_path=Path("receipt.json"),
        )
        self.assertEqual(receipt["state"], "PREPARED")
        self.assertEqual(receipt["previousActiveModels"][0]["id"], "old-model")
        self.assertEqual(receipt["configuredV8"]["CUSTOM_AUGMENT_VERSION_KEY"], "v8")
        self.assertEqual(receipt["labelsBefore"][0]["baseClass"], "truck")
        self.assertEqual(receipt["rollbackCommand"][0:3], ["python", "-m", "training.activate_v9_production"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
