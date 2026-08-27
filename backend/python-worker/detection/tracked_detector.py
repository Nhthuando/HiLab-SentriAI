"""Registry-controlled YOLO11 + ByteTrack detector for the Area monitor.

The Area worker must never infer its business ontology from model prompts,
sample counts, box geometry, or a local fallback artifact.  This module accepts
one immutable control snapshot from :mod:`zone.zone_sync` and emits only the
canonical classes the snapshot authorizes.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

import numpy as np
from ultralytics import YOLO

from detection.detector import COCO_VIETNAMESE_MAPPING, YoloDetector
from detection.policy import DetectionPolicy, TemporalConfirmationWindow
from detection.roi_inference import RoiConfigurationError, RoiScheduler, class_aware_deduplicate
from detection.taxonomy import DETECTION_TAXONOMY, normalize_canonical_class

logger = logging.getLogger("sentriai.detection.tracked")

DEFAULT_AREA_YOLO_MODEL = "yolo11n.pt"
DEFAULT_CUSTOM_INTERVAL = 1
DEFAULT_CUSTOM_MATCH_OVERLAP = 0.20
DEFAULT_CUSTOM_HOLD_OPPORTUNITIES = 8
DEFAULT_CUSTOM_BOX_EMA_ALPHA = 0.65
DEFAULT_CUSTOM_BASE_HOLD_FRAMES = 12
DEFAULT_CUSTOM_MAX_EDGE_STEP_RATIO = 0.015
PERSON_IN_REACH_MAX_CONFIDENCE = 0.50
PERSON_IN_REACH_MIN_CONTAINMENT = 0.90
PERSON_IN_REACH_MAX_AREA_RATIO = 0.35
PERSON_IN_REACH_MIN_BOTTOM_GAP_RATIO = 0.12
ROI_STATE_MAX_IDLE_OPPORTUNITIES = 9
ROI_CLOCK_DOMAIN = "roi_opportunity"
FULL_FRAME_CUSTOM_CLOCK_DOMAIN = "full_frame_custom_opportunity"
GENERIC_VEHICLE_CLASSES = frozenset({"truck", "bus", "car"})


def _coco_class_ids() -> Mapping[str, int]:
    value = DETECTION_TAXONOMY["cocoClasses"]
    if not isinstance(value, Mapping):  # taxonomy validates this at import time
        raise RuntimeError("Detection taxonomy has no valid COCO class map")
    return {str(name): int(class_id) for name, class_id in value.items()}


COCO_CLASS_IDS = _coco_class_ids()


class TrackedYoloDetector(YoloDetector):
    """Run registry-whitelisted COCO detection and active custom refinement.

    Base inference remains responsible for ByteTrack IDs.  A custom result may
    refine only an overlapping generic vehicle after two hits in the latest
    three eligible custom-inference frames.  It cannot create a violation from
    a one-frame or low-confidence guess.
    """

    def __init__(
        self,
        model_path: Optional[str] = None,
        conf_threshold: Optional[float] = None,
        tracker: str = "bytetrack.yaml",
        target_classes: Optional[Sequence[str]] = None,
    ) -> None:
        configured_kind = os.getenv("AREA_DETECTOR_KIND", "yolo11").strip().casefold()
        if configured_kind not in {"", "yolo11", "yolo"}:
            logger.warning(
                "Ignoring unsupported AREA_DETECTOR_KIND=%s; Area uses registry-filtered YOLO11 only.",
                configured_kind,
            )
        self.detector_kind = "yolo11"
        self.tracker = tracker
        self.inference_size = self._read_positive_int("AREA_INFERENCE_SIZE", default=896, minimum=640)
        # The supplemental custom model has a different accuracy/latency
        # Pareto point from the base COCO tracker.  Keep the legacy behaviour
        # unless explicitly configured, while allowing custom inference to
        # run at a smaller validated size without reducing base-class recall.
        self.custom_inference_size = self._read_positive_int(
            "AREA_CUSTOM_INFERENCE_SIZE", default=self.inference_size, minimum=640,
        )
        # Keep the existing environment contract, but translate it to the
        # current Ultralytics precision API. Passing the deprecated ``half``
        # keyword (even as False) emits one warning per inference call.
        self.inference_quantize = (
            16
            if os.getenv("AREA_INFERENCE_HALF", "false").strip().casefold() in {"1", "true", "yes", "on"}
            else None
        )
        self.last_roi_latency_ms = 0.0
        self._policy = DetectionPolicy.from_environment()
        self._enabled_coco_classes: frozenset[str] = frozenset()
        self._enabled_custom_classes: frozenset[str] = frozenset()
        self._runtime_mode = "SUPPLEMENTAL"
        self._base_track_state: Dict[int, Dict[str, Any]] = {}
        self._base_frame_index = 0
        self._custom_model: Optional[YOLO] = None
        self._custom_version_key: Optional[str] = None
        self._custom_artifact_path: Optional[str] = None
        self._custom_artifact_sha256: Optional[str] = None
        self._custom_label_map: Dict[str, str] = {}
        self._custom_frame_index = 0
        self._roi_opportunity_index = 0
        self._custom_windows: Dict[str, TemporalConfirmationWindow] = {}
        self._custom_candidates: Dict[str, Dict[str, Any]] = {}
        self._roi_base_candidates: Dict[str, Dict[str, Any]] = {}
        self._next_synthetic_track_id = -1
        self._custom_interval = self._read_positive_int(
            "CUSTOM_AUGMENT_INTERVAL", default=DEFAULT_CUSTOM_INTERVAL, minimum=1
        )
        self._custom_match_overlap = self._read_ratio(
            "CUSTOM_AUGMENT_MATCH_OVERLAP", default=DEFAULT_CUSTOM_MATCH_OVERLAP
        )
        self._custom_hold_opportunities = self._read_positive_int(
            "CUSTOM_TRACK_HOLD_OPPORTUNITIES",
            default=DEFAULT_CUSTOM_HOLD_OPPORTUNITIES,
            minimum=1,
        )
        self._custom_box_ema_alpha = max(
            0.05,
            self._read_ratio(
                "CUSTOM_TRACK_BOX_EMA_ALPHA",
                default=DEFAULT_CUSTOM_BOX_EMA_ALPHA,
            ),
        )
        self._custom_base_hold_frames = self._read_positive_int(
            "CUSTOM_TRACK_BASE_HOLD_FRAMES",
            default=DEFAULT_CUSTOM_BASE_HOLD_FRAMES,
            minimum=1,
        )
        self._custom_max_edge_step_ratio = max(
            0.001,
            self._read_ratio(
                "CUSTOM_TRACK_MAX_EDGE_STEP_RATIO",
                default=DEFAULT_CUSTOM_MAX_EDGE_STEP_RATIO,
            ),
        )
        self._reset_tracker_on_next_frame = False
        self._detection_control_fingerprint: Optional[tuple[object, ...]] = None
        try:
            self._roi_scheduler = RoiScheduler.from_environment()
        except RoiConfigurationError:
            # Invalid ROI geometry can accidentally broaden inference. Treat it
            # as a startup configuration error instead of silently changing it.
            logger.exception("Invalid Area ROI configuration")
            raise

        # YoloDetector loads a local YOLO11 model.  The target list supplied to
        # its initializer is only a defensive COCO default; ``track`` applies
        # the real snapshot whitelist on every frame.
        configured_model = model_path or os.getenv("AREA_DETECTOR_MODEL") or DEFAULT_AREA_YOLO_MODEL
        super().__init__(
            model_path=configured_model,
            conf_threshold=conf_threshold if conf_threshold is not None else self._policy.base_default.continuation,
            target_classes=list(target_classes or tuple(COCO_CLASS_IDS)),
        )

    @staticmethod
    def _read_positive_int(name: str, *, default: int, minimum: int) -> int:
        raw = os.getenv(name)
        if raw is None or not raw.strip():
            return default
        try:
            return max(minimum, int(raw))
        except ValueError:
            logger.warning("Ignoring invalid %s=%r; using %s", name, raw, default)
            return default

    @staticmethod
    def _read_ratio(name: str, *, default: float) -> float:
        raw = os.getenv(name)
        if raw is None or not raw.strip():
            return default
        try:
            return min(1.0, max(0.0, float(raw)))
        except ValueError:
            logger.warning("Ignoring invalid %s=%r; using %.2f", name, raw, default)
            return default

    def configure_detection_control(
        self,
        *,
        coco_classes: frozenset[str],
        custom_classes: frozenset[str],
        active_model: dict[str, object] | None,
    ) -> None:
        """Apply one complete registry/model capability snapshot atomically."""
        runtime_mode = "SUPPLEMENTAL"
        if active_model is not None and active_model.get("runtime_mode") == "UNIFIED":
            runtime_mode = "UNIFIED"
        normalized_coco_classes = frozenset(
            canonical
            for raw_class in coco_classes
            if isinstance(raw_class, str)
            and (canonical := normalize_canonical_class(raw_class)) in COCO_CLASS_IDS
        )
        normalized_custom_classes = frozenset(
            canonical
            for raw_class in custom_classes
            if isinstance(raw_class, str)
            and (canonical := normalize_canonical_class(raw_class)) is not None
        )
        enabled_coco_classes = (
            frozenset()
            if runtime_mode == "UNIFIED"
            else normalized_coco_classes
        )
        enabled_custom_classes = (
            normalized_coco_classes | normalized_custom_classes
            if runtime_mode == "UNIFIED"
            else frozenset(canonical for canonical in normalized_custom_classes if canonical not in COCO_CLASS_IDS)
        )
        version_key: Optional[str] = None
        artifact_path: Optional[str] = None
        artifact_sha256: Optional[str] = None
        normalized_labels: Dict[str, str] = {}
        if active_model is not None and enabled_custom_classes:
            raw_version_key = active_model.get("version_key")
            raw_artifact_path = active_model.get("artifact_path")
            raw_artifact_sha256 = active_model.get("artifact_sha256")
            label_map = active_model.get("label_map")
            if (
                isinstance(raw_version_key, str)
                and isinstance(raw_artifact_path, str)
                and isinstance(raw_artifact_sha256, str)
                and len(raw_artifact_sha256) == 64
                and all(character in "0123456789abcdef" for character in raw_artifact_sha256.casefold())
                and isinstance(label_map, Mapping)
            ):
                version_key = raw_version_key
                artifact_path = raw_artifact_path
                artifact_sha256 = raw_artifact_sha256.casefold()
                for raw_label, raw_class in label_map.items():
                    canonical = normalize_canonical_class(str(raw_class))
                    if (
                        canonical is not None
                        and canonical in enabled_custom_classes
                        and (runtime_mode == "UNIFIED" or canonical not in COCO_CLASS_IDS)
                    ):
                        normalized_labels[str(raw_label)] = canonical
            else:
                logger.warning("Ignoring malformed active custom model control snapshot.")

        fingerprint: tuple[object, ...] = (
            runtime_mode,
            tuple(sorted(enabled_coco_classes)),
            tuple(sorted(enabled_custom_classes)),
            version_key,
            artifact_path,
            artifact_sha256,
            tuple(sorted(normalized_labels.items())),
        )
        if fingerprint == getattr(self, "_detection_control_fingerprint", None):
            return

        self._enabled_coco_classes = enabled_coco_classes
        self._enabled_custom_classes = enabled_custom_classes
        self._runtime_mode = runtime_mode
        self.reset_tracking()
        self.configure_custom_model(
            version_key,
            artifact_path,
            normalized_labels,
            enabled_custom_classes,
            artifact_sha256=artifact_sha256,
            allow_coco=runtime_mode == "UNIFIED",
        )
        if runtime_mode == "UNIFIED" and self._custom_model is None:
            # A checksum-valid file can still be unreadable by Ultralytics.
            # Unified mode must never turn that load failure into a blank
            # camera: retain the base COCO portion of the registry as rollback.
            self._runtime_mode = "SUPPLEMENTAL"
            self._enabled_coco_classes = frozenset(
                canonical for canonical in enabled_custom_classes if canonical in COCO_CLASS_IDS
            )
            self._enabled_custom_classes = frozenset()
            logger.error(
                "Unified Area model could not be loaded; falling back to base COCO classes: %s",
                sorted(self._enabled_coco_classes),
            )
        self._detection_control_fingerprint = fingerprint
        logger.info(
            "Area detection control applied: mode=%s COCO=%s custom=%s model=%s base-init=%.2f base-continue=%.2f",
            runtime_mode,
            sorted(enabled_coco_classes),
            sorted(enabled_custom_classes),
            version_key or "none",
            self._policy.base_default.initiation,
            self._policy.base_default.continuation,
        )

    def configure_custom_model(
        self,
        version_key: Optional[str],
        artifact_path: Optional[str],
        label_map: Mapping[str, str],
        enabled_classes: frozenset[str],
        artifact_sha256: Optional[str] = None,
        allow_coco: bool = False,
    ) -> None:
        """Load exactly the ACTIVE custom model, or fail closed to base-only."""
        normalized_labels: Dict[str, str] = {}
        for raw_label, raw_class in label_map.items():
            canonical = normalize_canonical_class(str(raw_class))
            if canonical is None or (canonical in COCO_CLASS_IDS and not allow_coco) or canonical not in enabled_classes:
                continue
            normalized_labels[str(raw_label)] = canonical

        desired = (
            version_key,
            artifact_path,
            artifact_sha256,
            tuple(sorted(normalized_labels.items())),
            tuple(sorted(enabled_classes)),
            allow_coco,
        )
        current = (
            self._custom_version_key,
            getattr(self, "_custom_artifact_path", None),
            getattr(self, "_custom_artifact_sha256", None),
            tuple(sorted(self._custom_label_map.items())),
            tuple(sorted(self._enabled_custom_classes)),
            getattr(self, "_runtime_mode", "SUPPLEMENTAL") == "UNIFIED",
        )
        if desired == current:
            return

        if not version_key or not artifact_path or not artifact_sha256 or not normalized_labels or not enabled_classes:
            self._unload_custom_model()
            return

        candidate = Path(artifact_path)
        if not candidate.is_file():
            logger.error("ACTIVE custom artifact is unavailable; disabling custom detection: %s", candidate)
            self._unload_custom_model()
            return
        try:
            model = YOLO(str(candidate))
            model.to(self.device)
        except Exception as exc:  # model corruption / runtime error must fail closed
            logger.error("Unable to load ACTIVE custom model %s: %s", version_key, exc)
            self._unload_custom_model()
            return

        self._custom_model = model
        self._custom_version_key = version_key
        self._custom_artifact_path = str(candidate)
        self._custom_artifact_sha256 = artifact_sha256
        self._custom_label_map = normalized_labels
        self._custom_windows.clear()
        self._custom_candidates.clear()
        logger.info("Loaded ACTIVE custom model %s for %s", version_key, sorted(set(normalized_labels.values())))

    def _unload_custom_model(self) -> None:
        self._custom_model = None
        self._custom_version_key = None
        self._custom_artifact_path = None
        self._custom_artifact_sha256 = None
        self._custom_label_map = {}
        self._custom_windows.clear()
        self._custom_candidates.clear()
        logger.info("Custom Area detection disabled; registry-filtered COCO remains active.")

    @staticmethod
    def _canonicalize_detection_class(class_name: str) -> tuple[str, Optional[str]]:
        """Normalize syntax only; never coerce one semantic class into another."""
        canonical = normalize_canonical_class(class_name)
        return (canonical or "", None)

    @staticmethod
    def _bbox_from_detection(detection: Mapping[str, Any]) -> Optional[List[int]]:
        bbox = detection.get("bbox")
        if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
            return None
        try:
            return [int(round(float(value))) for value in bbox[:4]]
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _normalized_bbox(bbox: List[int], width: int, height: int) -> List[float]:
        return [
            round(bbox[0] / width, 4),
            round(bbox[1] / height, 4),
            round(bbox[2] / width, 4),
            round(bbox[3] / height, 4),
        ]

    @staticmethod
    def _iou(first: List[int], second: List[int]) -> float:
        ax1, ay1, ax2, ay2 = first
        bx1, by1, bx2, by2 = second
        intersection = max(0, min(ax2, bx2) - max(ax1, bx1)) * max(0, min(ay2, by2) - max(ay1, by1))
        if not intersection:
            return 0.0
        first_area = max(1, (ax2 - ax1) * (ay2 - ay1))
        second_area = max(1, (bx2 - bx1) * (by2 - by1))
        return intersection / (first_area + second_area - intersection)

    @staticmethod
    def _center_distance_ratio(first: List[int], second: List[int]) -> float:
        first_center = ((first[0] + first[2]) / 2.0, (first[1] + first[3]) / 2.0)
        second_center = ((second[0] + second[2]) / 2.0, (second[1] + second[3]) / 2.0)
        distance = float(np.hypot(first_center[0] - second_center[0], first_center[1] - second_center[1]))
        first_scale = max(1.0, ((first[2] - first[0]) + (first[3] - first[1])) / 2.0)
        second_scale = max(1.0, ((second[2] - second[0]) + (second[3] - second[1])) / 2.0)
        return distance / first_scale

    def _new_base_detection(
        self,
        *,
        bbox: List[int],
        width: int,
        height: int,
        canonical_class: str,
        confidence: float,
        track_id: Optional[int],
    ) -> Dict[str, Any]:
        return {
            "trackId": track_id,
            "bbox": bbox,
            "normalized_bbox": self._normalized_bbox(bbox, width, height),
            "class": canonical_class,
            "canonicalClass": canonical_class,
            "label": COCO_VIETNAMESE_MAPPING.get(canonical_class, canonical_class),
            "confidence": round(confidence, 3),
            "source": "COCO",
            "customConfirmed": False,
            "canInitiate": False,
            "canContinue": False,
        }

    def _filter_and_gate_base(self, detections: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Apply continuation/initiation policy without rewriting semantic classes."""
        self._base_frame_index += 1
        output: List[Dict[str, Any]] = []
        for detection in detections:
            canonical = str(detection.get("canonicalClass") or detection.get("class") or "")
            if canonical not in self._enabled_coco_classes:
                continue
            confidence = float(detection.get("confidence") or 0.0)
            raw_track_id = detection.get("trackId")
            track_id: Optional[int]
            try:
                track_id = int(raw_track_id) if raw_track_id is not None else None
            except (TypeError, ValueError):
                track_id = None

            state = self._base_track_state.get(track_id) if track_id is not None else None
            previously_confirmed = bool(state and state.get("confirmed") and state.get("class") == canonical)
            can_continue = self._policy.can_continue("base", canonical, confidence) and previously_confirmed
            can_initiate = self._policy.can_initiate("base", canonical, confidence)
            if not can_initiate and not can_continue:
                continue

            if track_id is not None:
                self._base_track_state[track_id] = {
                    "class": canonical,
                    "confirmed": previously_confirmed or can_initiate,
                    "last_seen": self._base_frame_index,
                }
            detection["trackId"] = track_id
            detection["canInitiate"] = can_initiate
            detection["canContinue"] = can_continue or can_initiate
            output.append(detection)

        stale_before = self._base_frame_index - 120
        for track_id, state in list(self._base_track_state.items()):
            if int(state.get("last_seen", self._base_frame_index)) < stale_before:
                self._base_track_state.pop(track_id, None)
        return output

    def _custom_class_for_model_label(self, raw_label: object) -> Optional[str]:
        if not isinstance(raw_label, str):
            return None
        direct = self._custom_label_map.get(raw_label)
        if direct is not None:
            return direct
        folded = raw_label.casefold()
        for label, canonical in self._custom_label_map.items():
            if label.casefold() == folded:
                return canonical
        return None

    def _collect_custom_detections(
        self,
        frame: np.ndarray,
        width: int,
        height: int,
        *,
        inference_size: Optional[int] = None,
        suppress_tracking_callbacks: bool = False,
    ) -> List[Dict[str, Any]]:
        if self._custom_model is None or not self._enabled_custom_classes:
            return []
        continuation_threshold = min(
            self._policy.thresholds_for("custom", canonical).continuation
            for canonical in self._enabled_custom_classes
        )
        results = self._predict_without_tracking_callbacks(
            self._custom_model,
            frame,
            suppress=suppress_tracking_callbacks,
            conf=continuation_threshold,
            imgsz=inference_size or self.custom_inference_size,
            device=self.device,
            quantize=getattr(self, "inference_quantize", None) if self.device != "cpu" else None,
            verbose=False,
        )
        detections: List[Dict[str, Any]] = []
        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue
            for index in range(len(boxes)):
                raw_label = str(self._custom_model.names.get(int(boxes.cls[index].item()), ""))
                canonical = self._custom_class_for_model_label(raw_label)
                if canonical is None or canonical not in self._enabled_custom_classes:
                    continue
                confidence = float(boxes.conf[index].item())
                if not self._policy.can_continue("custom", canonical, confidence):
                    continue
                xyxy = boxes.xyxy[index].cpu().numpy().tolist()
                bbox = [
                    max(0, min(width - 1, int(xyxy[0]))),
                    max(0, min(height - 1, int(xyxy[1]))),
                    max(1, min(width, int(xyxy[2]))),
                    max(1, min(height, int(xyxy[3]))),
                ]
                if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
                    continue
                detections.append({
                    "trackId": None,
                    "bbox": bbox,
                    "normalized_bbox": self._normalized_bbox(bbox, width, height),
                    "class": canonical,
                    "canonicalClass": canonical,
                    "label": raw_label,
                    "confidence": round(confidence, 3),
                    "source": "CUSTOM",
                    "candidateVersion": self._custom_version_key,
                    "customConfirmed": False,
                    "canInitiate": False,
                    "canContinue": False,
                })
        return self._same_class_nms(detections)

    @staticmethod
    def _predict_without_tracking_callbacks(
        model: Any,
        frame: np.ndarray,
        *,
        suppress: bool,
        **kwargs: Any,
    ) -> Any:
        """Run tile prediction without advancing the full-frame ByteTrack.

        Ultralytics attaches tracker callbacks to the model instance after the
        first ``track`` call. A later plain ``model(tile)`` would otherwise feed
        that crop into the same tracker and corrupt full-frame continuity.
        """
        callbacks = getattr(model, "callbacks", None)
        if not suppress or not isinstance(callbacks, dict):
            return model(frame, **kwargs)

        saved: Dict[str, List[Any]] = {}
        tracker_events = ("on_predict_start", "on_predict_postprocess_end")
        try:
            for event in tracker_events:
                event_callbacks = callbacks.get(event)
                if not isinstance(event_callbacks, list):
                    continue
                saved[event] = event_callbacks
                callbacks[event] = [
                    callback
                    for callback in event_callbacks
                    if not TrackedYoloDetector._is_ultralytics_tracker_callback(callback)
                ]
            return model(frame, **kwargs)
        finally:
            for event, event_callbacks in saved.items():
                callbacks[event] = event_callbacks

    @staticmethod
    def _is_ultralytics_tracker_callback(callback: Any) -> bool:
        function = getattr(callback, "func", callback)
        return (
            getattr(function, "__module__", "") == "ultralytics.trackers.track"
            and getattr(function, "__name__", "") in {"on_predict_start", "on_predict_postprocess_end"}
        )

    def _collect_roi_base_detections(self, frame: np.ndarray, width: int, height: int) -> List[Dict[str, Any]]:
        """Run supplemental, non-tracking COCO inference on one ROI tile."""
        if self.model is None or not self._enabled_coco_classes:
            return []
        class_ids = [COCO_CLASS_IDS[name] for name in sorted(self._enabled_coco_classes)]
        continuation_threshold = min(
            self._policy.thresholds_for("base", canonical).continuation
            for canonical in self._enabled_coco_classes
        )
        results = self._predict_without_tracking_callbacks(
            self.model,
            frame,
            suppress=True,
            conf=continuation_threshold,
            classes=class_ids,
            imgsz=getattr(getattr(self, "_roi_scheduler", None), "tile_size", 640),
            device=self.device,
            quantize=getattr(self, "inference_quantize", None) if self.device != "cpu" else None,
            verbose=False,
        )
        detections: List[Dict[str, Any]] = []
        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue
            for index in range(len(boxes)):
                raw_class = str(self.model.names.get(int(boxes.cls[index].item()), ""))
                canonical, _ = self._canonicalize_detection_class(raw_class)
                if canonical not in self._enabled_coco_classes:
                    continue
                xyxy = boxes.xyxy[index].cpu().numpy().tolist()
                bbox = [
                    max(0, min(width - 1, int(xyxy[0]))),
                    max(0, min(height - 1, int(xyxy[1]))),
                    max(1, min(width, int(xyxy[2]))),
                    max(1, min(height, int(xyxy[3]))),
                ]
                if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
                    continue
                detections.append(self._new_base_detection(
                    bbox=bbox,
                    width=width,
                    height=height,
                    canonical_class=canonical,
                    confidence=float(boxes.conf[index].item()),
                    track_id=None,
                ))
        return self._same_class_nms(detections)

    def _collect_roi_candidates(self, frame: np.ndarray) -> List[Dict[str, Any]]:
        """Execute configured ROI callbacks without changing the default path."""
        scheduler = getattr(self, "_roi_scheduler", None)
        if scheduler is None:
            return []
        callbacks: Dict[str, Any] = {}
        if self.model is not None and self._enabled_coco_classes:
            callbacks["base"] = lambda crop: self._collect_roi_base_detections(
                crop, crop.shape[1], crop.shape[0]
            )
        if self._custom_model is not None and self._enabled_custom_classes:
            callbacks["custom"] = lambda crop: self._collect_custom_detections(
                crop,
                crop.shape[1],
                crop.shape[0],
                inference_size=scheduler.tile_size,
                suppress_tracking_callbacks=True,
            )
        if not callbacks:
            return []
        try:
            return scheduler.infer(frame, frame_index=self._base_frame_index, callbacks=callbacks)
        except Exception as exc:
            logger.warning("Area ROI inference failed; keeping full-frame detections: %s", exc)
            return []
        finally:
            # This clock advances even when an ROI opportunity produces no
            # detections (or one detector callback fails). State expiry must
            # therefore not be inferred from candidate payloads.
            self._roi_opportunity_index = max(
                getattr(self, "_roi_opportunity_index", 0),
                scheduler.inference_index,
            )

    def _roi_base_evidence_key(self, detection: Mapping[str, Any]) -> str:
        canonical = str(detection.get("canonicalClass") or detection.get("class") or "")
        bbox = self._bbox_from_detection(detection)
        if bbox is not None:
            for key, candidate in self._roi_base_candidates.items():
                if candidate.get("class") != canonical:
                    continue
                previous_bbox = self._bbox_from_detection(candidate)
                if previous_bbox and (
                    self._iou(bbox, previous_bbox) >= self._custom_match_overlap
                    or self._center_distance_ratio(bbox, previous_bbox) <= 0.80
                ):
                    return key
        return f"roi-base:{self._next_synthetic_track_id}:{canonical}"

    def _merge_roi_base_candidates(
        self,
        detections: List[Dict[str, Any]],
        candidates: Iterable[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Associate ROI COCO candidates while retaining full-frame track IDs."""
        candidate_list = list(candidates)
        candidate_clock = max(
            (
                int(candidate.get("roiInferenceIndex") or 0)
                for candidate in candidate_list
                if isinstance(candidate.get("roiInferenceIndex"), int)
                and not isinstance(candidate.get("roiInferenceIndex"), bool)
            ),
            default=0,
        )
        self._roi_opportunity_index = max(getattr(self, "_roi_opportunity_index", 0), candidate_clock)
        self._prune_roi_base_candidates(self._roi_opportunity_index)
        if not candidate_list:
            return detections
        additions: List[Dict[str, Any]] = []
        for candidate in candidate_list:
            canonical = str(candidate.get("canonicalClass") or candidate.get("class") or "")
            if canonical not in self._enabled_coco_classes:
                continue
            bbox = self._bbox_from_detection(candidate)
            if bbox is None:
                continue
            try:
                confidence = float(candidate.get("confidence") or 0.0)
                evidence_index = int(candidate.get("roiInferenceIndex") or 0)
            except (TypeError, ValueError):
                continue

            # A full-frame ByteTrack observation always owns identity. The ROI
            # duplicate is supplemental evidence and cannot replace that ID.
            matching_track = next((
                existing
                for existing in detections
                if str(existing.get("canonicalClass") or existing.get("class") or "") == canonical
                and (existing_bbox := self._bbox_from_detection(existing)) is not None
                and self._iou(bbox, existing_bbox) >= self._custom_match_overlap
            ), None)
            if matching_track is not None:
                continue
            key = self._roi_base_evidence_key(candidate)
            existing_record = self._roi_base_candidates.get(key)
            can_initiate = self._policy.can_initiate("base", canonical, confidence)
            can_continue = bool(
                existing_record
                and existing_record.get("trackId") is not None
                and self._policy.can_continue("base", canonical, confidence)
            )
            if not can_initiate and not can_continue:
                continue

            record = self._roi_base_candidates.setdefault(key, {})
            track_id = record.get("trackId")
            if track_id is None:
                track_id = self._next_synthetic_track_id
                self._next_synthetic_track_id -= 1
            record.update({
                "class": canonical,
                "bbox": bbox,
                "trackId": track_id,
                "last_seen": evidence_index,
            })
            output = dict(candidate)
            output.update({
                "trackId": int(track_id),
                "source": "COCO",
                "customConfirmed": False,
                "canInitiate": can_initiate,
                "canContinue": can_initiate or can_continue,
            })
            additions.append(output)
        return class_aware_deduplicate([*detections, *additions])

    def _prune_roi_base_candidates(self, opportunity_index: int) -> None:
        stale_before = opportunity_index - ROI_STATE_MAX_IDLE_OPPORTUNITIES
        for key, candidate in list(self._roi_base_candidates.items()):
            if int(candidate.get("last_seen", opportunity_index)) < stale_before:
                self._roi_base_candidates.pop(key, None)

    @staticmethod
    def _same_class_nms(detections: List[Dict[str, Any]], *, iou_threshold: float = 0.50) -> List[Dict[str, Any]]:
        """Deduplicate only exact canonical classes; never merge semantics."""
        kept: List[Dict[str, Any]] = []
        for candidate in sorted(detections, key=lambda item: float(item.get("confidence") or 0.0), reverse=True):
            bbox = TrackedYoloDetector._bbox_from_detection(candidate)
            if bbox is None:
                continue
            canonical = str(candidate.get("canonicalClass") or candidate.get("class") or "")
            if any(
                canonical == str(existing.get("canonicalClass") or existing.get("class") or "")
                and (existing_bbox := TrackedYoloDetector._bbox_from_detection(existing)) is not None
                and TrackedYoloDetector._iou(bbox, existing_bbox) >= iou_threshold
                for existing in kept
            ):
                continue
            kept.append(candidate)
        return kept

    def _best_generic_target(
        self,
        custom: Mapping[str, Any],
        base_detections: Iterable[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        custom_bbox = self._bbox_from_detection(custom)
        if custom_bbox is None:
            return None
        best: Optional[Dict[str, Any]] = None
        best_iou = 0.0
        for base in base_detections:
            base_class = str(base.get("canonicalClass") or base.get("class") or "")
            if base_class not in GENERIC_VEHICLE_CLASSES:
                continue
            base_bbox = self._bbox_from_detection(base)
            if base_bbox is None:
                continue
            overlap = self._iou(custom_bbox, base_bbox)
            if overlap >= self._custom_match_overlap and overlap > best_iou:
                best, best_iou = base, overlap
        return best

    def _custom_evidence_key(self, custom: Mapping[str, Any], target: Optional[Mapping[str, Any]]) -> str:
        """Associate custom evidence spatially, never through a generic base ID."""
        del target  # Base ByteTrack identity must not own a custom semantic track.
        canonical = str(custom.get("canonicalClass") or custom.get("class") or "")
        clock_domain = self._custom_clock_domain(custom)
        namespace = "roi:" if clock_domain == ROI_CLOCK_DOMAIN else ""
        bbox = self._bbox_from_detection(custom)
        evidence_frame = self._custom_clock_index(custom)
        best_key: Optional[str] = None
        best_rank = (-1.0, float("-inf"))
        if bbox is not None:
            for key, candidate in self._custom_candidates.items():
                if candidate.get("class") != canonical:
                    continue
                if candidate.get("clock_domain") != clock_domain:
                    continue
                # One custom record can match only one object in an inference
                # opportunity. This preserves identity when multiple machines
                # of the same class are visible.
                if int(candidate.get("last_seen", -1)) == evidence_frame:
                    continue
                previous_bbox = self._bbox_from_detection(candidate)
                if previous_bbox is None:
                    continue
                overlap = self._iou(bbox, previous_bbox)
                center_distance = self._center_distance_ratio(bbox, previous_bbox)
                if overlap < self._custom_match_overlap and center_distance > 0.80:
                    continue
                rank = (overlap, -center_distance)
                if rank > best_rank:
                    best_key, best_rank = key, rank
        if best_key is not None:
            return best_key

        track_id = self._next_synthetic_track_id
        self._next_synthetic_track_id -= 1
        key = f"{namespace}custom:{abs(track_id)}:{canonical}"
        self._custom_candidates[key] = {
            "class": canonical,
            "bbox": bbox,
            "last_seen": evidence_frame,
            "clock_domain": clock_domain,
            "trackId": track_id,
        }
        return key

    @staticmethod
    def _custom_clock_domain(custom: Mapping[str, Any]) -> str:
        return ROI_CLOCK_DOMAIN if custom.get("roiInferenceIndex") is not None else FULL_FRAME_CUSTOM_CLOCK_DOMAIN

    def _custom_clock_index(self, custom: Mapping[str, Any]) -> int:
        if self._custom_clock_domain(custom) == ROI_CLOCK_DOMAIN:
            return int(custom.get("roiInferenceIndex") or getattr(self, "_roi_opportunity_index", 0))
        return self._custom_frame_index

    @staticmethod
    def _bounded_normalized_box_step(
        previous: Sequence[float],
        current: Sequence[float],
        maximum_step: float,
    ) -> List[float]:
        return [
            min(1.0, max(0.0, float(old) + min(max(float(new) - float(old), -maximum_step), maximum_step)))
            for old, new in zip(previous, current)
        ]

    @staticmethod
    def _frame_dimensions_from_box(
        pixel_box: Sequence[float],
        normalized_box: Sequence[float],
    ) -> Optional[tuple[float, float]]:
        normalized_width = float(normalized_box[2]) - float(normalized_box[0])
        normalized_height = float(normalized_box[3]) - float(normalized_box[1])
        pixel_width = float(pixel_box[2]) - float(pixel_box[0])
        pixel_height = float(pixel_box[3]) - float(pixel_box[1])
        if normalized_width <= 0.0 or normalized_height <= 0.0 or pixel_width <= 0.0 or pixel_height <= 0.0:
            return None
        return pixel_width / normalized_width, pixel_height / normalized_height

    def _confirm_custom(self, custom: Dict[str, Any], target: Optional[Dict[str, Any]]) -> bool:
        canonical = str(custom["canonicalClass"])
        confidence = float(custom["confidence"])
        if not self._policy.can_continue("custom", canonical, confidence):
            return False
        key = self._custom_evidence_key(custom, target)
        window = self._custom_windows.setdefault(key, self._policy.new_custom_confirmation_window())
        clock_domain = self._custom_clock_domain(custom)
        evidence_frame = self._custom_clock_index(custom)
        record = self._custom_candidates.setdefault(key, {})
        raw_bbox = list(custom["bbox"])
        current_bbox = list(raw_bbox)
        previous_bbox = self._bbox_from_detection(record)
        current_normalized = list(custom.get("normalized_bbox") or ())
        previous_normalized = record.get("normalized_bbox")
        if (
            isinstance(previous_normalized, list)
            and len(previous_normalized) == 4
            and len(current_normalized) == 4
        ):
            alpha = getattr(self, "_custom_box_ema_alpha", DEFAULT_CUSTOM_BOX_EMA_ALPHA)
            current_normalized = [
                float(previous) * (1.0 - alpha) + float(current) * alpha
                for previous, current in zip(previous_normalized, current_normalized)
            ]
            current_normalized = self._bounded_normalized_box_step(
                previous_normalized,
                current_normalized,
                getattr(
                    self,
                    "_custom_max_edge_step_ratio",
                    DEFAULT_CUSTOM_MAX_EDGE_STEP_RATIO,
                ),
            )
            dimensions = self._frame_dimensions_from_box(raw_bbox, custom["normalized_bbox"])
            if dimensions is not None:
                frame_width, frame_height = dimensions
                current_bbox = [
                    int(round(current_normalized[0] * frame_width)),
                    int(round(current_normalized[1] * frame_height)),
                    int(round(current_normalized[2] * frame_width)),
                    int(round(current_normalized[3] * frame_height)),
                ]
        elif previous_bbox is not None:
            alpha = getattr(self, "_custom_box_ema_alpha", DEFAULT_CUSTOM_BOX_EMA_ALPHA)
            current_bbox = [
                int(round(previous * (1.0 - alpha) + current * alpha))
                for previous, current in zip(previous_bbox, current_bbox)
            ]
        confirmed_by_window = window.observe(key, frame_index=evidence_frame, matched=True)
        # Once promoted, a matching observation must never demote the record.
        # Expiry is controlled only by bounded missing opportunities below.
        confirmed = confirmed_by_window or record.get("confirmed") is True
        custom["_evidenceKey"] = key
        custom["bbox"] = current_bbox
        custom["normalized_bbox"] = current_normalized
        record.update({
            "class": canonical,
            "bbox": current_bbox,
            "normalized_bbox": current_normalized,
            "last_seen": evidence_frame,
            "clock_domain": clock_domain,
            "confidence": confidence,
            "label": custom.get("label", canonical),
            "confirmed": confirmed,
        })
        target_bbox = self._bbox_from_detection(target) if target is not None else None
        target_normalized = target.get("normalized_bbox") if target is not None else None
        if target_bbox is not None:
            record["base_bbox"] = target_bbox
            if isinstance(target_normalized, list) and len(target_normalized) == 4:
                record["base_normalized_bbox"] = list(target_normalized)
            record["last_supported_frame"] = self._base_frame_index
        return confirmed

    def _record_missing_custom_evidence(self, observed_keys: set[str]) -> None:
        """Advance 2-of-3 evidence while holding a confirmed class briefly."""
        for key, record in list(self._custom_candidates.items()):
            if key in observed_keys or record.get("clock_domain") != FULL_FRAME_CUSTOM_CLOCK_DOMAIN:
                continue
            window = self._custom_windows.get(key)
            if window is None:
                continue
            confirmed_by_window = window.observe(
                key,
                frame_index=self._custom_frame_index,
                matched=False,
            )
            age = self._custom_frame_index - int(record.get("last_seen", self._custom_frame_index))
            last_supported_frame = record.get("last_supported_frame")
            base_recent = (
                isinstance(last_supported_frame, int)
                and self._base_frame_index - last_supported_frame
                <= getattr(self, "_custom_base_hold_frames", DEFAULT_CUSTOM_BASE_HOLD_FRAMES)
            )
            record["confirmed"] = confirmed_by_window or (
                record.get("confirmed") is True
                and (
                    age <= getattr(
                        self, "_custom_hold_opportunities", DEFAULT_CUSTOM_HOLD_OPPORTUNITIES
                    )
                    or base_recent
                )
            )

    @staticmethod
    def _propagate_box_from_base(
        custom_box: Sequence[float],
        previous_base_box: Sequence[float],
        current_base_box: Sequence[float],
        *,
        alpha: float,
        rounded: bool,
    ) -> List[Any]:
        """Move a custom box by the bounded motion/scale of a base box."""
        custom_cx = (float(custom_box[0]) + float(custom_box[2])) / 2.0
        custom_cy = (float(custom_box[1]) + float(custom_box[3])) / 2.0
        custom_width = max(1e-6, float(custom_box[2]) - float(custom_box[0]))
        custom_height = max(1e-6, float(custom_box[3]) - float(custom_box[1]))
        previous_cx = (float(previous_base_box[0]) + float(previous_base_box[2])) / 2.0
        previous_cy = (float(previous_base_box[1]) + float(previous_base_box[3])) / 2.0
        current_cx = (float(current_base_box[0]) + float(current_base_box[2])) / 2.0
        current_cy = (float(current_base_box[1]) + float(current_base_box[3])) / 2.0
        previous_width = max(1e-6, float(previous_base_box[2]) - float(previous_base_box[0]))
        previous_height = max(1e-6, float(previous_base_box[3]) - float(previous_base_box[1]))
        current_width = max(1e-6, float(current_base_box[2]) - float(current_base_box[0]))
        current_height = max(1e-6, float(current_base_box[3]) - float(current_base_box[1]))
        scale_x = min(1.15, max(0.85, current_width / previous_width))
        scale_y = min(1.15, max(0.85, current_height / previous_height))
        predicted_width = custom_width * scale_x
        predicted_height = custom_height * scale_y
        predicted_cx = custom_cx + current_cx - previous_cx
        predicted_cy = custom_cy + current_cy - previous_cy
        predicted = [
            predicted_cx - predicted_width / 2.0,
            predicted_cy - predicted_height / 2.0,
            predicted_cx + predicted_width / 2.0,
            predicted_cy + predicted_height / 2.0,
        ]
        smoothed = [
            float(previous) * (1.0 - alpha) + current * alpha
            for previous, current in zip(custom_box, predicted)
        ]
        return [int(round(value)) for value in smoothed] if rounded else smoothed

    def _carry_custom_record_with_base(
        self,
        record: Dict[str, Any],
        base_detection: Mapping[str, Any],
    ) -> None:
        current_base_bbox = self._bbox_from_detection(base_detection)
        if current_base_bbox is None:
            return
        previous_base_bbox = record.get("base_bbox")
        custom_bbox = record.get("bbox")
        alpha = getattr(self, "_custom_box_ema_alpha", DEFAULT_CUSTOM_BOX_EMA_ALPHA)
        propagated_bbox: Optional[List[int]] = None
        if (
            isinstance(previous_base_bbox, list)
            and len(previous_base_bbox) == 4
            and isinstance(custom_bbox, list)
            and len(custom_bbox) == 4
        ):
            propagated_bbox = self._propagate_box_from_base(
                custom_bbox,
                previous_base_bbox,
                current_base_bbox,
                alpha=alpha,
                rounded=True,
            )
        current_base_normalized = base_detection.get("normalized_bbox")
        previous_base_normalized = record.get("base_normalized_bbox")
        custom_normalized = record.get("normalized_bbox")
        if (
            isinstance(current_base_normalized, list)
            and len(current_base_normalized) == 4
            and isinstance(previous_base_normalized, list)
            and len(previous_base_normalized) == 4
            and isinstance(custom_normalized, list)
            and len(custom_normalized) == 4
        ):
            propagated_normalized = self._propagate_box_from_base(
                custom_normalized,
                previous_base_normalized,
                current_base_normalized,
                alpha=alpha,
                rounded=False,
            )
            bounded_normalized = self._bounded_normalized_box_step(
                custom_normalized,
                propagated_normalized,
                getattr(
                    self,
                    "_custom_max_edge_step_ratio",
                    DEFAULT_CUSTOM_MAX_EDGE_STEP_RATIO,
                ),
            )
            record["normalized_bbox"] = bounded_normalized
            dimensions = self._frame_dimensions_from_box(
                current_base_bbox,
                current_base_normalized,
            )
            if dimensions is not None:
                frame_width, frame_height = dimensions
                record["bbox"] = [
                    int(round(bounded_normalized[0] * frame_width)),
                    int(round(bounded_normalized[1] * frame_height)),
                    int(round(bounded_normalized[2] * frame_width)),
                    int(round(bounded_normalized[3] * frame_height)),
                ]
            elif propagated_bbox is not None:
                record["bbox"] = propagated_bbox
        elif propagated_bbox is not None:
            record["bbox"] = propagated_bbox
        record["base_bbox"] = current_base_bbox
        if isinstance(current_base_normalized, list) and len(current_base_normalized) == 4:
            record["base_normalized_bbox"] = list(current_base_normalized)
        record["last_supported_frame"] = self._base_frame_index

    def _is_person_component_false_positive(
        self,
        detection: Mapping[str, Any],
        active_records: Iterable[Mapping[str, Any]],
    ) -> bool:
        """Reject a floating machine component mistaken for a person.

        This is deliberately narrower than cross-class NMS. A real person at
        the vehicle/ground boundary, outside the reach envelope, or with high
        model confidence remains visible.
        """
        canonical = str(detection.get("canonicalClass") or detection.get("class") or "")
        if canonical != "person" or str(detection.get("source") or "").upper() != "COCO":
            return False
        if float(detection.get("confidence") or 0.0) >= PERSON_IN_REACH_MAX_CONFIDENCE:
            return False
        person_bbox = self._bbox_from_detection(detection)
        if person_bbox is None:
            return False
        person_width = max(0, person_bbox[2] - person_bbox[0])
        person_height = max(0, person_bbox[3] - person_bbox[1])
        person_area = person_width * person_height
        if person_area <= 0:
            return False

        for record in active_records:
            record_class = str(record.get("canonicalClass") or record.get("class") or "")
            if record_class != "reach_stacker" or record.get("confirmed") is not True:
                continue
            reach_bbox = self._bbox_from_detection(record)
            if reach_bbox is None:
                continue
            reach_width = max(0, reach_bbox[2] - reach_bbox[0])
            reach_height = max(0, reach_bbox[3] - reach_bbox[1])
            reach_area = reach_width * reach_height
            if reach_area <= 0 or person_area / reach_area > PERSON_IN_REACH_MAX_AREA_RATIO:
                continue
            intersection = (
                max(0, min(person_bbox[2], reach_bbox[2]) - max(person_bbox[0], reach_bbox[0]))
                * max(0, min(person_bbox[3], reach_bbox[3]) - max(person_bbox[1], reach_bbox[1]))
            )
            containment = intersection / person_area
            bottom_gap_ratio = (reach_bbox[3] - person_bbox[3]) / reach_height
            if (
                containment >= PERSON_IN_REACH_MIN_CONTAINMENT
                and bottom_gap_ratio >= PERSON_IN_REACH_MIN_BOTTOM_GAP_RATIO
            ):
                return True
        return False

    def _retain_confirmed_custom_tracks(self, detections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Emit stable custom tracks and suppress their generic duplicates."""
        custom_hold = getattr(
            self, "_custom_hold_opportunities", DEFAULT_CUSTOM_HOLD_OPPORTUNITIES
        )
        base_hold = getattr(
            self, "_custom_base_hold_frames", DEFAULT_CUSTOM_BASE_HOLD_FRAMES
        )
        active_records = [
            record
            for record in self._custom_candidates.values()
            if record.get("clock_domain") == FULL_FRAME_CUSTOM_CLOCK_DOMAIN
            and record.get("confirmed") is True
            and record.get("trackId") is not None
            and (
                self._custom_frame_index - int(record.get("last_seen", self._custom_frame_index))
                <= custom_hold
                or (
                    isinstance(record.get("last_supported_frame"), int)
                    and self._base_frame_index - int(record["last_supported_frame"]) <= base_hold
                )
            )
        ]

        # A generic base detection may continue the geometry of an already
        # confirmed custom object for an arbitrarily long model-confidence gap.
        # Matching is spatial and one-to-one; the base ID/class never replaces
        # the custom identity or semantic label.
        used_base_indexes: set[int] = set()
        for record in active_records:
            record_bbox = self._bbox_from_detection(record)
            if record_bbox is None:
                continue
            best_index: Optional[int] = None
            best_rank = (-1.0, float("-inf"))
            for index, detection in enumerate(detections):
                if index in used_base_indexes:
                    continue
                canonical = str(detection.get("canonicalClass") or detection.get("class") or "")
                if canonical not in GENERIC_VEHICLE_CLASSES:
                    continue
                detection_bbox = self._bbox_from_detection(detection)
                if detection_bbox is None:
                    continue
                overlap = self._iou(record_bbox, detection_bbox)
                center_distance = self._center_distance_ratio(record_bbox, detection_bbox)
                if overlap < self._custom_match_overlap and center_distance > 0.80:
                    continue
                rank = (overlap, -center_distance)
                if rank > best_rank:
                    best_index, best_rank = index, rank
            if best_index is not None:
                used_base_indexes.add(best_index)
                self._carry_custom_record_with_base(record, detections[best_index])

        output: List[Dict[str, Any]] = []
        for detection in detections:
            canonical = str(detection.get("canonicalClass") or detection.get("class") or "")
            detection_bbox = self._bbox_from_detection(detection)
            overlaps_custom = canonical in GENERIC_VEHICLE_CLASSES and detection_bbox is not None and any(
                (record_bbox := self._bbox_from_detection(record)) is not None
                and (
                    self._iou(detection_bbox, record_bbox) >= self._custom_match_overlap
                    or self._center_distance_ratio(record_bbox, detection_bbox) <= 0.80
                )
                for record in active_records
            )
            is_person_component = self._is_person_component_false_positive(
                detection,
                active_records,
            )
            if not overlaps_custom and not is_person_component:
                output.append(detection)

        output_track_ids = {
            int(item["trackId"])
            for item in output
            if item.get("trackId") is not None
        }
        for record in active_records:
            track_id = int(record["trackId"])
            if track_id in output_track_ids:
                continue
            bbox = record.get("bbox")
            normalized_bbox = record.get("normalized_bbox")
            if not isinstance(bbox, list) or len(bbox) != 4 or not isinstance(normalized_bbox, list) or len(normalized_bbox) != 4:
                continue
            output.append({
                "trackId": track_id,
                "bbox": list(bbox),
                "normalized_bbox": list(normalized_bbox),
                "class": record["class"],
                "canonicalClass": record["class"],
                "label": record.get("label", record["class"]),
                "confidence": round(float(record.get("confidence") or 0.0), 3),
                "source": "CUSTOM",
                "candidateVersion": self._custom_version_key,
                "customConfirmed": True,
                "canInitiate": False,
                "canContinue": True,
            })
        return output

    def _prune_custom_candidates(self) -> None:
        current_clock = {
            ROI_CLOCK_DOMAIN: getattr(self, "_roi_opportunity_index", 0),
            FULL_FRAME_CUSTOM_CLOCK_DOMAIN: self._custom_frame_index,
        }
        for key, candidate in list(self._custom_candidates.items()):
            clock_domain = candidate.get("clock_domain")
            current_index = current_clock.get(str(clock_domain))
            if current_index is None:
                # Fail closed for pre-domain or malformed state.
                self._custom_candidates.pop(key, None)
                self._custom_windows.pop(key, None)
                continue
            max_idle = min(
                ROI_STATE_MAX_IDLE_OPPORTUNITIES,
                getattr(self, "_custom_hold_opportunities", DEFAULT_CUSTOM_HOLD_OPPORTUNITIES),
            )
            custom_stale = int(candidate.get("last_seen", current_index)) < current_index - max_idle
            last_supported_frame = candidate.get("last_supported_frame")
            base_recent = (
                candidate.get("clock_domain") == FULL_FRAME_CUSTOM_CLOCK_DOMAIN
                and isinstance(last_supported_frame, int)
                and self._base_frame_index - last_supported_frame
                <= getattr(self, "_custom_base_hold_frames", DEFAULT_CUSTOM_BASE_HOLD_FRAMES)
            )
            if custom_stale and not base_recent:
                self._custom_candidates.pop(key, None)
                self._custom_windows.pop(key, None)

    def _apply_confirmed_custom(
        self,
        custom: Dict[str, Any],
        target: Optional[Dict[str, Any]],
        width: int,
        height: int,
    ) -> Dict[str, Any]:
        output = target if target is not None else dict(custom)
        can_initiate = self._policy.can_initiate(
            "custom", str(custom["canonicalClass"]), custom["confidence"],
        )
        key = str(custom.get("_evidenceKey") or self._custom_evidence_key(custom, target))
        record = self._custom_candidates.setdefault(key, {})
        track_id = record.get("trackId")
        if track_id is None:
            track_id = self._next_synthetic_track_id
            self._next_synthetic_track_id -= 1
            record["trackId"] = track_id
        record["initiated"] = bool(record.get("initiated")) or can_initiate
        output.update({
            "trackId": int(track_id),
            "bbox": list(record.get("bbox") or custom["bbox"]),
            "normalized_bbox": list(
                record.get("normalized_bbox")
                or self._normalized_bbox(list(custom["bbox"]), width, height)
            ),
            "class": custom["canonicalClass"],
            "canonicalClass": custom["canonicalClass"],
            "label": custom["label"],
            "confidence": custom["confidence"],
            "source": "CUSTOM",
            "candidateVersion": self._custom_version_key,
            "customConfirmed": True,
            # A two-of-three confirmation is necessary but not sufficient to
            # create a new violation: that still requires initiation confidence.
            "canInitiate": can_initiate,
            "canContinue": True,
        })
        output.pop("_evidenceKey", None)
        return output

    def _apply_custom_augmentation(
        self,
        frame: np.ndarray,
        detections: List[Dict[str, Any]],
        width: int,
        height: int,
        roi_candidates: Optional[Iterable[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        if self._custom_model is None or not self._enabled_custom_classes:
            return detections
        supplemental = list(roi_candidates or ())
        supplemental_clock = max(
            (
                int(candidate.get("roiInferenceIndex") or 0)
                for candidate in supplemental
                if isinstance(candidate.get("roiInferenceIndex"), int)
                and not isinstance(candidate.get("roiInferenceIndex"), bool)
            ),
            default=0,
        )
        self._roi_opportunity_index = max(getattr(self, "_roi_opportunity_index", 0), supplemental_clock)
        full_frame_due = (self._base_frame_index % self._custom_interval) == 0
        if full_frame_due:
            self._custom_frame_index += 1
        self._prune_custom_candidates()
        if not full_frame_due and not supplemental:
            return self._same_class_nms(self._retain_confirmed_custom_tracks(detections))
        candidates = supplemental
        if full_frame_due:
            try:
                candidates = [*self._collect_custom_detections(frame, width, height), *supplemental]
            except Exception as exc:
                logger.warning("ACTIVE custom inference failed; keeping ROI/COCO detections: %s", exc)

        custom_only: List[Dict[str, Any]] = []
        observed_full_frame_keys: set[str] = set()
        for custom in candidates:
            target = self._best_generic_target(custom, detections)
            confirmed = self._confirm_custom(custom, target)
            if self._custom_clock_domain(custom) == FULL_FRAME_CUSTOM_CLOCK_DOMAIN:
                evidence_key = custom.get("_evidenceKey")
                if isinstance(evidence_key, str):
                    observed_full_frame_keys.add(evidence_key)
            if not confirmed:
                continue
            refined = self._apply_confirmed_custom(custom, target, width, height)
            if target is None:
                custom_only.append(refined)

        if full_frame_due:
            self._record_missing_custom_evidence(observed_full_frame_keys)

        self._prune_custom_candidates()
        retained = self._retain_confirmed_custom_tracks(detections)
        # Current evidence must win an equal-confidence NMS tie so its
        # canInitiate flag is not replaced by a retained continuation record.
        return self._same_class_nms([*custom_only, *retained])

    def _filter_and_gate_unified(self, detections: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Apply one track state to COCO and domain classes from one model pass."""
        self._base_frame_index += 1
        self._custom_frame_index += 1
        output: List[Dict[str, Any]] = []
        for detection in detections:
            canonical = str(detection.get("canonicalClass") or detection.get("class") or "")
            if canonical not in self._enabled_custom_classes:
                continue
            confidence = float(detection.get("confidence") or 0.0)
            raw_track_id = detection.get("trackId")
            try:
                track_id = int(raw_track_id) if raw_track_id is not None else None
            except (TypeError, ValueError):
                track_id = None
            state = self._base_track_state.get(track_id) if track_id is not None else None
            previously_confirmed = bool(state and state.get("confirmed") and state.get("class") == canonical)
            policy_source = "base" if canonical in COCO_CLASS_IDS else "custom"
            can_continue = previously_confirmed and self._policy.can_continue(policy_source, canonical, confidence)
            can_initiate = self._policy.can_initiate(policy_source, canonical, confidence)
            custom_confirmed = canonical in COCO_CLASS_IDS
            if canonical not in COCO_CLASS_IDS and not previously_confirmed:
                temporal_candidate = dict(detection)
                temporal_target = detection if track_id is not None else None
                custom_confirmed = self._confirm_custom(temporal_candidate, temporal_target)
                can_initiate = can_initiate and custom_confirmed
            elif canonical not in COCO_CLASS_IDS:
                custom_confirmed = True
            if not can_initiate and not can_continue:
                continue
            if track_id is not None:
                self._base_track_state[track_id] = {
                    "class": canonical,
                    "confirmed": previously_confirmed or can_initiate,
                    "last_seen": self._base_frame_index,
                }
            detection["trackId"] = track_id
            detection["source"] = "UNIFIED"
            detection["customConfirmed"] = custom_confirmed
            detection["canInitiate"] = can_initiate
            detection["canContinue"] = can_continue or can_initiate
            output.append(detection)
        stale_before = self._base_frame_index - 120
        for track_id, state in list(self._base_track_state.items()):
            if int(state.get("last_seen", self._base_frame_index)) < stale_before:
                self._base_track_state.pop(track_id, None)
        self._prune_custom_candidates()
        return output

    def _track_unified(self, frame: np.ndarray, conf: Optional[float]) -> List[Dict[str, Any]]:
        """Run the ACTIVE unified YOLO exactly once with ByteTrack continuity."""
        if self._custom_model is None or not self._enabled_custom_classes:
            logger.error("Unified Area classes are enabled but the ACTIVE unified model is unavailable.")
            return []
        height, width = frame.shape[:2]
        model_names = self._custom_model.names
        name_items = model_names.items() if isinstance(model_names, Mapping) else enumerate(model_names)
        class_ids = [
            int(class_id)
            for class_id, raw_label in name_items
            if self._custom_class_for_model_label(str(raw_label)) in self._enabled_custom_classes
        ]
        if not class_ids:
            logger.error("Unified Area model has no class IDs matching its ACTIVE manifest.")
            return []
        continuation_threshold = min(
            self._policy.thresholds_for(
                "base" if canonical in COCO_CLASS_IDS else "custom",
                canonical,
            ).continuation
            for canonical in self._enabled_custom_classes
        )
        threshold = min(conf if conf is not None else continuation_threshold, continuation_threshold)
        try:
            results = self._custom_model.track(
                frame,
                conf=threshold,
                classes=class_ids,
                persist=not self._reset_tracker_on_next_frame,
                tracker=self.tracker,
                imgsz=self.inference_size,
                device=self.device,
                quantize=getattr(self, "inference_quantize", None) if self.device != "cpu" else None,
                verbose=False,
            )
            self._reset_tracker_on_next_frame = False
        except Exception as exc:
            logger.error("Unified Area tracking inference failed: %s", exc)
            return []

        detections: List[Dict[str, Any]] = []
        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue
            track_ids = boxes.id.int().cpu().numpy().tolist() if boxes.id is not None else None
            for index in range(len(boxes)):
                class_id = int(boxes.cls[index].item())
                raw_label = (
                    str(model_names.get(class_id, ""))
                    if isinstance(model_names, Mapping)
                    else str(model_names[class_id])
                )
                canonical = self._custom_class_for_model_label(raw_label)
                if canonical is None or canonical not in self._enabled_custom_classes:
                    continue
                xyxy = boxes.xyxy[index].cpu().numpy().tolist() if hasattr(boxes.xyxy[index], "cpu") else boxes.xyxy[index].tolist()
                bbox = [
                    max(0, min(width - 1, int(xyxy[0]))),
                    max(0, min(height - 1, int(xyxy[1]))),
                    max(1, min(width, int(xyxy[2]))),
                    max(1, min(height, int(xyxy[3]))),
                ]
                if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
                    continue
                track_id = int(track_ids[index]) if track_ids is not None and index < len(track_ids) else None
                detection = self._new_base_detection(
                    bbox=bbox,
                    width=width,
                    height=height,
                    canonical_class=canonical,
                    confidence=float(boxes.conf[index].item()),
                    track_id=track_id,
                )
                detection["label"] = raw_label
                detections.append(detection)
        return self._filter_and_gate_unified(self._same_class_nms(detections))

    def track(self, frame: np.ndarray, conf: Optional[float] = None) -> List[Dict[str, Any]]:
        """Return only currently registry-authorized Area detections."""
        if frame is None or (not self._enabled_coco_classes and not self._enabled_custom_classes):
            return []
        height, width = frame.shape[:2]
        if height <= 0 or width <= 0:
            return []
        if getattr(self, "_runtime_mode", "SUPPLEMENTAL") == "UNIFIED":
            self.last_roi_latency_ms = 0.0
            return self._track_unified(frame, conf)
        base: List[Dict[str, Any]] = []
        if self._enabled_coco_classes:
            if self.model is None:
                logger.error("COCO registry classes are enabled but the YOLO11 model is unavailable.")
                return []
            class_ids = [COCO_CLASS_IDS[name] for name in sorted(self._enabled_coco_classes)]
            continuation_threshold = min(
                self._policy.thresholds_for("base", canonical).continuation
                for canonical in self._enabled_coco_classes
            )
            threshold = min(conf if conf is not None else continuation_threshold, continuation_threshold)
            try:
                results = self.model.track(
                    frame,
                    conf=threshold,
                    classes=class_ids,
                    persist=not self._reset_tracker_on_next_frame,
                    tracker=self.tracker,
                    imgsz=self.inference_size,
                    device=self.device,
                    quantize=getattr(self, "inference_quantize", None) if self.device != "cpu" else None,
                    verbose=False,
                )
                self._reset_tracker_on_next_frame = False
            except Exception as exc:
                logger.error("Area YOLO11 tracking inference failed: %s", exc)
                return []

            for result in results:
                boxes = result.boxes
                if boxes is None:
                    continue
                track_ids = boxes.id.int().cpu().numpy().tolist() if boxes.id is not None else None
                for index in range(len(boxes)):
                    raw_class = str(self.model.names.get(int(boxes.cls[index].item()), ""))
                    canonical, _ = self._canonicalize_detection_class(raw_class)
                    if canonical not in self._enabled_coco_classes:
                        continue
                    xyxy = boxes.xyxy[index].cpu().numpy().tolist()
                    bbox = [
                        max(0, min(width - 1, int(xyxy[0]))),
                        max(0, min(height - 1, int(xyxy[1]))),
                        max(1, min(width, int(xyxy[2]))),
                        max(1, min(height, int(xyxy[3]))),
                    ]
                    if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
                        continue
                    track_id = int(track_ids[index]) if track_ids is not None and index < len(track_ids) else None
                    base.append(self._new_base_detection(
                        bbox=bbox,
                        width=width,
                        height=height,
                        canonical_class=canonical,
                        confidence=float(boxes.conf[index].item()),
                        track_id=track_id,
                    ))

        gated = self._filter_and_gate_base(self._same_class_nms(base))
        roi_started = time.perf_counter()
        roi_candidates = self._collect_roi_candidates(frame)
        self.last_roi_latency_ms = (time.perf_counter() - roi_started) * 1000.0
        roi_base = [candidate for candidate in roi_candidates if candidate.get("roiDetector") == "base"]
        roi_custom = [candidate for candidate in roi_candidates if candidate.get("roiDetector") == "custom"]
        gated = self._merge_roi_base_candidates(gated, roi_base)
        return self._apply_custom_augmentation(frame, gated, width, height, roi_custom)

    def warmup(self, frame_shape: tuple[int, int]) -> None:
        """Initialize base/custom predictors without consuming the video source."""
        width, height = frame_shape
        if width <= 0 or height <= 0:
            raise ValueError("warmup frame dimensions must be positive")
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        try:
            self.track(frame)
        finally:
            # A synthetic frame must never become part of the live tracking
            # timeline or temporal custom evidence.
            self.reset_tracking()

    def reset_tracking(self) -> None:
        """Start a fresh ByteTrack/control sequence after a seek or source reset."""
        self._reset_tracker_on_next_frame = True
        self._base_track_state.clear()
        self._base_frame_index = 0
        self._custom_frame_index = 0
        self._custom_windows.clear()
        self._custom_candidates.clear()
        roi_candidates = getattr(self, "_roi_base_candidates", None)
        if roi_candidates is not None:
            roi_candidates.clear()
