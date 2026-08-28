"""Pure, strict capability resolution backed by the shared detection taxonomy."""
from __future__ import annotations

import json
import math
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal

_CANONICAL_CLASS_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,49}$")
_MAX_SAFE_INTEGER = 9_007_199_254_740_991
# Intentional explicit Unicode whitespace policy. U+001C FILE SEPARATOR is not
# whitespace here because Python and JavaScript disagree about it by default.
_SHARED_WHITESPACE = re.compile(r"[\u0009-\u000D\u0020\u00A0\u1680\u2000-\u200A\u2028\u2029\u202F\u205F\u3000]+")
_TAXONOMY_PATH = Path(__file__).resolve().parents[2] / "config" / "detection-taxonomy.json"
DetectionSource = Literal["COCO", "CUSTOM", "UNAVAILABLE"]
RuntimeMode = Literal["SUPPLEMENTAL", "UNIFIED"]

_EXPECTED_COCO_CLASSES: Mapping[str, int] = MappingProxyType({
    "person": 0,
    "bicycle": 1,
    "car": 2,
    "motorcycle": 3,
    "bus": 5,
    "truck": 7,
})
_EXPECTED_SYNTAX_ALIASES: Mapping[str, str] = MappingProxyType({
    "reach stacker": "reach_stacker",
    "reach-stacker": "reach_stacker",
    "container truck": "container_truck",
    "container-truck": "container_truck",
    "mobile crane": "mobile_crane",
    "shipping container": "shipping_container",
})
_EXPECTED_LEGACY_NAME_CONSTRAINTS: Mapping[str, tuple[str, ...]] = MappingProxyType({
    "container": (),
    "xe nâng": ("reach_stacker", "forklift"),
    "xe cẩu": ("mobile_crane",),
})
_EXPECTED_RECOMMENDED_DISPLAY_NAMES: Mapping[str, str] = MappingProxyType({
    "person": "Người",
    "bicycle": "Xe đạp",
    "car": "Xe con",
    "motorcycle": "Xe máy",
    "bus": "Xe buýt",
    "truck": "Xe tải",
    "reach_stacker": "Xe nâng container",
    "container_truck": "Xe đầu kéo container",
    "forklift": "Xe nâng hàng",
    "mobile_crane": "Xe cẩu tự hành",
    "shipping_container": "Container tĩnh",
})
_KNOWN_SUPPORTED_CLASSES = (
    "person", "bicycle", "car", "motorcycle", "bus", "truck",
    "reach_stacker", "container_truck", "forklift", "mobile_crane", "shipping_container",
)


class DetectionTaxonomyValidationError(ValueError):
    """Malformed taxonomy document (same category as the Node adapter)."""

    category = "TAXONOMY_VALIDATION"


class DetectionInputValidationError(ValueError):
    """Malformed registry/model DTO (same category as the Node adapter)."""

    category = "INPUT_VALIDATION"


def _normalized_text(value: str) -> str:
    """Match Node's explicit NFC/BOM/whitespace policy exactly."""
    normalized = _SHARED_WHITESPACE.sub(" ", unicodedata.normalize("NFC", value).replace("\ufeff", ""))
    start = 0
    end = len(normalized)
    while start < end and normalized[start] == " ":
        start += 1
    while end > start and normalized[end - 1] == " ":
        end -= 1
    return normalized[start:end]


def _normalized_key(value: str) -> str:
    return _normalized_text(value).lower()


def _taxonomy_error(message: str) -> None:
    raise DetectionTaxonomyValidationError(message)


def _input_error(message: str) -> None:
    raise DetectionInputValidationError(message)


def _parse_finite_safe_integer(value: object, field: str, error) -> int:
    """Normalize JSON's integral numbers to the cross-runtime safe-integer domain."""
    if isinstance(value, bool):
        error(f"Invalid finite safe integer at {field}")
    if isinstance(value, int):
        normalized = value
    elif isinstance(value, float) and math.isfinite(value) and value.is_integer():
        normalized = int(value)
    else:
        error(f"Invalid finite safe integer at {field}")
    if not -_MAX_SAFE_INTEGER <= normalized <= _MAX_SAFE_INTEGER:
        error(f"Invalid finite safe integer at {field}")
    return normalized


def _validate_canonical_class(value: object, field: str) -> str:
    if not isinstance(value, str) or value == "container" or _CANONICAL_CLASS_PATTERN.fullmatch(value) is None:
        _taxonomy_error(f"Invalid canonical class at {field}")
    return value


def _assert_exact_keys(actual: Mapping[object, object], expected: Mapping[str, object], section: str) -> None:
    if set(actual.keys()) != set(expected.keys()):
        _taxonomy_error(f"Invalid required keys at {section}")


def _validate_nonblank_string(value: object, field: str, error) -> str:
    if not isinstance(value, str) or not _normalized_text(value):
        error(f"Invalid nonblank string at {field}")
    return value


def decode_detection_taxonomy(parsed: object) -> Mapping[str, object]:
    """Exhaustively validate and deeply freeze the fixed version-1 taxonomy."""
    if not isinstance(parsed, Mapping):
        _taxonomy_error("Unsupported detection taxonomy schema")
    if _parse_finite_safe_integer(parsed.get("schemaVersion"), "schemaVersion", _taxonomy_error) != 1:
        _taxonomy_error("Unsupported detection taxonomy schema")

    coco_raw = parsed.get("cocoClasses")
    if not isinstance(coco_raw, Mapping):
        _taxonomy_error("Invalid detection taxonomy section: cocoClasses")
    _assert_exact_keys(coco_raw, _EXPECTED_COCO_CLASSES, "cocoClasses")
    coco_classes: dict[str, int] = {}
    coco_ids: set[int] = set()
    for canonical_class, expected_id in _EXPECTED_COCO_CLASSES.items():
        value = _parse_finite_safe_integer(coco_raw[canonical_class], f"cocoClasses.{canonical_class}", _taxonomy_error)
        _validate_canonical_class(canonical_class, f"cocoClasses.{canonical_class}")
        if value != expected_id or value in coco_ids:
            _taxonomy_error(f"Invalid required COCO mapping at cocoClasses.{canonical_class}")
        coco_ids.add(value)
        coco_classes[canonical_class] = value

    aliases_raw = parsed.get("syntaxAliases")
    if not isinstance(aliases_raw, Mapping):
        _taxonomy_error("Invalid detection taxonomy section: syntaxAliases")
    _assert_exact_keys(aliases_raw, _EXPECTED_SYNTAX_ALIASES, "syntaxAliases")
    syntax_aliases: dict[str, str] = {}
    for alias, target in _EXPECTED_SYNTAX_ALIASES.items():
        if aliases_raw[alias] != target or _normalized_key(alias) != alias:
            _taxonomy_error(f"Invalid required mapping at syntaxAliases.{alias}")
        syntax_aliases[alias] = _validate_canonical_class(target, f"syntaxAliases.{alias}")

    displays_raw = parsed.get("recommendedDisplayNames")
    if not isinstance(displays_raw, Mapping):
        _taxonomy_error("Invalid detection taxonomy section: recommendedDisplayNames")
    _assert_exact_keys(displays_raw, _EXPECTED_RECOMMENDED_DISPLAY_NAMES, "recommendedDisplayNames")
    recommended_display_names: dict[str, str] = {}
    for canonical_class in _KNOWN_SUPPORTED_CLASSES:
        _validate_canonical_class(canonical_class, f"recommendedDisplayNames.{canonical_class}")
        if displays_raw[canonical_class] != _EXPECTED_RECOMMENDED_DISPLAY_NAMES[canonical_class]:
            _taxonomy_error(f"Invalid required mapping at recommendedDisplayNames.{canonical_class}")
        recommended_display_names[canonical_class] = _EXPECTED_RECOMMENDED_DISPLAY_NAMES[canonical_class]

    constraints_raw = parsed.get("legacyNameConstraints")
    if not isinstance(constraints_raw, Mapping):
        _taxonomy_error("Invalid detection taxonomy section: legacyNameConstraints")
    _assert_exact_keys(constraints_raw, _EXPECTED_LEGACY_NAME_CONSTRAINTS, "legacyNameConstraints")
    legacy_name_constraints: dict[str, tuple[str, ...]] = {}
    for legacy_name, expected_classes in _EXPECTED_LEGACY_NAME_CONSTRAINTS.items():
        raw_classes = constraints_raw[legacy_name]
        if not isinstance(raw_classes, list) or tuple(raw_classes) != expected_classes:
            _taxonomy_error(f"Invalid required mapping at legacyNameConstraints.{legacy_name}")
        legacy_name_constraints[legacy_name] = expected_classes

    return MappingProxyType({
        "schemaVersion": 1,
        "cocoClasses": MappingProxyType(coco_classes),
        "syntaxAliases": MappingProxyType(syntax_aliases),
        "recommendedDisplayNames": MappingProxyType(recommended_display_names),
        "legacyNameConstraints": MappingProxyType(legacy_name_constraints),
    })


def _load_taxonomy(taxonomy_path: Path = _TAXONOMY_PATH) -> Mapping[str, object]:
    return decode_detection_taxonomy(json.loads(taxonomy_path.read_text(encoding="utf-8")))


DETECTION_TAXONOMY = _load_taxonomy()


# Every recommended display name is reserved for its exact canonical class.
# Derive this from the shared taxonomy so the Python and Node adapters cannot
# drift by maintaining a second hand-written alias list.
_RESERVED_DISPLAY_NAME_TO_CANONICAL_CLASS: Mapping[str, str] = MappingProxyType({
    _normalized_key(display_name): canonical_class
    for canonical_class, display_name in DETECTION_TAXONOMY["recommendedDisplayNames"].items()
})


def _assert_exact_dto_keys(value: Mapping[object, object], allowed_keys: tuple[str, ...], type_name: str) -> None:
    if set(value.keys()) != set(allowed_keys):
        _input_error(f"Invalid {type_name} fields")


@dataclass(frozen=True)
class RegistryLabelInput:
    vietnamese_name: str
    base_class: str
    sample_count: int | None = None

    @classmethod
    def from_dict(cls, value: object) -> "RegistryLabelInput":
        return parse_registry_label_input(value)

    def as_dict(self) -> dict[str, object]:
        result: dict[str, object] = {"vietnameseName": self.vietnamese_name, "baseClass": self.base_class}
        if self.sample_count is not None:
            result["sampleCount"] = self.sample_count
        return result


@dataclass(frozen=True)
class _CapabilityLabelInput:
    """The only label fields permitted to influence runtime routing."""

    vietnamese_name: str
    base_class: str


@dataclass(frozen=True)
class ActiveModelInput:
    version_key: str
    label_map: Mapping[str, str]
    runtime_mode: RuntimeMode = "SUPPLEMENTAL"

    @classmethod
    def from_dict(cls, value: object) -> "ActiveModelInput":
        return parse_active_model_input(value)

    def as_dict(self) -> dict[str, object]:
        return {
            "versionKey": self.version_key,
            "labelMap": dict(self.label_map),
            "runtimeMode": self.runtime_mode,
        }


def parse_registry_label_input(value: object) -> RegistryLabelInput:
    """Strictly decode a registry DTO; no coercion or unknown fields are accepted."""
    if not isinstance(value, Mapping):
        _input_error("Invalid RegistryLabelInput")
    has_sample_count = "sampleCount" in value
    _assert_exact_dto_keys(
        value,
        ("vietnameseName", "baseClass", "sampleCount") if has_sample_count else ("vietnameseName", "baseClass"),
        "RegistryLabelInput",
    )
    vietnamese_name = _validate_nonblank_string(value.get("vietnameseName"), "RegistryLabelInput.vietnameseName", _input_error)
    base_class = _validate_nonblank_string(value.get("baseClass"), "RegistryLabelInput.baseClass", _input_error)
    if not has_sample_count:
        return RegistryLabelInput(vietnamese_name=vietnamese_name, base_class=base_class)
    sample_count = value.get("sampleCount")
    sample_count = _parse_finite_safe_integer(sample_count, "RegistryLabelInput.sampleCount", _input_error)
    if sample_count < 0:
        _input_error("Invalid RegistryLabelInput.sampleCount")
    return RegistryLabelInput(vietnamese_name=vietnamese_name, base_class=base_class, sample_count=sample_count)


def _parse_capability_label_input(value: object) -> _CapabilityLabelInput:
    """Decode the routing subset without allowing DTO-only fields to affect it.

    Management DTO validation remains intentionally strict in
    :func:`parse_registry_label_input`. Runtime capability decisions must read
    only the display name and canonical base class, matching the Node adapter.
    """
    if not isinstance(value, Mapping):
        _input_error("Invalid CapabilityLabelInput")
    return _CapabilityLabelInput(
        vietnamese_name=_validate_nonblank_string(
            value.get("vietnameseName"),
            "CapabilityLabelInput.vietnameseName",
            _input_error,
        ),
        base_class=_validate_nonblank_string(
            value.get("baseClass"),
            "CapabilityLabelInput.baseClass",
            _input_error,
        ),
    )


def parse_active_model_input(value: object) -> ActiveModelInput:
    """Strictly decode an active-model DTO; invalid manifest values are never dropped."""
    if not isinstance(value, Mapping):
        _input_error("Invalid ActiveModelInput")
    has_runtime_mode = "runtimeMode" in value
    _assert_exact_dto_keys(
        value,
        ("versionKey", "labelMap", "runtimeMode") if has_runtime_mode else ("versionKey", "labelMap"),
        "ActiveModelInput",
    )
    version_key = _validate_nonblank_string(value.get("versionKey"), "ActiveModelInput.versionKey", _input_error)
    raw_label_map = value.get("labelMap")
    if not isinstance(raw_label_map, Mapping):
        _input_error("Invalid ActiveModelInput.labelMap")
    label_map: dict[str, str] = {}
    for key, raw_class in raw_label_map.items():
        normalized_key = _validate_nonblank_string(key, "ActiveModelInput.labelMap key", _input_error)
        validated_class = _validate_nonblank_string(
            raw_class,
            f"ActiveModelInput.labelMap.{normalized_key}",
            _input_error,
        )
        if normalize_canonical_class(validated_class) is None:
            _input_error(f"Invalid ActiveModelInput.labelMap.{normalized_key} canonical class")
        label_map[normalized_key] = validated_class
    runtime_mode = value.get("runtimeMode", "SUPPLEMENTAL")
    if runtime_mode not in {"SUPPLEMENTAL", "UNIFIED"}:
        _input_error("Invalid ActiveModelInput.runtimeMode")
    return ActiveModelInput(
        version_key=version_key,
        label_map=MappingProxyType(label_map),
        runtime_mode=runtime_mode,
    )


@dataclass(frozen=True)
class DetectionCapability:
    canonical_class: str | None
    detection_source: DetectionSource
    is_detectable: bool
    active_model_version: str | None
    reason_code: str
    reason_text: str

    def as_dict(self) -> dict[str, object]:
        return {
            "canonicalClass": self.canonical_class,
            "detectionSource": self.detection_source,
            "isDetectable": self.is_detectable,
            "activeModelVersion": self.active_model_version,
            "reasonCode": self.reason_code,
            "reasonText": self.reason_text,
        }


def normalize_canonical_class(value: str) -> str | None:
    """Normalize spelling only; never merge semantically different classes."""
    key = _normalized_key(value)
    syntax_aliases = DETECTION_TAXONOMY["syntaxAliases"]
    if not isinstance(syntax_aliases, Mapping):
        raise AssertionError("validated taxonomy has invalid syntax aliases")
    candidate = syntax_aliases.get(key, key)
    if candidate == "container" or not isinstance(candidate, str) or _CANONICAL_CLASS_PATTERN.fullmatch(candidate) is None:
        return None
    return candidate


def _unavailable(canonical_class: str | None, reason_code: str, reason_text: str) -> DetectionCapability:
    return DetectionCapability(canonical_class, "UNAVAILABLE", False, None, reason_code, reason_text)


def _validate_registry_mapping(label: _CapabilityLabelInput) -> tuple[str | None, DetectionCapability | None]:
    raw_class = _normalized_text(label.base_class)
    canonical_class = normalize_canonical_class(raw_class)
    if _normalized_key(raw_class) == "container":
        return None, _unavailable(None, "AMBIGUOUS_CONTAINER", "Class container không xác định xe đầu kéo hay container tĩnh")
    if canonical_class is None:
        return None, _unavailable(None, "INVALID_CANONICAL_CLASS", f"Class {raw_class} không phải định danh canonical hợp lệ")
    display_name = _normalized_text(label.vietnamese_name)
    display_key = _normalized_key(display_name)
    reserved_canonical_class = _RESERVED_DISPLAY_NAME_TO_CANONICAL_CLASS.get(display_key)
    if reserved_canonical_class is not None and reserved_canonical_class != canonical_class:
        return None, _unavailable(
            None,
            "RESERVED_DISPLAY_NAME_CLASS_MISMATCH",
            f"Tên {display_name} phải dùng class {reserved_canonical_class}, không phải {canonical_class}",
        )
    constraints = DETECTION_TAXONOMY["legacyNameConstraints"]
    if not isinstance(constraints, Mapping):
        raise AssertionError("validated taxonomy has invalid legacy constraints")
    allowed_classes = constraints.get(display_key)
    if allowed_classes is not None:
        if not isinstance(allowed_classes, tuple):
            raise AssertionError("validated taxonomy has invalid legacy class constraint")
        if not allowed_classes:
            return None, _unavailable(None, "AMBIGUOUS_CONTAINER", "Tên Container không xác định xe đầu kéo hay container tĩnh")
        if canonical_class not in allowed_classes:
            return None, _unavailable(None, "LEGACY_NAME_CLASS_MISMATCH", f"Tên {display_name} không phù hợp với class {canonical_class}")
    return canonical_class, None


def _active_manifest_classes(active_model: ActiveModelInput) -> frozenset[str]:
    return frozenset(
        canonical_class
        for raw_class in active_model.label_map.values()
        if (canonical_class := normalize_canonical_class(raw_class)) is not None
    )


def _legacy_manifest_class(
    label: _CapabilityLabelInput,
    active_model: ActiveModelInput,
) -> str | None:
    """Resolve an existing ambiguous legacy name from an exact model manifest.

    This is intentionally narrower than a semantic alias: only an exact
    labelMap key may repair a pre-existing legacy ``base_class`` mismatch, and
    the mapped class must be one of that legacy name's declared meanings.
    """
    display_key = _normalized_key(label.vietnamese_name)
    constraints = DETECTION_TAXONOMY["legacyNameConstraints"]
    if not isinstance(constraints, Mapping):
        raise AssertionError("validated taxonomy has invalid legacy constraints")
    allowed_classes = constraints.get(display_key)
    if not isinstance(allowed_classes, tuple) or not allowed_classes:
        return None
    for model_label, raw_class in active_model.label_map.items():
        if _normalized_key(model_label) != display_key:
            continue
        canonical_class = normalize_canonical_class(raw_class)
        return canonical_class if canonical_class in allowed_classes else None
    return None


def resolve_label_capability(label: object, active_model: object | None) -> DetectionCapability:
    """Resolve runtime capability from routing fields only.

    Strict management validation remains available through
    :func:`parse_registry_label_input`; malformed sample counts or other
    display-only fields must not change a runtime decision.
    """
    # These dataclasses are public convenience types, so callers may construct
    # them directly. Re-decode only the fields meaningful to routing and take
    # an immutable copy of a direct label_map.
    label_dto: object
    if isinstance(label, RegistryLabelInput):
        label_dto = {
            "vietnameseName": label.vietnamese_name,
            "baseClass": label.base_class,
        }
    else:
        label_dto = label
    parsed_label = _parse_capability_label_input(label_dto)

    if active_model is None:
        parsed_active_model = None
    else:
        active_model_dto: object = (
            {
                "versionKey": active_model.version_key,
                "labelMap": active_model.label_map,
                "runtimeMode": active_model.runtime_mode,
            }
            if isinstance(active_model, ActiveModelInput)
            else active_model
        )
        parsed_active_model = parse_active_model_input(active_model_dto)
    canonical_class, error = _validate_registry_mapping(parsed_label)
    if error is not None:
        if parsed_active_model is not None and error.reason_code == "LEGACY_NAME_CLASS_MISMATCH":
            manifest_class = _legacy_manifest_class(parsed_label, parsed_active_model)
            if manifest_class is not None:
                return DetectionCapability(
                    manifest_class,
                    "CUSTOM",
                    True,
                    parsed_active_model.version_key,
                    "ACTIVE_CUSTOM_LEGACY_LABEL",
                    f"Nhận diện bởi model custom {parsed_active_model.version_key}; nhãn legacy được định nghĩa bởi manifest",
                )
        return error
    if canonical_class is None:
        raise AssertionError("validated registry mapping has no canonical class")
    coco_classes = DETECTION_TAXONOMY["cocoClasses"]
    if not isinstance(coco_classes, Mapping):
        raise AssertionError("validated taxonomy has invalid COCO classes")
    active_classes = _active_manifest_classes(parsed_active_model) if parsed_active_model is not None else frozenset()
    if parsed_active_model is not None and parsed_active_model.runtime_mode == "UNIFIED":
        if canonical_class in active_classes:
            return DetectionCapability(
                canonical_class,
                "CUSTOM",
                True,
                parsed_active_model.version_key,
                "ACTIVE_UNIFIED_CLASS",
                f"Nhận diện bởi model unified {parsed_active_model.version_key}",
            )
        return _unavailable(
            canonical_class,
            "UNIFIED_CLASS_NOT_IN_ACTIVE_MODEL",
            f"Model unified đang hoạt động không hỗ trợ class {canonical_class}",
        )
    if canonical_class in coco_classes:
        return DetectionCapability(canonical_class, "COCO", True, None, "COCO_BASE_CLASS", "Nhận diện bởi model COCO")
    if parsed_active_model is None:
        return _unavailable(canonical_class, "NO_ACTIVE_CUSTOM_MODEL", "Chưa có model nhận diện")
    if canonical_class in active_classes:
        return DetectionCapability(canonical_class, "CUSTOM", True, parsed_active_model.version_key, "ACTIVE_CUSTOM_CLASS", f"Nhận diện bởi model custom {parsed_active_model.version_key}")
    return _unavailable(canonical_class, "CUSTOM_CLASS_NOT_IN_ACTIVE_MODEL", f"Model custom đang hoạt động không hỗ trợ class {canonical_class}")
