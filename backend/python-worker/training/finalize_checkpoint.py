"""Evaluate a saved best checkpoint and publish it as a safe candidate.

This is used when an operator stops a sufficiently good GPU training run before
its configured epoch budget.  It never resumes training and never changes the
base monitoring model.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

from ultralytics import YOLO

from evaluation.metrics import unified_acceptance_gate
from .runner import (
    _emit,
    _evaluation,
    _quality_gate,
    _sha256,
    _training_dataset_contract,
    _write_runner_report,
)


def finalize_checkpoint(
    manifest_path: str,
    output_root: str,
    job_id: str,
    acceptance_report_path: str | None = None,
) -> dict[str, Any]:
    """Run independent hold-out evaluation for ``best.pt`` and save a report."""
    output = Path(output_root).resolve()
    manifest = Path(manifest_path).resolve()
    run_checkpoint = output / "runs" / job_id / "weights" / "best.pt"
    if not run_checkpoint.is_file():
        raise FileNotFoundError(f"Best checkpoint does not exist: {run_checkpoint}")

    contract = _training_dataset_contract(manifest, output)
    labels = list(contract["labels"])
    label_map = dict(contract["labelMap"])
    runtime_mode = str(contract["runtimeMode"])
    test_count = contract["counts"]["test"]
    val_count = contract["counts"]["val"]
    if not test_count and not val_count:
        raise ValueError("Dataset needs a validation or independent test split")

    dataset = Path(contract["dataset"])
    evaluation_split = "test" if test_count else "val"
    _emit("evaluating", split=evaluation_split, source="saved_best_checkpoint")
    validation = YOLO(str(run_checkpoint)).val(
        data=str(dataset / "data.yaml"),
        split=evaluation_split,
        device=0,
        workers=0,
        verbose=False,
    )
    metrics = _evaluation(validation, labels, runtime_mode)
    metrics["evaluationSplit"] = evaluation_split
    metrics["evaluationSource"] = "saved_best_checkpoint"
    profile = contract["profile"]
    required_classes = list(contract["validationClasses"])
    validation_accepted, validation_failures = _quality_gate(metrics, required_classes, runtime_mode)
    accepted = validation_accepted
    failures = list(validation_failures)
    metrics["validationGate"] = {"passed": validation_accepted, "failures": validation_failures}
    metrics["qualityGate"] = {"passed": accepted, "failures": failures}
    metrics["trainingProfile"] = profile
    metrics["datasetContentHash"] = contract["datasetContentHash"]
    metrics["sourceSplits"] = contract["sourceSplits"]
    artifact_dir = output / "models" / job_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact = artifact_dir / "best.pt"
    shutil.copy2(run_checkpoint, artifact)
    artifact_sha256 = _sha256(artifact)
    if runtime_mode == "UNIFIED":
        if acceptance_report_path:
            acceptance_report = json.loads(Path(acceptance_report_path).read_text(encoding="utf-8"))
            if not isinstance(acceptance_report, dict):
                raise ValueError("Unified acceptance report must be a JSON object")
            activation_gate = unified_acceptance_gate(
                acceptance_report,
                expected_dataset_hash=str(contract["datasetContentHash"]),
                expected_artifact_hash=artifact_sha256,
            )
            accepted = validation_accepted and bool(activation_gate["passed"])
            failures = [*validation_failures, *activation_gate["failures"]]
            metrics["activationGate"] = activation_gate
        else:
            accepted = False
            failures = [*validation_failures, "locked video continuity/FPS gate is pending"]
            metrics["activationGate"] = {"passed": False, "reason": "PENDING_LOCKED_VIDEO_GATE"}
        metrics["qualityGate"] = {"passed": accepted, "failures": failures}
    (artifact_dir / "labels.json").write_text(json.dumps(label_map, ensure_ascii=False, indent=2), encoding="utf-8")
    (artifact_dir / "evaluation.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    report = {
        "outcome": "completed",
        "artifactPath": artifact.relative_to(output.parents[0]).as_posix(),
        "artifactSha256": artifact_sha256,
        "metrics": metrics,
        "labelMap": label_map,
        "accepted": accepted,
    }
    _write_runner_report(output, job_id, report)
    _emit("completed", **report)
    return report


if __name__ == "__main__":
    if len(sys.argv) not in {4, 5}:
        raise SystemExit("usage: finalize_checkpoint.py <manifest> <output-root> <job-id> [acceptance-report]")
    result = finalize_checkpoint(
        sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) == 5 else None,
    )
    _emit("result", **result)
