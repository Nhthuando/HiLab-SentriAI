"""Activate the reviewed BAI-KIEM V9 candidate with an audited owner override.

The automatic quality gate remains unchanged. This operator-only command records
the explicit override, preserves the current V8 environment fallback, and writes
a receipt that can restore the prior database activation state.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from db import close_db_pool, get_db_pool, init_db_pool


EXPECTED_CONFIRMATION = "ACTIVATE_BAIKIEM_V9_PRODUCTION"
V9_VERSION_KEY = "baikiem-v9-unified-candidate-final"
V9_CLASSES = ("person", "car", "truck", "forklift", "reach_stacker")
BACKEND_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = BACKEND_ROOT / "data"
DEFAULT_MODEL_DIR = DATA_ROOT / "training" / "models" / V9_VERSION_KEY
DEFAULT_DATASET_DIR = DATA_ROOT / "training" / "datasets" / "baikiem-v9-reviewed-final"
DEFAULT_RECEIPT_ROOT = DATA_ROOT / "training" / "activation-backups"
ENV_PATH = BACKEND_ROOT / ".env"


class ActivationInputError(ValueError):
    """Raised before any production state is changed."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ActivationInputError(f"Cannot read JSON input {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ActivationInputError(f"JSON input must be an object: {path}")
    return value


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def build_activation_metadata(
    evaluation: Mapping[str, Any],
    label_map: Mapping[str, str],
    *,
    artifact_sha256: str,
    dataset_content_hash: str,
    approved_at: str,
) -> dict[str, Any]:
    """Add an owner approval without rewriting failed automatic metrics."""
    result = deepcopy(dict(evaluation))
    result["runtimeMode"] = "UNIFIED"
    result["labelMap"] = dict(label_map)
    result["manualProductionApproval"] = {
        "approved": True,
        "approvedBy": "project-owner",
        "approvedAt": approved_at,
        "reason": "Owner accepted current V9 metrics for production video testing",
        "allowPartialUnified": True,
        "artifactSha256": artifact_sha256,
        "datasetContentHash": dataset_content_hash,
    }
    return result


def validate_activation_inputs(
    model_path: Path,
    labels_path: Path,
    evaluation_path: Path,
    manifest_path: Path,
    confirmation: str,
) -> dict[str, Any]:
    if confirmation != EXPECTED_CONFIRMATION:
        raise ActivationInputError(f"Confirmation must equal {EXPECTED_CONFIRMATION}")
    for path in (model_path, labels_path, evaluation_path, manifest_path):
        if not path.is_file():
            raise ActivationInputError(f"Activation input is missing: {path}")

    artifact_sha256 = _sha256(model_path)
    labels = _load_json(labels_path)
    evaluation = _load_json(evaluation_path)
    manifest = _load_json(manifest_path)
    if evaluation.get("runtimeMode") != "UNIFIED":
        raise ActivationInputError("V9 evaluation runtimeMode must be UNIFIED")
    if evaluation.get("artifactSha256") != artifact_sha256:
        raise ActivationInputError("V9 model SHA-256 differs from evaluation metadata")
    manifest_hash = manifest.get("contentHash")
    if not isinstance(manifest_hash, str) or len(manifest_hash) != 64:
        raise ActivationInputError("V9 dataset manifest has no valid content hash")
    if evaluation.get("datasetContentHash") != manifest_hash:
        raise ActivationInputError("V9 dataset hash differs between evaluation and manifest")
    manifest_classes = tuple(manifest.get("classes", ()))
    if manifest_classes != V9_CLASSES:
        raise ActivationInputError("V9 dataset class order is not the reviewed five-class contract")
    if any(labels.get(name) != name for name in V9_CLASSES):
        raise ActivationInputError("V9 labels must retain every canonical model-name mapping")
    quality_gate = evaluation.get("qualityGate")
    if not isinstance(quality_gate, dict) or quality_gate.get("passed") is not False:
        raise ActivationInputError("Manual activation expects the reviewed failed quality gate to remain explicit")
    return {
        "artifactSha256": artifact_sha256,
        "datasetContentHash": manifest_hash,
        "labels": labels,
        "evaluation": evaluation,
        "manifest": manifest,
    }


def _read_configured_v8(env_path: Path = ENV_PATH) -> dict[str, str]:
    wanted = {
        "CUSTOM_AUGMENT_ARTIFACT",
        "CUSTOM_AUGMENT_VERSION_KEY",
        "CUSTOM_AUGMENT_SHA256",
    }
    result: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in wanted:
            result[key] = value.strip().strip('"').strip("'")
    if set(result) != wanted:
        raise ActivationInputError("Current V8 environment identity is incomplete")
    configured_path = Path(result["CUSTOM_AUGMENT_ARTIFACT"])
    artifact = configured_path if configured_path.is_absolute() else DATA_ROOT / configured_path
    if not artifact.is_file() or _sha256(artifact) != result["CUSTOM_AUGMENT_SHA256"]:
        raise ActivationInputError("Current V8 rollback artifact is missing or has the wrong hash")
    result["resolvedArtifactPath"] = str(artifact.resolve())
    return result


def build_rollback_receipt(
    *,
    version_key: str,
    artifact_sha256: str,
    previous_active: Sequence[Mapping[str, Any]],
    configured_v8: Mapping[str, str],
    labels: Sequence[Mapping[str, Any]],
    receipt_path: Path,
) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "state": "PREPARED",
        "preparedAt": datetime.now(timezone.utc).isoformat(),
        "versionKey": version_key,
        "artifactSha256": artifact_sha256,
        "previousActiveModels": [dict(item) for item in previous_active],
        "configuredV8": dict(configured_v8),
        "labelsBefore": [dict(item) for item in labels],
        "createdRegistryLabel": None,
        "receiptPath": str(receipt_path.resolve()),
        "rollbackCommand": [
            "python",
            "-m",
            "training.activate_v9_production",
            "--rollback",
            str(receipt_path.resolve()),
        ],
    }


async def _database_snapshot(connection: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    active_rows = await connection.fetch(
        """
        SELECT id::text AS id, version_key AS "versionKey", status,
               artifact_path AS "artifactPath", artifact_sha256 AS "artifactSha256"
        FROM model_versions
        WHERE status = 'ACTIVE'
        ORDER BY activated_at DESC NULLS LAST
        """
    )
    labels = await connection.fetch(
        """
        SELECT id::text AS id, vietnamese_name AS "vietnameseName", base_class AS "baseClass"
        FROM object_labels
        ORDER BY vietnamese_name ASC
        """
    )
    return [dict(row) for row in active_rows], [dict(row) for row in labels]


async def activate(
    *,
    model_path: Path,
    labels_path: Path,
    evaluation_path: Path,
    manifest_path: Path,
    confirmation: str,
    receipt_root: Path = DEFAULT_RECEIPT_ROOT,
) -> dict[str, Any]:
    validated = validate_activation_inputs(
        model_path, labels_path, evaluation_path, manifest_path, confirmation,
    )
    configured_v8 = _read_configured_v8()
    approved_at = datetime.now(timezone.utc).isoformat()
    metadata = build_activation_metadata(
        validated["evaluation"],
        validated["labels"],
        artifact_sha256=validated["artifactSha256"],
        dataset_content_hash=validated["datasetContentHash"],
        approved_at=approved_at,
    )
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt_path = receipt_root / f"baikiem-v9-{timestamp}.json"

    await init_db_pool(min_size=1, max_size=2)
    try:
        pool = get_db_pool()
        async with pool.acquire() as connection:
            previous_active, labels_before = await _database_snapshot(connection)
            receipt = build_rollback_receipt(
                version_key=V9_VERSION_KEY,
                artifact_sha256=validated["artifactSha256"],
                previous_active=previous_active,
                configured_v8=configured_v8,
                labels=labels_before,
                receipt_path=receipt_path,
            )
            _atomic_json(receipt_path, receipt)

            dataset_id: uuid.UUID
            training_job_id: uuid.UUID
            model_version_id: uuid.UUID
            created_label: dict[str, str] | None = None
            async with connection.transaction():
                existing_dataset = await connection.fetchrow(
                    "SELECT id FROM training_datasets WHERE content_hash = $1",
                    validated["datasetContentHash"],
                )
                if existing_dataset:
                    dataset_id = existing_dataset["id"]
                else:
                    dataset_id = uuid.uuid4()
                    frames = validated["manifest"].get("frames", {})
                    sample_count = int(frames.get("train", 0)) + int(frames.get("val", 0))
                    sources = validated["manifest"].get("sources", {})
                    source_count = max(1, len(sources) if isinstance(sources, dict) else 1)
                    await connection.execute(
                        """
                        INSERT INTO training_datasets
                            (id, manifest_path, content_hash, sample_count, source_count, created_at)
                        VALUES ($1, $2, $3, $4, $5, NOW())
                        """,
                        dataset_id,
                        "data/training/datasets/baikiem-v9-reviewed-final/dataset-manifest.json",
                        validated["datasetContentHash"],
                        sample_count,
                        source_count,
                    )

                existing_model = await connection.fetchrow(
                    "SELECT id, training_job_id FROM model_versions WHERE version_key = $1",
                    V9_VERSION_KEY,
                )
                if existing_model:
                    model_version_id = existing_model["id"]
                    training_job_id = existing_model["training_job_id"]
                    await connection.execute(
                        """
                        UPDATE training_jobs
                        SET status = 'SUCCEEDED', current_epoch = 76, total_epochs = 120,
                            completed_at = COALESCE(completed_at, NOW()), failure_reason = NULL
                        WHERE id = $1
                        """,
                        training_job_id,
                    )
                else:
                    training_job_id = uuid.uuid4()
                    model_version_id = uuid.uuid4()
                    await connection.execute(
                        """
                        INSERT INTO training_jobs
                            (id, dataset_id, status, base_model, current_epoch, total_epochs,
                             requested_at, started_at, completed_at)
                        VALUES ($1, $2, 'SUCCEEDED', 'yolo11n.pt', 76, 120, NOW(), NOW(), NOW())
                        """,
                        training_job_id,
                        dataset_id,
                    )
                    await connection.execute(
                        """
                        INSERT INTO model_versions
                            (id, training_job_id, version_key, base_model, artifact_path,
                             artifact_sha256, status, evaluation_metrics, evaluated_at, created_at)
                        VALUES ($1, $2, $3, 'yolo11n.pt', $4, $5, 'CANDIDATE', $6, NOW(), NOW())
                        """,
                        model_version_id,
                        training_job_id,
                        V9_VERSION_KEY,
                        str(model_path.resolve()),
                        validated["artifactSha256"],
                        metadata,
                    )

                reach_label = await connection.fetchrow(
                    "SELECT id, base_class FROM object_labels WHERE vietnamese_name = $1",
                    "Xe nâng container",
                )
                if reach_label is None:
                    label_id = uuid.uuid4()
                    await connection.execute(
                        """
                        INSERT INTO object_labels
                            (id, vietnamese_name, base_class, created_at, updated_at)
                        VALUES ($1, $2, 'reach_stacker', NOW(), NOW())
                        """,
                        label_id,
                        "Xe nâng container",
                    )
                    created_label = {"id": str(label_id), "vietnameseName": "Xe nâng container"}
                elif reach_label["base_class"] != "reach_stacker":
                    raise ActivationInputError(
                        "Existing 'Xe nâng container' registry label is not mapped to reach_stacker"
                    )

                await connection.execute(
                    "UPDATE model_versions SET status = 'INACTIVE' WHERE status = 'ACTIVE' AND id <> $1",
                    model_version_id,
                )
                await connection.execute(
                    """
                    UPDATE model_versions
                    SET status = 'ACTIVE', artifact_path = $2, artifact_sha256 = $3,
                        evaluation_metrics = $4, evaluated_at = NOW(), activated_at = NOW()
                    WHERE id = $1
                    """,
                    model_version_id,
                    str(model_path.resolve()),
                    validated["artifactSha256"],
                    metadata,
                )

            receipt["state"] = "ACTIVE"
            receipt["activatedAt"] = datetime.now(timezone.utc).isoformat()
            receipt["trainingDatasetId"] = str(dataset_id)
            receipt["trainingJobId"] = str(training_job_id)
            receipt["modelVersionId"] = str(model_version_id)
            receipt["createdRegistryLabel"] = created_label
            receipt["evaluationQualityGatePassed"] = False
            receipt["manualProductionApproval"] = metadata["manualProductionApproval"]
            _atomic_json(receipt_path, receipt)
            return receipt
    finally:
        await close_db_pool()


async def rollback(receipt_path: Path, *, dry_run: bool) -> dict[str, Any]:
    receipt = _load_json(receipt_path)
    if receipt.get("schemaVersion") != 1 or receipt.get("state") != "ACTIVE":
        raise ActivationInputError("Rollback receipt is not an active V9 receipt")
    configured_v8 = receipt.get("configuredV8")
    if not isinstance(configured_v8, dict):
        raise ActivationInputError("Rollback receipt has no configured V8 identity")
    v8_path = Path(str(configured_v8.get("resolvedArtifactPath", "")))
    if not v8_path.is_file() or _sha256(v8_path) != configured_v8.get("CUSTOM_AUGMENT_SHA256"):
        raise ActivationInputError("V8 rollback artifact is unavailable or changed")

    await init_db_pool(min_size=1, max_size=2)
    try:
        pool = get_db_pool()
        async with pool.acquire() as connection:
            model_id = receipt.get("modelVersionId")
            row = await connection.fetchrow(
                "SELECT id::text AS id, status, artifact_sha256 FROM model_versions WHERE id = $1::uuid",
                model_id,
            )
            if row is None or row["artifact_sha256"] != receipt.get("artifactSha256"):
                raise ActivationInputError("Active V9 database record does not match rollback receipt")
            if dry_run:
                return {
                    "state": "DRY_RUN_OK",
                    "v9Status": row["status"],
                    "v8ArtifactPath": str(v8_path),
                    "previousActiveCount": len(receipt.get("previousActiveModels", [])),
                    "receiptPath": str(receipt_path.resolve()),
                }

            async with connection.transaction():
                await connection.execute(
                    "UPDATE model_versions SET status = 'INACTIVE' WHERE id = $1::uuid",
                    model_id,
                )
                previous_ids = [
                    str(item.get("id"))
                    for item in receipt.get("previousActiveModels", [])
                    if isinstance(item, dict) and item.get("id")
                ]
                if previous_ids:
                    await connection.execute(
                        "UPDATE model_versions SET status = 'ACTIVE', activated_at = NOW() WHERE id = ANY($1::uuid[])",
                        previous_ids,
                    )
                created_label = receipt.get("createdRegistryLabel")
                removed_label = False
                if isinstance(created_label, dict) and created_label.get("id"):
                    result = await connection.execute(
                        """
                        DELETE FROM object_labels label
                        WHERE label.id = $1::uuid
                          AND NOT EXISTS (SELECT 1 FROM label_samples sample WHERE sample.label_id = label.id)
                        """,
                        created_label["id"],
                    )
                    removed_label = result.endswith("1")

            receipt["state"] = "ROLLED_BACK"
            receipt["rolledBackAt"] = datetime.now(timezone.utc).isoformat()
            receipt["createdRegistryLabelRemoved"] = removed_label
            _atomic_json(receipt_path, receipt)
            return receipt
    finally:
        await close_db_pool()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--activate", action="store_true")
    action.add_argument("--rollback", type=Path)
    action.add_argument("--dry-run-rollback", type=Path)
    parser.add_argument("--confirmation", default="")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL_DIR / "best.pt")
    parser.add_argument("--labels", type=Path, default=DEFAULT_MODEL_DIR / "labels.json")
    parser.add_argument("--evaluation", type=Path, default=DEFAULT_MODEL_DIR / "evaluation.json")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_DATASET_DIR / "dataset-manifest.json")
    parser.add_argument("--receipt-root", type=Path, default=DEFAULT_RECEIPT_ROOT)
    args = parser.parse_args()
    if args.activate:
        result = asyncio.run(activate(
            model_path=args.model.resolve(),
            labels_path=args.labels.resolve(),
            evaluation_path=args.evaluation.resolve(),
            manifest_path=args.manifest.resolve(),
            confirmation=args.confirmation,
            receipt_root=args.receipt_root.resolve(),
        ))
    else:
        path = args.rollback or args.dry_run_rollback
        result = asyncio.run(rollback(path.resolve(), dry_run=args.dry_run_rollback is not None))
    # Keep the operator CLI reliable on Windows consoles configured with cp1258.
    # The receipt on disk remains UTF-8 and human-readable.
    print(json.dumps(result, ensure_ascii=True, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
