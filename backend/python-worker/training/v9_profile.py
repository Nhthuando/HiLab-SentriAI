"""Strict shared contract for BAI-KIEM V9 data preparation and acceptance."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


EXPECTED_V9_CLASSES = (
    "person",
    "bicycle",
    "car",
    "motorcycle",
    "bus",
    "truck",
    "container_truck",
    "forklift",
    "reach_stacker",
    "mobile_crane",
)


class V9ProfileError(ValueError):
    """Raised when the shared V9 profile is incomplete or ambiguous."""


@dataclass(frozen=True)
class V9ClassDefinition:
    id: int
    base_class: str
    recommended_display_name: str
    minimum_instances: int
    minimum_sources: int


@dataclass(frozen=True)
class V9Selection:
    train_val_target_frames: int
    locked_target_frames: int
    sample_interval_seconds: float
    stationary_anchor_seconds: float
    maximum_candidate_frames: int
    proposal_confidence: float
    high_confidence: float
    negative_fraction: float
    near_duplicate_hamming: int
    jpeg_quality: int
    image_size: int
    batch: int


@dataclass(frozen=True)
class V9Acceptance:
    macro_precision: float
    macro_recall: float
    macro_f1: float
    map50: float
    macro_map50_to_95: float
    minimum_class_precision: float
    minimum_class_recall: float
    minimum_end_to_end_fps: float
    maximum_visible_gap_seconds: float


@dataclass(frozen=True)
class V9Profile:
    name: str
    runtime_mode: str
    class_definitions: tuple[V9ClassDefinition, ...]
    hard_negative_classes: tuple[str, ...]
    selection: V9Selection
    acceptance: V9Acceptance

    @property
    def classes(self) -> tuple[str, ...]:
        return tuple(item.base_class for item in self.class_definitions)

    @property
    def minimum_end_to_end_fps(self) -> float:
        return self.acceptance.minimum_end_to_end_fps


def _object(value: object, field: str, expected: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise V9ProfileError(f"{field} must be an object")
    unknown = set(value).difference(expected)
    missing = expected.difference(value)
    if unknown or missing:
        raise V9ProfileError(f"{field} keys mismatch; missing={sorted(missing)} unknown={sorted(unknown)}")
    return value


def _integer(value: object, field: str, *, minimum: int = 0, maximum: int | None = None) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise V9ProfileError(f"{field} must be an integer >= {minimum}")
    if maximum is not None and value > maximum:
        raise V9ProfileError(f"{field} must be <= {maximum}")
    return value


def _number(value: object, field: str, *, minimum: float, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise V9ProfileError(f"{field} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < minimum or (maximum is not None and result > maximum):
        raise V9ProfileError(f"{field} is outside [{minimum}, {maximum}]")
    return result


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise V9ProfileError(f"{field} must be a trimmed non-empty string")
    return value


def load_v9_profile(path: Path | str, taxonomy_path: Path | str | None = None) -> V9Profile:
    profile_path = Path(path).resolve()
    root = _object(
        json.loads(profile_path.read_text(encoding="utf-8")),
        "profile",
        {"schemaVersion", "profile", "runtimeMode", "classes", "hardNegativeClasses", "selection", "acceptance"},
    )
    if _integer(root["schemaVersion"], "schemaVersion", minimum=1) != 1:
        raise V9ProfileError("schemaVersion must equal 1")
    if _text(root["profile"], "profile") != "BAIKIEM_V9_UNIFIED":
        raise V9ProfileError("profile must equal BAIKIEM_V9_UNIFIED")
    if _text(root["runtimeMode"], "runtimeMode") != "UNIFIED":
        raise V9ProfileError("runtimeMode must equal UNIFIED")

    raw_classes = root["classes"]
    if not isinstance(raw_classes, list) or len(raw_classes) != len(EXPECTED_V9_CLASSES):
        raise V9ProfileError("classes must contain exactly ten definitions")
    definitions: list[V9ClassDefinition] = []
    for index, raw in enumerate(raw_classes):
        item = _object(
            raw,
            f"classes[{index}]",
            {"id", "baseClass", "recommendedDisplayName", "minimumInstances", "minimumSources"},
        )
        class_id = _integer(item["id"], f"classes[{index}].id")
        base_class = _text(item["baseClass"], f"classes[{index}].baseClass")
        if class_id != index or base_class != EXPECTED_V9_CLASSES[index]:
            raise V9ProfileError("V9 class IDs/order do not match the canonical contract")
        definitions.append(V9ClassDefinition(
            id=class_id,
            base_class=base_class,
            recommended_display_name=_text(item["recommendedDisplayName"], f"classes[{index}].recommendedDisplayName"),
            minimum_instances=_integer(item["minimumInstances"], f"classes[{index}].minimumInstances", minimum=1),
            minimum_sources=_integer(item["minimumSources"], f"classes[{index}].minimumSources", minimum=1),
        ))

    if taxonomy_path is None:
        taxonomy_path = profile_path.with_name("detection-taxonomy.json")
    taxonomy = json.loads(Path(taxonomy_path).read_text(encoding="utf-8"))
    display_names = taxonomy.get("recommendedDisplayNames") if isinstance(taxonomy, Mapping) else None
    if not isinstance(display_names, Mapping):
        raise V9ProfileError("detection taxonomy has no recommendedDisplayNames")
    for item in definitions:
        if display_names.get(item.base_class) != item.recommended_display_name:
            raise V9ProfileError(f"display-name mismatch for {item.base_class}")

    hard_negatives = root["hardNegativeClasses"]
    if hard_negatives != ["shipping_container"]:
        raise V9ProfileError("hardNegativeClasses must equal ['shipping_container']")

    selection = _object(root["selection"], "selection", {
        "trainValTargetFrames", "lockedTargetFrames", "sampleIntervalSeconds", "stationaryAnchorSeconds",
        "maximumCandidateFrames", "proposalConfidence", "highConfidence", "negativeFraction",
        "nearDuplicateHamming", "jpegQuality", "imageSize", "batch",
    })
    parsed_selection = V9Selection(
        train_val_target_frames=_integer(selection["trainValTargetFrames"], "selection.trainValTargetFrames", minimum=1),
        locked_target_frames=_integer(selection["lockedTargetFrames"], "selection.lockedTargetFrames", minimum=1),
        sample_interval_seconds=_number(selection["sampleIntervalSeconds"], "selection.sampleIntervalSeconds", minimum=0.1),
        stationary_anchor_seconds=_number(selection["stationaryAnchorSeconds"], "selection.stationaryAnchorSeconds", minimum=1.0),
        maximum_candidate_frames=_integer(selection["maximumCandidateFrames"], "selection.maximumCandidateFrames", minimum=1),
        proposal_confidence=_number(selection["proposalConfidence"], "selection.proposalConfidence", minimum=0.0, maximum=1.0),
        high_confidence=_number(selection["highConfidence"], "selection.highConfidence", minimum=0.0, maximum=1.0),
        negative_fraction=_number(selection["negativeFraction"], "selection.negativeFraction", minimum=0.0, maximum=0.5),
        near_duplicate_hamming=_integer(selection["nearDuplicateHamming"], "selection.nearDuplicateHamming", maximum=64),
        jpeg_quality=_integer(selection["jpegQuality"], "selection.jpegQuality", minimum=1, maximum=100),
        image_size=_integer(selection["imageSize"], "selection.imageSize", minimum=320),
        batch=_integer(selection["batch"], "selection.batch", minimum=1),
    )
    if parsed_selection.high_confidence <= parsed_selection.proposal_confidence:
        raise V9ProfileError("selection.highConfidence must exceed proposalConfidence")
    if parsed_selection.train_val_target_frames + parsed_selection.locked_target_frames > parsed_selection.maximum_candidate_frames:
        raise V9ProfileError("selected frame targets exceed maximumCandidateFrames")

    acceptance = _object(root["acceptance"], "acceptance", {
        "macroPrecision", "macroRecall", "macroF1", "map50", "macroMap50To95",
        "minimumClassPrecision", "minimumClassRecall", "minimumEndToEndFps", "maximumVisibleGapSeconds",
    })
    parsed_acceptance = V9Acceptance(
        macro_precision=_number(acceptance["macroPrecision"], "acceptance.macroPrecision", minimum=0.0, maximum=1.0),
        macro_recall=_number(acceptance["macroRecall"], "acceptance.macroRecall", minimum=0.0, maximum=1.0),
        macro_f1=_number(acceptance["macroF1"], "acceptance.macroF1", minimum=0.0, maximum=1.0),
        map50=_number(acceptance["map50"], "acceptance.map50", minimum=0.0, maximum=1.0),
        macro_map50_to_95=_number(acceptance["macroMap50To95"], "acceptance.macroMap50To95", minimum=0.0, maximum=1.0),
        minimum_class_precision=_number(acceptance["minimumClassPrecision"], "acceptance.minimumClassPrecision", minimum=0.0, maximum=1.0),
        minimum_class_recall=_number(acceptance["minimumClassRecall"], "acceptance.minimumClassRecall", minimum=0.0, maximum=1.0),
        minimum_end_to_end_fps=_number(acceptance["minimumEndToEndFps"], "acceptance.minimumEndToEndFps", minimum=0.1),
        maximum_visible_gap_seconds=_number(acceptance["maximumVisibleGapSeconds"], "acceptance.maximumVisibleGapSeconds", minimum=0.0),
    )
    return V9Profile(
        name="BAIKIEM_V9_UNIFIED",
        runtime_mode="UNIFIED",
        class_definitions=tuple(definitions),
        hard_negative_classes=("shipping_container",),
        selection=parsed_selection,
        acceptance=parsed_acceptance,
    )
