"""Evaluate reviewed golden frames; pending annotations always block acceptance."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

PYTHON_WORKER_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_WORKER_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_WORKER_ROOT))

from evaluation.golden_dataset import evaluatable_records, load_manifest
from evaluation.metrics import evaluate_detections


def _metric_gate(value: Any, *, operator: str, target: float, blocker: str) -> dict[str, Any]:
    if value is None:
        return {"status": "BLOCKED", "value": None, "operator": operator, "target": target, "reason": blocker}
    passed = value >= target if operator == ">=" else value < target
    return {
        "status": "PASS" if passed else "FAIL", "value": value,
        "operator": operator, "target": target, "reason": None,
    }


def _baseline_value(baseline: Mapping[str, Any] | None, *path: str) -> Any:
    value: Any = baseline
    for key in path:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value


def _acceptance(metrics: Mapping[str, Any], baseline: Mapping[str, Any] | None) -> dict[str, Any]:
    reach = metrics.get("perClass", {}).get("reach_stacker", {})
    confusion = metrics.get("truckReachStackerConfusion", {})
    current_false_alerts = _baseline_value(metrics, "falseAlerts", "perMinute", "value")
    baseline_false_alerts = _baseline_value(baseline, "metrics", "falseAlerts", "perMinute", "value")
    current_far = _baseline_value(metrics, "farObjectRecall", "value")
    baseline_far = _baseline_value(baseline, "metrics", "farObjectRecall", "value")
    gates = {
        "reachStackerPrecision": _metric_gate(
            _baseline_value(reach, "precision", "value"), operator=">=", target=0.90,
            blocker="reach_stacker precision is undefined",
        ),
        "reachStackerRecall": _metric_gate(
            _baseline_value(reach, "recall", "value"), operator=">=", target=0.85,
            blocker="reach_stacker recall is undefined",
        ),
        "truckAsReachStackerRate": _metric_gate(
            _baseline_value(confusion, "truckAsReachStackerRate", "value"), operator="<", target=0.05,
            blocker="truck ground truth is unavailable",
        ),
    }
    if current_false_alerts is None or baseline_false_alerts is None:
        gates["falseAlertsPerMinuteImproved"] = {
            "status": "BLOCKED", "value": current_false_alerts, "operator": "<",
            "target": baseline_false_alerts,
            "reason": "current complete-review rate and baseline rate are both required",
        }
    else:
        gates["falseAlertsPerMinuteImproved"] = _metric_gate(
            current_false_alerts, operator="<", target=float(baseline_false_alerts), blocker="",
        )
    if current_far is None or baseline_far is None:
        gates["farObjectRecallImproved"] = {
            "status": "BLOCKED", "value": current_far, "operator": ">",
            "target": baseline_far, "reason": "current far-object recall and baseline recall are both required",
        }
    else:
        gates["farObjectRecallImproved"] = {
            "status": "PASS" if current_far > baseline_far else "FAIL",
            "value": current_far, "operator": ">", "target": baseline_far, "reason": None,
        }
    statuses = {gate["status"] for gate in gates.values()}
    overall = "FAIL" if "FAIL" in statuses else "BLOCKED" if "BLOCKED" in statuses else "PASS"
    return {"status": overall, "gates": gates}


def _read_jsonl(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, 1):
            if not raw.strip():
                continue
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number} must contain a JSON object")
            records.append(value)
    return records


def _class_map(path: Path) -> dict[int, str]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("class map must be an object keyed by integer class ID")
    result: dict[int, str] = {}
    for raw_id, raw_class in value.items():
        try:
            class_id = int(raw_id)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid class ID: {raw_id!r}") from exc
        if class_id < 0 or not isinstance(raw_class, str) or not raw_class:
            raise ValueError(f"invalid class mapping: {raw_id!r} -> {raw_class!r}")
        result[class_id] = raw_class
    return result


def _ground_truth(root: Path, records: Sequence[Mapping[str, Any]], classes: Mapping[int, str]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        frame_id = str(record["frameId"])
        if record["annotationStatus"] == "NEGATIVE":
            result[frame_id] = []
            continue
        labels_path = root / str(record["labelsPath"])
        items: list[dict[str, Any]] = []
        with labels_path.open("r", encoding="utf-8") as handle:
            for line_number, raw in enumerate(handle, 1):
                parts = raw.split()
                if len(parts) != 5:
                    raise ValueError(f"{labels_path}:{line_number} must have five YOLO fields")
                class_id = int(parts[0])
                if class_id not in classes:
                    raise ValueError(f"{labels_path}:{line_number} uses unmapped class ID {class_id}")
                center_x, center_y, width, height = (float(value) for value in parts[1:])
                bbox = [center_x - width / 2, center_y - height / 2, center_x + width / 2, center_y + height / 2]
                items.append({"class": classes[class_id], "bbox": bbox, "tags": list(record.get("tags") or [])})
        result[frame_id] = items
    return result


def _predictions(records: Sequence[Mapping[str, Any]], allowed_frames: set[str]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {frame_id: [] for frame_id in allowed_frames}
    seen: set[str] = set()
    for record in records:
        frame_id = record.get("frameId")
        detections = record.get("detections")
        if not isinstance(frame_id, str) or frame_id not in allowed_frames:
            continue
        if frame_id in seen:
            raise ValueError(f"prediction JSONL has duplicate frameId {frame_id}")
        if not isinstance(detections, list):
            raise ValueError(f"predictions for {frame_id} must be an array")
        result[frame_id] = [dict(item) for item in detections if isinstance(item, dict)]
        seen.add(frame_id)
    return result


def render_markdown(report: Mapping[str, Any]) -> str:
    status = report["status"]
    lines = [
        "# BAI-KIEM Golden Evaluation",
        "",
        f"**Status: {status}**",
        "",
        f"- Total candidate frames: {report['frameCounts']['total']}",
        f"- Pending: {report['frameCounts']['pending']}",
        f"- Annotated: {report['frameCounts']['annotated']}",
        f"- Negative: {report['frameCounts']['negative']}",
        f"- Evaluatable: {report['frameCounts']['evaluatable']}",
        f"- Evaluation split: `{report['split']}`",
        "",
    ]
    if report.get("blockers"):
        lines.extend(["## Blockers", ""] + [f"- {reason}" for reason in report["blockers"]] + [""])
    metrics = report.get("metrics")
    if metrics:
        lines.extend([
            "## Reviewed-subset metrics",
            "",
            f"- Precision: `{metrics['precision']['value']}`",
            f"- Recall: `{metrics['recall']['value']}`",
            f"- F1: `{metrics['f1']['value']}`",
            f"- Small-object recall: `{metrics['smallObjectRecall']['value']}`",
            f"- Far-object recall: `{metrics['farObjectRecall']['value']}`",
            "",
            "These values cover reviewed records only and do not clear the acceptance gate while any frame remains PENDING.",
            "",
        ])
    else:
        lines.extend([
            "## Class accuracy",
            "",
            "Precision, recall, AP50, small/far recall, truck/reach-stacker confusion, static-container false detections, and false alerts per minute are **BLOCKED/NOT EVALUATED**. No reviewed ground truth exists.",
            "",
        ])
    acceptance = report.get("acceptance")
    if acceptance:
        lines.extend(["## Acceptance gates", "", f"**Overall: {acceptance['status']}**", ""])
        for name, gate in acceptance["gates"].items():
            reason = f" — {gate['reason']}" if gate.get("reason") else ""
            lines.append(
                f"- `{name}`: **{gate['status']}**; value=`{gate.get('value')}`, "
                f"required `{gate.get('operator')} {gate.get('target')}`{reason}"
            )
        lines.append("")
    return "\n".join(lines)


def run(
    manifest_path: Path,
    *,
    class_map_path: Path | None = None,
    predictions_path: Path | None = None,
    events_path: Path | None = None,
    split: str = "test",
    baseline_path: Path | None = None,
    events_review_complete: bool = False,
    reviewed_event_duration_minutes: float | None = None,
) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    all_frames = manifest["frames"]
    frames = [record for record in all_frames if record.get("split") == split]
    reviewed = [record for record in evaluatable_records(manifest) if record.get("split") == split]
    counts = {
        "total": len(frames),
        "pending": sum(record["annotationStatus"] == "PENDING" for record in frames),
        "annotated": sum(record["annotationStatus"] == "ANNOTATED" for record in frames),
        "negative": sum(record["annotationStatus"] == "NEGATIVE" for record in frames),
        "evaluatable": len(reviewed),
    }
    blockers: list[str] = []
    if not frames:
        blockers.append(f"manifest has no frames in split {split!r}")
    if counts["pending"]:
        blockers.append(f"annotationStatus contains {counts['pending']} PENDING frame(s)")
    metrics = None
    if reviewed:
        if class_map_path is None or predictions_path is None:
            blockers.append("reviewed frames require --class-map and --predictions")
        else:
            truths = _ground_truth(manifest_path.parent, reviewed, _class_map(class_map_path))
            prediction_records = _read_jsonl(predictions_path)
            predictions = _predictions(prediction_records, set(truths))
            tags = {str(record["frameId"]): record["tags"] for record in reviewed}
            events = _read_jsonl(events_path)
            duration_minutes = float(manifest["source"].get("durationMs", 0)) / 60_000.0
            metrics = evaluate_detections(
                truths, predictions, frame_tags=tags, events=events,
                video_duration_minutes=duration_minutes if duration_minutes > 0 else None,
                events_review_complete=events_review_complete,
                reviewed_event_duration_minutes=reviewed_event_duration_minutes,
            )
    baseline = None
    if baseline_path is not None:
        loaded_baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        if not isinstance(loaded_baseline, dict):
            raise ValueError("baseline report must contain a JSON object")
        baseline = loaded_baseline
    # Emit every acceptance threshold even when annotations are pending so the
    # machine-readable report says BLOCKED rather than silently omitting gates.
    acceptance = _acceptance(metrics or {}, baseline)
    status = "BLOCKED" if blockers or not reviewed else acceptance["status"]
    if not reviewed and not blockers:
        blockers.append("manifest has no ANNOTATED or NEGATIVE frames")
    return {
        "schemaVersion": 1,
        "datasetId": manifest["datasetId"],
        "status": status,
        "split": split,
        "manifestFrameCount": len(all_frames),
        "frameCounts": counts,
        "blockers": blockers,
        "metrics": metrics,
        "acceptance": acceptance,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--class-map", type=Path)
    parser.add_argument("--predictions", type=Path)
    parser.add_argument("--events", type=Path)
    parser.add_argument("--split", default="test")
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--events-review-complete", action="store_true")
    parser.add_argument("--reviewed-event-duration-minutes", type=float)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    args = parser.parse_args(argv)
    report = run(
        args.manifest, class_map_path=args.class_map, predictions_path=args.predictions,
        events_path=args.events, split=args.split, baseline_path=args.baseline,
        events_review_complete=args.events_review_complete,
        reviewed_event_duration_minutes=args.reviewed_event_duration_minutes,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.output_markdown.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"status": report["status"], **report["frameCounts"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
