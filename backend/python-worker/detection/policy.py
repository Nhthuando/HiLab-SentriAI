"""Fail-closed confidence and temporal-confirmation policy for Area detection.

This module is deliberately independent from detector and zone implementations.  It
keeps threshold configuration immutable and makes it impossible for a low-confidence
observation to be used as a new-track / new-violation candidate.
"""
from __future__ import annotations

import json
import math
import os
import re
from collections import deque
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Deque, Mapping


class DetectionPolicyConfigurationError(ValueError):
    """Raised when Area detection policy configuration is invalid or unsafe."""


_CANONICAL_CLASS_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,49}$")
_SOURCE_ALIASES = {
    "base": "base",
    "coco": "base",
    "custom": "custom",
}
_POLICY_SOURCES = frozenset({"base", "custom"})


def _configuration_error(message: str) -> DetectionPolicyConfigurationError:
    return DetectionPolicyConfigurationError(f"Invalid Area detection policy: {message}")


def _as_confidence(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _configuration_error(f"{field_name} must be a JSON number between 0 and 1")
    confidence = float(value)
    if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
        raise _configuration_error(f"{field_name} must be between 0 and 1")
    return confidence


def _normalise_source(source: str) -> str:
    if not isinstance(source, str):
        raise ValueError("detection source must be a string")
    canonical = _SOURCE_ALIASES.get(source.strip().casefold())
    if canonical is None:
        raise ValueError("detection source must be one of: base, COCO, custom")
    return canonical


def _normalise_class_name(canonical_class: str) -> str:
    if not isinstance(canonical_class, str):
        raise ValueError("canonical class must be a string")
    normalized = canonical_class.strip().casefold()
    if not _CANONICAL_CLASS_PATTERN.fullmatch(normalized):
        raise ValueError("canonical class must match ^[a-z][a-z0-9_]{1,49}$")
    return normalized


@dataclass(frozen=True, slots=True)
class DetectionThresholds:
    """Initiation and continuation confidence for one detector source/class."""

    initiation: float
    continuation: float

    def __post_init__(self) -> None:
        initiation = _as_confidence(self.initiation, field_name="initiation")
        continuation = _as_confidence(self.continuation, field_name="continuation")
        if continuation > initiation:
            raise _configuration_error("continuation must be less than or equal to initiation")
        object.__setattr__(self, "initiation", initiation)
        object.__setattr__(self, "continuation", continuation)


DEFAULT_BASE_THRESHOLDS = DetectionThresholds(initiation=0.30, continuation=0.14)
DEFAULT_CUSTOM_THRESHOLDS = DetectionThresholds(initiation=0.45, continuation=0.25)
DEFAULT_CUSTOM_CONFIRM_HITS = 2
DEFAULT_CUSTOM_CONFIRM_WINDOW = 3


def _freeze_overrides(
    source: str,
    overrides: Mapping[str, DetectionThresholds],
    default: DetectionThresholds,
) -> Mapping[str, DetectionThresholds]:
    if not isinstance(overrides, Mapping):
        raise _configuration_error(f"{source} overrides must be an object")

    frozen: dict[str, DetectionThresholds] = {}
    for raw_class, thresholds in overrides.items():
        try:
            canonical_class = _normalise_class_name(raw_class)
        except ValueError as error:
            raise _configuration_error(f"{source} override class is invalid: {error}") from error
        if not isinstance(thresholds, DetectionThresholds):
            raise _configuration_error(f"{source}.{canonical_class} thresholds must be DetectionThresholds")
        frozen[canonical_class] = thresholds
    return MappingProxyType(frozen)


def _parse_environment_confidence(raw_value: object, *, name: str, default: float) -> float:
    if raw_value is None:
        return default
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise _configuration_error(f"{name} must be a number between 0 and 1")
    try:
        value = float(raw_value)
    except ValueError as error:
        raise _configuration_error(f"{name} must be a number between 0 and 1") from error
    return _as_confidence(value, field_name=name)


@dataclass(frozen=True, slots=True)
class DetectionPolicy:
    """Immutable source/class policy built from validated environment settings."""

    base_default: DetectionThresholds = DEFAULT_BASE_THRESHOLDS
    custom_default: DetectionThresholds = DEFAULT_CUSTOM_THRESHOLDS
    base_overrides: Mapping[str, DetectionThresholds] = field(default_factory=dict)
    custom_overrides: Mapping[str, DetectionThresholds] = field(default_factory=dict)
    custom_confirmation_hits: int = DEFAULT_CUSTOM_CONFIRM_HITS
    custom_confirmation_window: int = DEFAULT_CUSTOM_CONFIRM_WINDOW

    def __post_init__(self) -> None:
        if not isinstance(self.base_default, DetectionThresholds):
            raise _configuration_error("base default thresholds are invalid")
        if not isinstance(self.custom_default, DetectionThresholds):
            raise _configuration_error("custom default thresholds are invalid")
        object.__setattr__(
            self,
            "base_overrides",
            _freeze_overrides("base", self.base_overrides, self.base_default),
        )
        object.__setattr__(
            self,
            "custom_overrides",
            _freeze_overrides("custom", self.custom_overrides, self.custom_default),
        )
        if isinstance(self.custom_confirmation_hits, bool) or self.custom_confirmation_hits != DEFAULT_CUSTOM_CONFIRM_HITS:
            raise _configuration_error(
                f"CUSTOM_CONFIRM_HITS must be {DEFAULT_CUSTOM_CONFIRM_HITS} to preserve 2-of-3 confirmation"
            )
        if isinstance(self.custom_confirmation_window, bool) or self.custom_confirmation_window != DEFAULT_CUSTOM_CONFIRM_WINDOW:
            raise _configuration_error(
                f"CUSTOM_CONFIRM_WINDOW must be {DEFAULT_CUSTOM_CONFIRM_WINDOW} to preserve 2-of-3 confirmation"
            )

    @classmethod
    def from_environment(cls, environment: Mapping[str, str] | None = None) -> "DetectionPolicy":
        """Create a policy from environment data, rejecting invalid configuration.

        A missing value receives the safe default.  A present malformed or weaker
        value is an operational configuration error rather than a silent fallback.
        """

        values: Mapping[str, str] = os.environ if environment is None else environment
        # Preserve the deployed Area calibration while the golden set is still
        # pending annotation. improve.md explicitly describes 0.25-0.35 as a
        # benchmark starting range, not a hard safety floor. The previous
        # implementation ignored these existing values and silently forced
        # 0.30/0.14, which removed nearly every far-away BAI-KIEM object.
        base_default = DetectionThresholds(
            initiation=_parse_environment_confidence(
                values.get("AREA_BASE_INITIATION_CONFIDENCE", values.get("AREA_TRACK_INITIATION_CONFIDENCE")),
                name="AREA_BASE_INITIATION_CONFIDENCE",
                default=DEFAULT_BASE_THRESHOLDS.initiation,
            ),
            continuation=_parse_environment_confidence(
                values.get("AREA_BASE_CONTINUATION_CONFIDENCE", values.get("AREA_TRACK_CONTINUATION_CONFIDENCE")),
                name="AREA_BASE_CONTINUATION_CONFIDENCE",
                default=DEFAULT_BASE_THRESHOLDS.continuation,
            ),
        )
        overrides = _parse_threshold_overrides(values.get("AREA_CLASS_THRESHOLDS_JSON"))
        confirmation_hits = _parse_confirmation_setting(
            values.get("CUSTOM_CONFIRM_HITS"),
            name="CUSTOM_CONFIRM_HITS",
            expected=DEFAULT_CUSTOM_CONFIRM_HITS,
        )
        confirmation_window = _parse_confirmation_setting(
            values.get("CUSTOM_CONFIRM_WINDOW"),
            name="CUSTOM_CONFIRM_WINDOW",
            expected=DEFAULT_CUSTOM_CONFIRM_WINDOW,
        )
        return cls(
            base_default=base_default,
            base_overrides=overrides["base"],
            custom_overrides=overrides["custom"],
            custom_confirmation_hits=confirmation_hits,
            custom_confirmation_window=confirmation_window,
        )
    def thresholds_for(self, source: str, canonical_class: str) -> DetectionThresholds:
        """Return immutable thresholds for a normalized detector source/class."""

        normalized_source = _normalise_source(source)
        normalized_class = _normalise_class_name(canonical_class)
        if normalized_source == "base":
            return self.base_overrides.get(normalized_class, self.base_default)
        return self.custom_overrides.get(normalized_class, self.custom_default)

    def can_initiate(self, source: str, canonical_class: str, confidence: object) -> bool:
        """Whether an observation can create a track or begin a violation."""

        threshold = self.thresholds_for(source, canonical_class).initiation
        return _meets_threshold(confidence, threshold)

    def can_continue(self, source: str, canonical_class: str, confidence: object) -> bool:
        """Whether an observation is strong enough to maintain an existing track."""

        threshold = self.thresholds_for(source, canonical_class).continuation
        return _meets_threshold(confidence, threshold)

    def can_use_observation(
        self,
        source: str,
        canonical_class: str,
        confidence: object,
        *,
        has_confirmed_track: bool,
    ) -> bool:
        """Allow low confidence only as continuation of an already-confirmed track."""

        if self.can_initiate(source, canonical_class, confidence):
            return True
        return has_confirmed_track is True and self.can_continue(source, canonical_class, confidence)

    def new_custom_confirmation_window(self) -> "TemporalConfirmationWindow":
        """Create independent per-association 2-of-3 evidence state."""

        return TemporalConfirmationWindow(
            required_hits=self.custom_confirmation_hits,
            window_size=self.custom_confirmation_window,
        )


def _parse_threshold_overrides(raw_value: object) -> dict[str, dict[str, DetectionThresholds]]:
    parsed: object
    if raw_value is None or (isinstance(raw_value, str) and not raw_value.strip()):
        parsed = {}
    elif not isinstance(raw_value, str):
        raise _configuration_error("AREA_CLASS_THRESHOLDS_JSON must be a JSON object string")
    else:
        try:
            parsed = json.loads(raw_value)
        except json.JSONDecodeError as error:
            raise _configuration_error("AREA_CLASS_THRESHOLDS_JSON is not valid JSON") from error

    if not isinstance(parsed, dict):
        raise _configuration_error("AREA_CLASS_THRESHOLDS_JSON must decode to an object")

    unexpected_sources = set(parsed).difference(_POLICY_SOURCES)
    if unexpected_sources:
        raise _configuration_error(
            "AREA_CLASS_THRESHOLDS_JSON has unsupported source(s): "
            + ", ".join(sorted(str(source) for source in unexpected_sources))
        )

    result: dict[str, dict[str, DetectionThresholds]] = {"base": {}, "custom": {}}
    for source in _POLICY_SOURCES:
        raw_classes = parsed.get(source, {})
        if not isinstance(raw_classes, dict):
            raise _configuration_error(f"AREA_CLASS_THRESHOLDS_JSON.{source} must be an object")
        for raw_class, raw_thresholds in raw_classes.items():
            try:
                canonical_class = _normalise_class_name(raw_class)
            except ValueError as error:
                raise _configuration_error(f"{source} override class is invalid: {error}") from error
            if not isinstance(raw_thresholds, dict):
                raise _configuration_error(f"{source}.{canonical_class} must be an object")
            expected_fields = {"initiation", "continuation"}
            if set(raw_thresholds) != expected_fields:
                raise _configuration_error(
                    f"{source}.{canonical_class} must contain exactly initiation and continuation"
                )
            result[source][canonical_class] = DetectionThresholds(
                initiation=raw_thresholds["initiation"],
                continuation=raw_thresholds["continuation"],
            )
    return result


def _parse_confirmation_setting(raw_value: object, *, name: str, expected: int) -> int:
    if raw_value is None:
        return expected
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise _configuration_error(f"{name} must be the integer {expected}")
    try:
        value = int(raw_value)
    except ValueError as error:
        raise _configuration_error(f"{name} must be the integer {expected}") from error
    if value != expected:
        raise _configuration_error(f"{name} must be {expected} to preserve 2-of-3 confirmation")
    return value


def _meets_threshold(confidence: object, threshold: float) -> bool:
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return False
    candidate = float(confidence)
    return math.isfinite(candidate) and candidate >= threshold


class TemporalConfirmationWindow:
    """Per-track evidence over the latest eligible inference frames.

    ``frame_index`` is deliberately supplied by the caller.  For custom inference
    running every N video frames, callers pass the eligible-inference index so the
    window remains exactly two hits in the latest three inference opportunities.
    """

    def __init__(self, *, required_hits: int = DEFAULT_CUSTOM_CONFIRM_HITS, window_size: int = DEFAULT_CUSTOM_CONFIRM_WINDOW) -> None:
        if isinstance(required_hits, bool) or not isinstance(required_hits, int) or required_hits < 1:
            raise ValueError("required_hits must be a positive integer")
        if isinstance(window_size, bool) or not isinstance(window_size, int) or window_size < required_hits:
            raise ValueError("window_size must be an integer greater than or equal to required_hits")
        self.required_hits = required_hits
        self.window_size = window_size
        self._observations: dict[str, Deque[tuple[int, bool]]] = {}

    def observe(self, track_key: str, *, frame_index: int, matched: bool) -> bool:
        """Record one eligible frame and report whether that track is confirmed."""

        key = self._validate_track_key(track_key)
        if isinstance(frame_index, bool) or not isinstance(frame_index, int) or frame_index < 0:
            raise ValueError("frame_index must be a non-negative integer")
        if not isinstance(matched, bool):
            raise ValueError("matched must be a bool")

        history = self._observations.setdefault(key, deque())
        if history and frame_index < history[-1][0]:
            raise ValueError("frame_index must be monotonic for a track")
        if history and frame_index == history[-1][0]:
            history[-1] = (frame_index, matched)
        else:
            history.append((frame_index, matched))

        earliest_frame = frame_index - self.window_size + 1
        while history and history[0][0] < earliest_frame:
            history.popleft()
        return sum(1 for _, was_matched in history if was_matched) >= self.required_hits

    def reset(self, track_key: str) -> None:
        """Discard evidence for a terminated or re-associated track."""

        self._observations.pop(self._validate_track_key(track_key), None)

    def clear(self) -> None:
        """Discard all associations, for example when a model/control snapshot changes."""

        self._observations.clear()

    @staticmethod
    def _validate_track_key(track_key: str) -> str:
        if not isinstance(track_key, str) or not track_key.strip():
            raise ValueError("track_key must be a non-empty string")
        return track_key
