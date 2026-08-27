"""Atomic database snapshots for Area-zone detection control."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Optional, Tuple

from db.repositories import (
    get_active_custom_model,
    get_active_zones_by_camera,
    get_all_object_labels,
)
logger = logging.getLogger("sentriai.zone.sync")
_WARNED_MANUAL_CANDIDATES: set[tuple[str, str]] = set()
_WARNED_PARTIAL_UNIFIED: set[tuple[str, tuple[str, ...]]] = set()


@dataclass(frozen=True)
class ZoneSnapshot:
    """Immutable detection-control state consumed by the Area worker.

    A refresh constructs this object completely before atomically swapping it
    into the synchronizer. Nested data is frozen to keep one frame from
    accidentally mutating data another frame is reading.
    """

    zones: Tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    class_to_labels: Mapping[str, Tuple[str, ...]] = field(default_factory=lambda: MappingProxyType({}))
    all_labels: Tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    capabilities_by_label: Mapping[str, Mapping[str, Any]] = field(default_factory=lambda: MappingProxyType({}))
    coco_classes: frozenset[str] = field(default_factory=frozenset)
    custom_classes: frozenset[str] = field(default_factory=frozenset)
    active_model: Optional[Mapping[str, Any]] = None


def _freeze(value: Any) -> Any:
    """Recursively freeze JSON-shaped data held by a snapshot."""
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze(item) for item in value)
    return value


def _taxonomy_api():
    """Import lazily because ``detection.__init__`` imports AreaPipeline.

    Zone synchronization is itself imported by AreaPipeline, so importing the
    taxonomy at module-load time would create a package initialization cycle.
    The worker calls this only after both modules have finished loading.
    """
    from detection.taxonomy import (  # pylint: disable=import-outside-toplevel
        DetectionInputValidationError,
        parse_active_model_input,
        resolve_label_capability,
    )
    return DetectionInputValidationError, parse_active_model_input, resolve_label_capability


def _unavailable_capability(
    *,
    canonical_class: Optional[str],
    reason_code: str,
    reason_text: str,
) -> Dict[str, Any]:
    return {
        "canonicalClass": canonical_class,
        "detectionSource": "UNAVAILABLE",
        "isDetectable": False,
        "activeModelVersion": None,
        "reasonCode": reason_code,
        "reasonText": reason_text,
    }


def _normalize_active_model(
    raw_active: Any,
) -> tuple[Optional[Dict[str, Any]], Optional[Mapping[str, Any]], Optional[str]]:
    """Validate the active manifest and retain only serializable metadata."""
    if raw_active is None:
        return None, None, None
    if not isinstance(raw_active, dict):
        return None, None, "Bản ghi model ACTIVE không hợp lệ"

    DetectionInputValidationError, parse_active_model_input, _ = _taxonomy_api()
    metrics = raw_active.get("evaluation_metrics")
    label_map = metrics.get("labelMap") if isinstance(metrics, dict) else None
    manual_approval = metrics.get("manualProductionApproval") if isinstance(metrics, dict) else None
    allow_partial_unified = bool(
        isinstance(manual_approval, dict)
        and manual_approval.get("approved") is True
        and manual_approval.get("allowPartialUnified") is True
    )
    try:
        parsed = parse_active_model_input({
            "versionKey": raw_active.get("version_key"),
            "labelMap": label_map,
            "runtimeMode": metrics.get("runtimeMode", "SUPPLEMENTAL") if isinstance(metrics, dict) else "SUPPLEMENTAL",
        })
    except DetectionInputValidationError as exc:
        return None, None, f"Manifest model ACTIVE không hợp lệ: {exc}"

    model_input = {
        "versionKey": parsed.version_key,
        "labelMap": dict(parsed.label_map),
        "runtimeMode": parsed.runtime_mode,
    }
    data_root = (Path(__file__).resolve().parents[2] / "data").resolve()
    raw_artifact_path = raw_active.get("artifact_path")
    artifact_path = raw_artifact_path
    if isinstance(raw_artifact_path, str) and raw_artifact_path.strip():
        candidate = Path(raw_artifact_path.strip())
        resolved = candidate.resolve() if candidate.is_absolute() else (data_root / candidate).resolve()
        if resolved != data_root and data_root not in resolved.parents:
            return None, None, "Artifact model ACTIVE nằm ngoài backend/data"
        artifact_path = str(resolved)
    snapshot_model = _freeze({
        "version_key": parsed.version_key,
        "artifact_path": artifact_path,
        "artifact_sha256": raw_active.get("artifact_sha256"),
        "label_map": dict(parsed.label_map),
        "runtime_mode": parsed.runtime_mode,
        "allow_partial_unified": allow_partial_unified,
    })
    return model_input, snapshot_model, None


def _configured_custom_model(
    environment: Optional[Mapping[str, str]] = None,
    data_root: Optional[Path] = None,
) -> Optional[Dict[str, Any]]:
    """Return the explicitly configured reviewed model as a migration bridge.

    Older BAI-KIEM deployments intentionally used
    ``CUSTOM_AUGMENT_FORCE_DEFAULT=true``. Removing that switch before an
    equivalent ACTIVE DB row existed disabled the only reach-stacker model.
    This bridge remains fail-closed: it requires an in-data artifact, an exact
    labels manifest, and a passing saved base-regression gate. A model which
    misses only the generic quality threshold may be loaded for an explicitly
    approved manual video test when both its evaluation metadata and the
    deployment environment opt in.
    """
    values = os.environ if environment is None else environment
    if values.get("CUSTOM_AUGMENT_FORCE_DEFAULT", "false").strip().casefold() not in {"1", "true", "yes", "on"}:
        return None
    artifact_setting = values.get("CUSTOM_AUGMENT_ARTIFACT", "").strip()
    version_key = values.get("CUSTOM_AUGMENT_VERSION_KEY", "").strip()
    expected_sha256 = values.get("CUSTOM_AUGMENT_SHA256", "").strip().casefold()
    if (
        not artifact_setting
        or not version_key
        or len(expected_sha256) != 64
        or any(character not in "0123456789abcdef" for character in expected_sha256)
    ):
        logger.error("Configured custom model requires CUSTOM_AUGMENT_ARTIFACT, VERSION_KEY and SHA256")
        return None

    root = (data_root or (Path(__file__).resolve().parents[2] / "data")).resolve()
    configured_path = Path(artifact_setting)
    artifact = configured_path.resolve() if configured_path.is_absolute() else (root / configured_path).resolve()
    if root not in artifact.parents or not artifact.is_file():
        logger.error("Configured custom artifact is outside backend/data or missing: %s", artifact)
        return None

    labels_path = artifact.parent / "labels.json"
    evaluation_path = artifact.parent / "evaluation.json"
    try:
        labels = json.loads(labels_path.read_text(encoding="utf-8"))
        evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("Configured custom model metadata is unreadable: %s", exc)
        return None
    if not isinstance(labels, dict) or not labels:
        logger.error("Configured custom labels manifest is empty or invalid: %s", labels_path)
        return None
    quality_gate = evaluation.get("qualityGate") if isinstance(evaluation, dict) else None
    base_regression = evaluation.get("baseRegression") if isinstance(evaluation, dict) else None
    manual_candidate = (
        values.get("CUSTOM_AUGMENT_MANUAL_CANDIDATE", "false").strip().casefold()
        in {"1", "true", "yes", "on"}
        and isinstance(evaluation, dict)
        and evaluation.get("manualTestApproved") is True
    )
    if (
        not isinstance(quality_gate, dict)
        or (quality_gate.get("passed") is not True and not manual_candidate)
    ):
        logger.error("Configured custom model has no passing quality gate: %s", evaluation_path)
        return None
    if not isinstance(base_regression, dict) or base_regression.get("passed") is not True:
        logger.error("Configured custom model has no passing base regression gate: %s", evaluation_path)
        return None
    warning_key = (version_key, expected_sha256)
    if (
        manual_candidate
        and quality_gate.get("passed") is not True
        and warning_key not in _WARNED_MANUAL_CANDIDATES
    ):
        _WARNED_MANUAL_CANDIDATES.add(warning_key)
        logger.warning(
            "Loading explicitly approved manual-test candidate despite its generic quality gate: %s",
            evaluation_path,
        )

    digest = hashlib.sha256()
    try:
        with artifact.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        logger.error("Configured custom model artifact is unreadable: %s", exc)
        return None
    if digest.hexdigest() != expected_sha256:
        logger.error("Configured custom model checksum does not match CUSTOM_AUGMENT_SHA256: %s", artifact)
        return None
    runtime_mode = evaluation.get("runtimeMode", "SUPPLEMENTAL")
    if runtime_mode not in {"SUPPLEMENTAL", "UNIFIED"}:
        logger.error("Configured custom model has invalid runtimeMode: %r", runtime_mode)
        return None
    return {
        "version_key": version_key,
        "artifact_path": str(artifact),
        "artifact_sha256": expected_sha256,
        "evaluation_metrics": {
            "labelMap": labels,
            "runtimeMode": runtime_mode,
            "manualProductionApproval": evaluation.get("manualProductionApproval"),
        },
    }


class ZoneSynchronizer:
    """Poll the DB while retaining the last known-good snapshot on failure."""

    def __init__(self, camera_id: str = "BAI-KIEM", sync_interval: float = 5.0):
        self.camera_id = camera_id
        self.sync_interval = sync_interval
        self._snapshot = ZoneSnapshot()
        self._lock = asyncio.Lock()
        self._running = False
        self._task: Optional[asyncio.Task] = None

    def get_snapshot(self) -> ZoneSnapshot:
        """Return the current atomic snapshot synchronously."""
        return self._snapshot

    async def refresh_now(self) -> bool:
        """Refresh the complete detection-control snapshot.

        A failed database read does not partially apply any data: consumers keep
        the exact prior snapshot object, including its active-model routing.
        """
        try:
            raw_zones, raw_labels, raw_active = await asyncio.gather(
                get_active_zones_by_camera(self.camera_id),
                get_all_object_labels(),
                get_active_custom_model(),
            )
            if raw_active is None:
                raw_active = _configured_custom_model()
            active_model_input, active_model, active_manifest_error = _normalize_active_model(raw_active)
            DetectionInputValidationError, _, resolve_label_capability = _taxonomy_api()

            if active_model_input is not None and active_model_input.get("runtimeMode") == "UNIFIED":
                incomplete_labels: list[str] = []
                for index, raw_label in enumerate(raw_labels):
                    try:
                        coverage = resolve_label_capability(
                            {
                                "vietnameseName": raw_label.get("vietnamese_name"),
                                "baseClass": raw_label.get("base_class"),
                            },
                            active_model_input,
                        )
                    except DetectionInputValidationError:
                        continue
                    if coverage.reason_code == "UNIFIED_CLASS_NOT_IN_ACTIVE_MODEL":
                        raw_name = raw_label.get("vietnamese_name")
                        incomplete_labels.append(raw_name.strip() if isinstance(raw_name, str) else f"#{index}")
                allow_partial_unified = bool(
                    active_model is not None
                    and active_model.get("allow_partial_unified") is True
                )
                if incomplete_labels and not allow_partial_unified:
                    active_manifest_error = (
                        "UNIFIED model does not cover registry labels: "
                        + ", ".join(incomplete_labels[:5])
                    )
                    active_model_input = None
                    active_model = None
                elif incomplete_labels:
                    version_key = str(active_model_input.get("versionKey") or "unknown")
                    warning_key = (version_key, tuple(sorted(incomplete_labels)))
                    if warning_key not in _WARNED_PARTIAL_UNIFIED:
                        _WARNED_PARTIAL_UNIFIED.add(warning_key)
                        logger.warning(
                            "[%s] Owner-approved partial UNIFIED coverage; unavailable labels: %s",
                            self.camera_id,
                            ", ".join(incomplete_labels[:5]),
                        )

            # The registry is the sole whitelist. Do not infer classes from
            # Vietnamese display names; the shared taxonomy validates stored
            # base_class values and records every diagnostic result.
            class_map: Dict[str, List[str]] = {}
            capabilities: Dict[str, Mapping[str, Any]] = {}
            coco_classes: set[str] = set()
            custom_classes: set[str] = set()
            for index, raw_label in enumerate(raw_labels):
                label = dict(raw_label)
                raw_name = label.get("vietnamese_name")
                display_name = raw_name.strip() if isinstance(raw_name, str) else ""
                diagnostic_key = display_name or f"__invalid_label_{index}"
                try:
                    capability = resolve_label_capability(
                        {
                            "vietnameseName": raw_name,
                            "baseClass": label.get("base_class"),
                        },
                        active_model_input,
                    ).as_dict()
                    # COCO remains safe when the custom manifest is malformed;
                    # custom labels receive an explicit diagnostic instead of a
                    # misleading "no active model" result.
                    if active_manifest_error and capability["detectionSource"] != "COCO":
                        capability = _unavailable_capability(
                            canonical_class=capability["canonicalClass"],
                            reason_code="INVALID_ACTIVE_MANIFEST",
                            reason_text=active_manifest_error,
                        )
                except DetectionInputValidationError as exc:
                    capability = _unavailable_capability(
                        canonical_class=None,
                        reason_code="INVALID_REGISTRY_LABEL",
                        reason_text=f"Nhãn registry không hợp lệ: {exc}",
                    )

                capabilities[diagnostic_key] = _freeze(capability)
                canonical_class = capability["canonicalClass"]
                if not capability["isDetectable"] or not isinstance(canonical_class, str) or not display_name:
                    continue
                class_map.setdefault(canonical_class, []).append(display_name)
                if capability["detectionSource"] == "COCO":
                    coco_classes.add(canonical_class)
                elif capability["detectionSource"] == "CUSTOM":
                    custom_classes.add(canonical_class)

            frozen_class_map = MappingProxyType({
                canonical_class: tuple(sorted(set(names)))
                for canonical_class, names in class_map.items()
            })

            cleaned_zones: List[Mapping[str, Any]] = []
            for zone in raw_zones:
                cleaned_zones.append(_freeze({
                    "id": str(zone["id"]),
                    "name": zone.get("name", "Zone"),
                    "polygon": zone.get("polygon_points", []),
                    "polygon_points": zone.get("polygon_points", []),
                    "ruleType": zone.get("rule_type", "PROHIBIT_SPECIFIED"),
                    "rule_type": zone.get("rule_type", "PROHIBIT_SPECIFIED"),
                    "targetLabels": zone.get("target_labels", []),
                    "target_labels": zone.get("target_labels", []),
                    "isActive": zone.get("is_active", True),
                }))

            new_snapshot = ZoneSnapshot(
                zones=tuple(cleaned_zones),
                class_to_labels=frozen_class_map,
                all_labels=tuple(_freeze(dict(label)) for label in raw_labels),
                capabilities_by_label=MappingProxyType(capabilities),
                coco_classes=frozenset(coco_classes),
                custom_classes=frozenset(custom_classes),
                active_model=active_model,
            )

            async with self._lock:
                self._snapshot = new_snapshot

            logger.debug(
                "[%s] Zone sync updated: %d active zones, %d detectable classes",
                self.camera_id,
                len(cleaned_zones),
                len(frozen_class_map),
            )
            return True
        except Exception as exc:
            logger.warning(
                "[%s] Failed to refresh zone/label snapshot from database (%s). Preserving existing snapshot.",
                self.camera_id,
                exc,
            )
            return False

    async def _sync_loop(self) -> None:
        """Background polling loop."""
        logger.info("[%s] Starting zone synchronizer loop (interval: %.1fs)...", self.camera_id, self.sync_interval)
        while self._running:
            await self.refresh_now()
            try:
                await asyncio.sleep(self.sync_interval)
            except asyncio.CancelledError:
                break
        logger.info("[%s] Zone synchronizer loop stopped.", self.camera_id)

    def start(self) -> None:
        """Start background polling task."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._sync_loop())

    async def stop(self) -> None:
        """Stop background polling task."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await asyncio.wait_for(self._task, timeout=1.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
            self._task = None
