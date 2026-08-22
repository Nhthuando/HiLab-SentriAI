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

from .dataset_exporter import materialize
from .runner import _emit, _evaluation, _quality_gate, _sha256, _write_runner_report


def finalize_checkpoint(manifest_path: str, output_root: str, job_id: str) -> dict[str, Any]:
    """Run independent hold-out evaluation for ``best.pt`` and save a report."""
    output = Path(output_root).resolve()
    manifest = Path(manifest_path).resolve()
    run_checkpoint = output / "runs" / job_id / "weights" / "best.pt"
    if not run_checkpoint.is_file():
        raise FileNotFoundError(f"Best checkpoint does not exist: {run_checkpoint}")

    snapshot: dict[str, Any] = json.loads(manifest.read_text(encoding="utf-8"))
    labels = sorted({str(sample["label"]) for sample in snapshot["samples"]})
    label_map = {str(sample["label"]): str(sample["baseClass"]) for sample in snapshot["samples"]}
    test_count = sum(1 for sample in snapshot["samples"] if sample["split"] == "test")
    val_count = sum(1 for sample in snapshot["samples"] if sample["split"] == "val")
    if not test_count and not val_count:
        raise ValueError("Dataset needs a validation or independent test split")

    dataset = materialize(manifest, output / "datasets")
    evaluation_split = "test" if test_count else "val"
    _emit("evaluating", split=evaluation_split, source="saved_best_checkpoint")
    validation = YOLO(str(run_checkpoint)).val(
        data=str(dataset / "data.yaml"),
        split=evaluation_split,
        device=0,
        workers=0,
        verbose=False,
    )
    metrics = _evaluation(validation, labels)
    metrics["evaluationSplit"] = evaluation_split
    metrics["evaluationSource"] = "saved_best_checkpoint"
    accepted, failures = _quality_gate(metrics)
    metrics["qualityGate"] = {"passed": accepted, "failures": failures}

    artifact_dir = output / "models" / job_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact = artifact_dir / "best.pt"
    shutil.copy2(run_checkpoint, artifact)
    (artifact_dir / "labels.json").write_text(json.dumps(label_map, ensure_ascii=False, indent=2), encoding="utf-8")
    (artifact_dir / "evaluation.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    report = {
        "outcome": "completed",
        "artifactPath": artifact.relative_to(output.parents[0]).as_posix(),
        "artifactSha256": _sha256(artifact),
        "metrics": metrics,
        "labelMap": label_map,
        "accepted": accepted,
    }
    _write_runner_report(output, job_id, report)
    _emit("completed", **report)
    return report


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit("usage: finalize_checkpoint.py <manifest> <output-root> <job-id>")
    result = finalize_checkpoint(sys.argv[1], sys.argv[2], sys.argv[3])
    _emit("result", **result)
