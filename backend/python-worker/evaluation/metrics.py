"""Deterministic detection and false-alert metrics for reviewed golden frames."""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Iterable, Mapping, Sequence


TRUCK_CLASS = "truck"
REACH_STACKER_CLASS = "reach_stacker"
VEHICLE_CLASSES = frozenset({
    "bicycle", "car", "motorcycle", "bus", "truck", "reach_stacker",
    "container_truck", "forklift", "mobile_crane",
})


def iou(first: Sequence[float], second: Sequence[float]) -> float:
    if len(first) != 4 or len(second) != 4:
        raise ValueError("bbox must have four coordinates")
    ax1, ay1, ax2, ay2 = (float(value) for value in first)
    bx1, by1, bx2, by2 = (float(value) for value in second)
    intersection = max(0.0, min(ax2, bx2) - max(ax1, bx1)) * max(0.0, min(ay2, by2) - max(ay1, by1))
    if intersection <= 0:
        return 0.0
    first_area = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    second_area = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = first_area + second_area - intersection
    return intersection / union if union > 0 else 0.0


def _ratio(numerator: int, denominator: int, reason: str) -> dict[str, Any]:
    if denominator == 0:
        return {"value": None, "reason": reason}
    return {"value": round(numerator / denominator, 6), "reason": None}


def _f1(precision: dict[str, Any], recall: dict[str, Any]) -> dict[str, Any]:
    if precision["value"] is None or recall["value"] is None:
        return {"value": None, "reason": "precision or recall is undefined"}
    denominator = precision["value"] + recall["value"]
    if denominator == 0:
        return {"value": None, "reason": "precision and recall are both zero"}
    return {"value": round(2 * precision["value"] * recall["value"] / denominator, 6), "reason": None}


def _validate_box(item: Mapping[str, Any]) -> tuple[float, float, float, float]:
    bbox = item.get("bbox")
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        raise ValueError("every item requires bbox=[x1,y1,x2,y2]")
    values = tuple(float(value) for value in bbox)
    if not all(0 <= value <= 1 for value in values) or values[2] <= values[0] or values[3] <= values[1]:
        raise ValueError("bbox must be normalized and have positive area")
    return values


def _average_precision(
    class_name: str,
    ground_truth: Mapping[str, list[Mapping[str, Any]]],
    predictions: Mapping[str, list[Mapping[str, Any]]],
    iou_threshold: float,
) -> dict[str, Any]:
    class_ground_truth = {
        frame_id: [item for item in items if item.get("class") == class_name]
        for frame_id, items in ground_truth.items()
    }
    positive_count = sum(len(items) for items in class_ground_truth.values())
    if positive_count == 0:
        return {"value": None, "reason": "no ground-truth positives"}
    ranked = sorted(
        (
            (float(item.get("confidence", 0.0)), frame_id, item)
            for frame_id, items in predictions.items()
            for item in items
            if item.get("class") == class_name
        ),
        key=lambda entry: (-entry[0], entry[1]),
    )
    matched: dict[str, set[int]] = defaultdict(set)
    tp_flags: list[int] = []
    fp_flags: list[int] = []
    for _confidence, frame_id, prediction in ranked:
        best_index = None
        best_overlap = iou_threshold
        prediction_box = _validate_box(prediction)
        for index, truth in enumerate(class_ground_truth.get(frame_id, [])):
            if index in matched[frame_id]:
                continue
            overlap = iou(prediction_box, _validate_box(truth))
            if overlap >= best_overlap:
                best_overlap = overlap
                best_index = index
        if best_index is None:
            tp_flags.append(0)
            fp_flags.append(1)
        else:
            matched[frame_id].add(best_index)
            tp_flags.append(1)
            fp_flags.append(0)
    if not ranked:
        return {"value": 0.0, "reason": None}
    cumulative_tp = 0
    cumulative_fp = 0
    points: list[tuple[float, float]] = []
    for tp_flag, fp_flag in zip(tp_flags, fp_flags):
        cumulative_tp += tp_flag
        cumulative_fp += fp_flag
        points.append((cumulative_tp / positive_count, cumulative_tp / (cumulative_tp + cumulative_fp)))
    average = 0.0
    for recall_level in (index / 100 for index in range(101)):
        precision_at_recall = max((precision for recall, precision in points if recall >= recall_level), default=0.0)
        average += precision_at_recall / 101.0
    return {"value": round(average, 6), "reason": None}


def _source_name(item: Mapping[str, Any]) -> str:
    raw = str(item.get("source") or "UNSPECIFIED").strip().casefold()
    if raw in {"coco", "base"}:
        return "base"
    if raw == "custom":
        return "custom"
    return "unspecified"


def _group_counts(
    class_name: str,
    source: str,
    ground_truth: Mapping[str, list[Mapping[str, Any]]],
    predictions: Mapping[str, list[Mapping[str, Any]]],
    *,
    iou_threshold: float,
    initiation_threshold: float,
    continuation_threshold: float | None = None,
) -> dict[str, int]:
    """Match one class/source at a proposed runtime threshold pair.

    A continuation-only hit is eligible solely when the production detector
    explicitly records ``canContinue=true``. This uses the same confirmed-track
    signal consumed by the Area state machine and prevents a calibration sweep
    from pretending that an arbitrary low-confidence observation can initiate.
    """
    tp = fp = fn = 0
    for frame_id in sorted(set(ground_truth) | set(predictions)):
        truths = [item for item in ground_truth.get(frame_id, []) if item.get("class") == class_name]
        candidates = []
        for item in predictions.get(frame_id, []):
            if item.get("class") != class_name or _source_name(item) != source:
                continue
            confidence = float(item.get("confidence", 0.0))
            eligible = confidence >= initiation_threshold
            if continuation_threshold is not None:
                eligible = eligible or (
                    item.get("canContinue") is True and confidence >= continuation_threshold
                )
            if eligible:
                candidates.append(item)
        candidates.sort(key=lambda item: -float(item.get("confidence", 0.0)))
        matched_truth: set[int] = set()
        for prediction in candidates:
            prediction_box = _validate_box(prediction)
            best_index = None
            best_overlap = iou_threshold
            for truth_index, truth in enumerate(truths):
                if truth_index in matched_truth:
                    continue
                overlap = iou(prediction_box, _validate_box(truth))
                if overlap >= best_overlap:
                    best_overlap = overlap
                    best_index = truth_index
            if best_index is None:
                fp += 1
            else:
                matched_truth.add(best_index)
                tp += 1
        fn += len(truths) - len(matched_truth)
    return {"tp": tp, "fp": fp, "fn": fn}


def threshold_calibration(
    ground_truth: Mapping[str, list[Mapping[str, Any]]],
    predictions: Mapping[str, list[Mapping[str, Any]]],
    *,
    iou_threshold: float = 0.50,
) -> dict[str, Any]:
    """Return reproducible PR points and per-class/source policy sweeps."""
    groups = sorted({
        (str(item.get("class")), _source_name(item))
        for items in predictions.values()
        for item in items
    })
    output: list[dict[str, Any]] = []
    grids = {
        "base": ([0.25, 0.30, 0.35], [0.10, 0.14, 0.15]),
        "custom": ([0.30, 0.35, 0.40, 0.45], [0.15, 0.20, 0.25]),
        "unspecified": ([0.30], [0.14]),
    }
    for class_name, source in groups:
        confidences = sorted({
            float(item.get("confidence", 0.0))
            for items in predictions.values()
            for item in items
            if item.get("class") == class_name and _source_name(item) == source
        }, reverse=True)
        pr_points: list[dict[str, Any]] = []
        for threshold in confidences:
            counts = _group_counts(
                class_name, source, ground_truth, predictions,
                iou_threshold=iou_threshold, initiation_threshold=threshold,
            )
            precision = _ratio(counts["tp"], counts["tp"] + counts["fp"], "no predictions")
            recall = _ratio(counts["tp"], counts["tp"] + counts["fn"], "no ground-truth positives")
            pr_points.append({"threshold": threshold, **counts, "precision": precision, "recall": recall})

        initiation_values, continuation_values = grids[source]
        sweep: list[dict[str, Any]] = []
        for initiation in initiation_values:
            for continuation in continuation_values:
                if continuation > initiation:
                    continue
                counts = _group_counts(
                    class_name, source, ground_truth, predictions,
                    iou_threshold=iou_threshold,
                    initiation_threshold=initiation,
                    continuation_threshold=continuation,
                )
                precision = _ratio(counts["tp"], counts["tp"] + counts["fp"], "no predictions")
                recall = _ratio(counts["tp"], counts["tp"] + counts["fn"], "no ground-truth positives")
                sweep.append({
                    "initiation": initiation,
                    "continuation": continuation,
                    **counts,
                    "precision": precision,
                    "recall": recall,
                    "f1": _f1(precision, recall),
                })
        output.append({"class": class_name, "source": source, "prPoints": pr_points, "thresholdSweep": sweep})
    return {
        "policy": "continuation below initiation requires production canContinue=true",
        "groups": output,
    }


def evaluate_detections(
    ground_truth: Mapping[str, list[Mapping[str, Any]]],
    predictions: Mapping[str, list[Mapping[str, Any]]],
    *,
    frame_tags: Mapping[str, Iterable[str]] | None = None,
    events: Sequence[Mapping[str, Any]] = (),
    video_duration_minutes: float | None = None,
    events_review_complete: bool = False,
    reviewed_event_duration_minutes: float | None = None,
    iou_threshold: float = 0.50,
    include_threshold_calibration: bool = True,
) -> dict[str, Any]:
    if not 0 < iou_threshold <= 1:
        raise ValueError("iou_threshold must be in (0,1]")
    tags_by_frame = {frame_id: set(tags) for frame_id, tags in (frame_tags or {}).items()}
    classes = sorted({str(item.get("class")) for items in ground_truth.values() for item in items} | {str(item.get("class")) for items in predictions.values() for item in items})
    counters = {name: {"tp": 0, "fp": 0, "fn": 0} for name in classes}
    small_tp = small_total = far_tp = far_total = 0
    confusion = {"reachStackerAsTruck": 0, "truckAsReachStacker": 0}

    all_frames = sorted(set(ground_truth) | set(predictions))
    for frame_id in all_frames:
        truths = list(ground_truth.get(frame_id, []))
        predicted = sorted(predictions.get(frame_id, []), key=lambda item: -float(item.get("confidence", 0.0)))
        matched_truth: set[int] = set()
        matched_prediction: set[int] = set()
        for prediction_index, prediction in enumerate(predicted):
            predicted_class = str(prediction.get("class"))
            prediction_box = _validate_box(prediction)
            best_index = None
            best_overlap = iou_threshold
            for truth_index, truth in enumerate(truths):
                if truth_index in matched_truth or truth.get("class") != predicted_class:
                    continue
                overlap = iou(prediction_box, _validate_box(truth))
                if overlap >= best_overlap:
                    best_overlap = overlap
                    best_index = truth_index
            if best_index is not None:
                matched_truth.add(best_index)
                matched_prediction.add(prediction_index)
                counters[predicted_class]["tp"] += 1

        for prediction_index, prediction in enumerate(predicted):
            if prediction_index not in matched_prediction:
                counters[str(prediction.get("class"))]["fp"] += 1
        for truth_index, truth in enumerate(truths):
            truth_class = str(truth.get("class"))
            if truth_index not in matched_truth:
                counters[truth_class]["fn"] += 1
            box = _validate_box(truth)
            area = (box[2] - box[0]) * (box[3] - box[1])
            if area < 0.01:
                small_total += 1
                small_tp += int(truth_index in matched_truth)
            truth_tags = set(truth.get("tags") or ()) | tags_by_frame.get(frame_id, set())
            if "far" in truth_tags:
                far_total += 1
                far_tp += int(truth_index in matched_truth)

        for truth in truths:
            truth_class = str(truth.get("class"))
            if truth_class not in {TRUCK_CLASS, REACH_STACKER_CLASS}:
                continue
            truth_box = _validate_box(truth)
            opposite = REACH_STACKER_CLASS if truth_class == TRUCK_CLASS else TRUCK_CLASS
            if any(prediction.get("class") == opposite and iou(truth_box, _validate_box(prediction)) >= iou_threshold for prediction in predicted):
                key = "truckAsReachStacker" if truth_class == TRUCK_CLASS else "reachStackerAsTruck"
                confusion[key] += 1

    per_class: dict[str, Any] = {}
    totals = {"tp": 0, "fp": 0, "fn": 0}
    for class_name in classes:
        counts = counters[class_name]
        for key in totals:
            totals[key] += counts[key]
        precision = _ratio(counts["tp"], counts["tp"] + counts["fp"], "no predictions")
        recall = _ratio(counts["tp"], counts["tp"] + counts["fn"], "no ground-truth positives")
        per_class[class_name] = {
            **counts,
            "precision": precision,
            "recall": recall,
            "f1": _f1(precision, recall),
            "ap50": _average_precision(class_name, ground_truth, predictions, iou_threshold),
        }
    aggregate_precision = _ratio(totals["tp"], totals["tp"] + totals["fp"], "no predictions")
    aggregate_recall = _ratio(totals["tp"], totals["tp"] + totals["fn"], "no ground-truth positives")

    static_frames = {frame_id for frame_id, tags in tags_by_frame.items() if "static-container-only" in tags}
    static_false_predictions = sum(
        1 for frame_id in static_frames for item in predictions.get(frame_id, []) if item.get("class") in VEHICLE_CLASSES
    )
    reviewed_false_alerts = [event for event in events if isinstance(event.get("isFalseAlert"), bool)]
    false_alert_count = sum(1 for event in reviewed_false_alerts if event["isFalseAlert"])
    all_events_reviewed = len(reviewed_false_alerts) == len(events)
    if not all_events_reviewed:
        false_alert_rate = {"value": None, "reason": "one or more events lack reviewed isFalseAlert labels"}
        rate_denominator = None
    elif reviewed_event_duration_minutes is not None:
        if reviewed_event_duration_minutes <= 0:
            false_alert_rate = {"value": None, "reason": "reviewed event duration must be positive"}
            rate_denominator = None
        else:
            rate_denominator = float(reviewed_event_duration_minutes)
            false_alert_rate = {"value": round(false_alert_count / rate_denominator, 6), "reason": None}
    elif not events_review_complete:
        false_alert_rate = {
            "value": None,
            "reason": "false-alert review is incomplete; provide complete review or reviewed-duration denominator",
        }
        rate_denominator = None
    elif video_duration_minutes is None or video_duration_minutes <= 0:
        false_alert_rate = {"value": None, "reason": "video duration is unavailable"}
        rate_denominator = None
    else:
        rate_denominator = float(video_duration_minutes)
        false_alert_rate = {"value": round(false_alert_count / rate_denominator, 6), "reason": None}

    truck_ground_truth = sum(
        1 for items in ground_truth.values() for item in items if item.get("class") == TRUCK_CLASS
    )
    reach_stacker_ground_truth = sum(
        1 for items in ground_truth.values() for item in items if item.get("class") == REACH_STACKER_CLASS
    )

    return {
        "iouThreshold": iou_threshold,
        "counts": totals,
        "precision": aggregate_precision,
        "recall": aggregate_recall,
        "f1": _f1(aggregate_precision, aggregate_recall),
        "perClass": per_class,
        "smallObjectRecall": _ratio(small_tp, small_total, "no small ground-truth objects"),
        "farObjectRecall": _ratio(far_tp, far_total, "no far-tagged ground-truth objects"),
        "truckReachStackerConfusion": {
            **confusion,
            "truckAsReachStackerRate": _ratio(
                confusion["truckAsReachStacker"], truck_ground_truth, "no truck ground-truth positives"
            ),
            "reachStackerAsTruckRate": _ratio(
                confusion["reachStackerAsTruck"], reach_stacker_ground_truth,
                "no reach_stacker ground-truth positives",
            ),
        },
        "staticContainerFalseDetections": {
            "reviewedFrames": len(static_frames),
            "vehicleFalsePredictions": static_false_predictions,
            "perFrame": _ratio(static_false_predictions, len(static_frames), "no static-container-only reviewed frames"),
        },
        "falseAlerts": {
            "reviewedEventCount": len(reviewed_false_alerts),
            "allEventsReviewed": all_events_reviewed,
            "falseAlertCount": false_alert_count,
            "reviewedDurationMinutes": rate_denominator,
            "perMinute": false_alert_rate,
        },
        "thresholdCalibration": (
            threshold_calibration(ground_truth, predictions, iou_threshold=iou_threshold)
            if include_threshold_calibration
            else {"skipped": True, "reason": "caller supplied an explicit finite confidence grid"}
        ),
    }


def unified_acceptance_gate(
    report: Mapping[str, Any],
    *,
    expected_dataset_hash: str,
    expected_artifact_hash: str,
) -> dict[str, Any]:
    """Strict final gate for a unified model that replaces base YOLO.

    Undefined values never pass by coercion. The report must be produced from
    fully reviewed locked videos and bound to the exact dataset/checkpoint.
    """
    failures: list[str] = []

    def number(section: str, field: str) -> float | None:
        value = report.get(section)
        raw = value.get(field) if isinstance(value, Mapping) else None
        try:
            parsed = float(raw)
        except (TypeError, ValueError):
            failures.append(f"{section}.{field} is undefined")
            return None
        if not math.isfinite(parsed):
            failures.append(f"{section}.{field} is undefined")
            return None
        return parsed

    if report.get("schemaVersion") != 1 or report.get("runtimeMode") != "UNIFIED":
        failures.append("acceptance report schema/runtime is invalid")
    if report.get("datasetContentHash") != expected_dataset_hash:
        failures.append("acceptance report dataset hash does not match")
    if report.get("artifactSha256") != expected_artifact_hash:
        failures.append("acceptance report artifact hash does not match")
    if report.get("reviewComplete") is not True:
        failures.append("locked-video review is incomplete")
    locked_sources = report.get("lockedTestSources")
    if not isinstance(locked_sources, list) or not locked_sources or not all(
        isinstance(source, str) and source for source in locked_sources
    ):
        failures.append("locked test source provenance is missing")

    precision = number("reach_stacker", "precision")
    recall = number("reach_stacker", "recall")
    false_promotions = number("hardNegative", "truckToReachFalsePromotions")
    max_gap = number("temporalContinuity", "maxGapSeconds")
    fps = number("performance", "endToEndFps")
    if precision is not None and precision < 0.90:
        failures.append("reach_stacker precision below 0.90")
    if recall is not None and recall < 0.90:
        failures.append("reach_stacker recall below 0.90")
    if false_promotions is not None and false_promotions != 0:
        failures.append("truck-to-reach promotion exists on locked hard negatives")
    if max_gap is not None and max_gap > 0.50:
        failures.append("visible-target detection gap exceeds 0.50 seconds")
    if fps is not None and fps < 8.0:
        failures.append("end-to-end Area FPS is below 8.0")
    base_regression = report.get("baseRegression")
    if not isinstance(base_regression, Mapping) or base_regression.get("passed") is not True:
        failures.append("base-class regression gate did not pass")

    return {
        "passed": not failures,
        "failures": failures,
        "thresholds": {
            "reachStackerPrecision": 0.90,
            "reachStackerRecall": 0.90,
            "truckToReachFalsePromotions": 0,
            "maxVisibleGapSeconds": 0.50,
            "minimumEndToEndFps": 8.0,
        },
    }
