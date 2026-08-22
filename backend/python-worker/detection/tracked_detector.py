"""
detection.tracked_detector — Configurable YOLO/YOLO-World ByteTrack Detector

Uses either the original YOLO detector or YOLO-World with multi-object tracking
(ByteTrack) to provide persistent trackId across video frames for BAI-KIEM.
"""
import json
import logging
import math
import os
import time
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Sequence, Tuple

import numpy as np

from detection.detector import COCO_VIETNAMESE_MAPPING, YoloDetector
from ultralytics import YOLO, YOLOWorld

import dotenv

# Load environment configuration
for _env_path in ["backend/.env", ".env", "../.env", "../../backend/.env"]:
    if os.path.exists(_env_path):
        dotenv.load_dotenv(_env_path)
        break

logger = logging.getLogger("sentriai.detection.tracked")
DEFAULT_AREA_YOLO_MODEL = "yolo11n.pt"
DEFAULT_CUSTOM_AUGMENT_ARTIFACT = "training/models/01e3e77b-d843-4765-b951-a8219ca6e47c/best.pt"
DEFAULT_CUSTOM_AUGMENT_VERSION = "custom-01e3e77b"
DEFAULT_RETENTION_FRAMES = 14
DEFAULT_BOX_SMOOTHING = 0.45
DEFAULT_CONFIDENCE_SMOOTHING = 0.40
DEFAULT_TRACK_INITIATION_CONFIDENCE = 0.30
DEFAULT_TRACK_CONTINUATION_CONFIDENCE = 0.14
DEFAULT_MOTION_WINDOW_FRAMES = 40
DEFAULT_STATIC_MAX_SPEED_PX_PER_FRAME = 0.30
DEFAULT_CUSTOM_PROMOTE_CONFIDENCE = 0.18
DEFAULT_CUSTOM_INSTANT_CONFIDENCE = 0.22
DEFAULT_CUSTOM_CONFIRM_FRAMES = 2
DEFAULT_CUSTOM_CONFIRM_WINDOW = 8
DEFAULT_CUSTOM_CONFIRM_WINDOW_SECONDS = 2.5
DEFAULT_REACH_STACKER_MIN_ASPECT = 0.65
DEFAULT_REACH_STACKER_NARROW_MIN_CONFIDENCE = 0.86
DEFAULT_REACH_STACKER_MAX_AREA_RATIO = 0.20
DEFAULT_REACH_STACKER_CUSTOM_ONLY_COMPACT_ASPECT = 1.65
DEFAULT_REACH_STACKER_CUSTOM_ONLY_LARGE_AREA_RATIO = 0.035
DEFAULT_REACH_STACKER_CUSTOM_ONLY_COMPACT_MIN_CONFIDENCE = 0.80
DEFAULT_REACH_STACKER_TARGET_COMPACT_ASPECT = 1.65
DEFAULT_REACH_STACKER_TARGET_COMPACT_MIN_CONFIDENCE = 0.92
DEFAULT_REACH_STACKER_LONG_ASPECT = 1.75
DEFAULT_REACH_STACKER_LONG_MAX_AREA_RATIO = 0.06
DEFAULT_REACH_STACKER_LONG_MIN_CONFIDENCE = 0.32
DEFAULT_REACH_STACKER_MAX_ASPECT = 3.50
DEFAULT_REACH_STACKER_MIN_HEIGHT_RATIO = 0.06
DEFAULT_CUSTOM_TILE_SIZE = 640
DEFAULT_CUSTOM_TILE_OVERLAP = 0.25
DEFAULT_CUSTOM_TILE_MAX_TILES = 16
DEFAULT_CUSTOM_CROP_MAX_TARGETS = 6
DEFAULT_CUSTOM_CROP_PADDING = 0.45
DEFAULT_RETENTION_SECONDS = 2.2
GENERIC_VEHICLE_CLASSES = {"truck", "car", "bus"}
VEHICLE_CLASS_NAMES = {
    "truck",
    "car",
    "bus",
    "motorcycle",
    "forklift",
    "container handler",
    "reach stacker",
    "personnel carrier",
    "utility vehicle",
    "golf cart",
}
AMBIGUOUS_WORLD_VEHICLES = {"personnel carrier", "utility vehicle", "golf cart"}


class TrackedYoloDetector(YoloDetector):
    """
    YOLO Object Detector with ByteTrack tracking for persistent object identities.
    Area monitoring is restricted to person and truck detections. The truck class is
    mapped to the business label Container by the active object-label snapshot.
    """

    def __init__(
        self,
        model_path: Optional[str] = None,
        conf_threshold: Optional[float] = None,
        tracker: str = "bytetrack.yaml",
        target_classes: Optional[Sequence[str]] = None,
    ):
        self.detector_kind = os.getenv("AREA_DETECTOR_KIND", "yolo11").strip().casefold()
        configured_model = model_path or os.getenv("AREA_DETECTOR_MODEL")
        configured_classes = os.getenv("AREA_DETECTOR_CLASSES", "")
        env_classes = tuple(
            item.strip()
            for item in configured_classes.split(",")
            if item.strip()
        )
        default_classes = (
            (
                "person",
                "forklift",
                "container handler",
                "reach stacker",
                "container",
                "shipping container",
                "personnel carrier",
                "utility vehicle",
                "golf cart",
                "truck",
                "car",
                "motorcycle",
                "boat",
                "train",
            )
            if self.detector_kind in {"world", "hybrid"}
            else ("person", "truck", "car", "bus", "motorcycle", "boat", "train")
        )
        if target_classes:
            self.area_target_classes = tuple(target_classes)
        elif env_classes and self.detector_kind in {"world", "hybrid"}:
            # Preserve any project-specific prompts while retaining the domain
            # prompts required to distinguish containers, forklifts and people carriers.
            self.area_target_classes = tuple(dict.fromkeys((*default_classes, *env_classes)))
        else:
            self.area_target_classes = tuple(env_classes or default_classes)

        default_confidence = 0.18 if self.detector_kind in {"world", "hybrid"} else 0.25
        env_conf = os.getenv("AREA_CONF_THRESHOLD")
        if env_conf:
            try:
                self.conf_threshold = float(env_conf)
            except ValueError:
                self.conf_threshold = conf_threshold or default_confidence
        else:
            self.conf_threshold = conf_threshold if conf_threshold is not None else default_confidence

        try:
            # 896 keeps distant industrial vehicles detailed while recovering
            # enough headroom for the Area monitor's 8–9 FPS floor on 4 GB GPUs.
            self.inference_size = max(640, int(os.getenv("AREA_INFERENCE_SIZE", "896")))
        except ValueError:
            self.inference_size = 960
        self._reset_tracker_on_next_frame = False
        # YOLO-World may assign different text prompts to one ByteTrack ID on
        # adjacent frames. Keep a short, confidence-weighted class history so
        # the displayed/business label does not flicker between truck, car and
        # personnel carrier while the physical object remains the same.
        self._track_class_history: Dict[int, Dict[str, float]] = {}
        self._track_last_seen: Dict[int, int] = {}
        self._tracking_frame_index = 0
        # Detector inference runs at the lower continuation threshold so ByteTrack
        # can retain an established object through rain/blur.  A new visible ID
        # still needs the stricter initiation confidence before it reaches UI/zone.
        self._hysteresis_tracks: Dict[int, int] = {}
        self._hysteresis_confidence: Dict[int, Dict[str, float]] = {}
        self._hysteresis_frame_index = 0
        self._track_initiation_confidence = float(os.getenv(
            "AREA_TRACK_INITIATION_CONFIDENCE", str(DEFAULT_TRACK_INITIATION_CONFIDENCE)
        ))
        self._track_continuation_confidence = float(os.getenv(
            "AREA_TRACK_CONTINUATION_CONFIDENCE", str(DEFAULT_TRACK_CONTINUATION_CONFIDENCE)
        ))
        self._confidence_smoothing_alpha = min(1.0, max(0.0, float(os.getenv(
            "AREA_CONF_SMOOTHING", str(DEFAULT_CONFIDENCE_SMOOTHING)
        ))))
        self._motion_history: Dict[int, Deque[Tuple[float, float]]] = {}
        self._static_track_ids: set[int] = set()
        self._motion_window_frames = max(2, int(os.getenv(
            "AREA_MOTION_WINDOW_FRAMES", str(DEFAULT_MOTION_WINDOW_FRAMES)
        )))
        self._static_max_speed_px_per_frame = max(0.0, float(os.getenv(
            "AREA_STATIC_MAX_SPEED_PX_PER_FRAME", str(DEFAULT_STATIC_MAX_SPEED_PX_PER_FRAME)
        )))
        self._custom_model: Optional[YOLO] = None
        self._custom_version_key: Optional[str] = None
        self._custom_label_map: Dict[str, str] = {}
        self._custom_track_overrides: Dict[int, Dict[str, Any]] = {}
        self._custom_evidence: Dict[str, Dict[str, Any]] = {}
        self._custom_evidence_next_id = 1
        self._custom_frame_index = 0
        self._custom_confidence = float(os.getenv("CUSTOM_AUGMENT_CONF", "0.18"))
        self._custom_interval = max(1, int(os.getenv("CUSTOM_AUGMENT_INTERVAL", "1")))
        self._custom_full_frame = os.getenv("CUSTOM_AUGMENT_FULL_FRAME", "true").strip().casefold() not in {"0", "false", "no", "off"}
        self._custom_match_overlap = float(os.getenv("CUSTOM_AUGMENT_MATCH_OVERLAP", "0.18"))
        self._custom_full_frame_size = max(320, int(os.getenv("CUSTOM_AUGMENT_FULL_FRAME_SIZE", str(self.inference_size))))
        self._custom_tile_enabled = os.getenv("CUSTOM_AUGMENT_TILE_ENABLED", "false").strip().casefold() in {"1", "true", "yes", "on"}
        self._custom_tile_size = max(320, int(os.getenv("CUSTOM_AUGMENT_TILE_SIZE", str(DEFAULT_CUSTOM_TILE_SIZE))))
        self._custom_tile_overlap = min(0.75, max(0.0, float(os.getenv("CUSTOM_AUGMENT_TILE_OVERLAP", str(DEFAULT_CUSTOM_TILE_OVERLAP)))))
        self._custom_tile_max_tiles = max(1, int(os.getenv("CUSTOM_AUGMENT_TILE_MAX_TILES", str(DEFAULT_CUSTOM_TILE_MAX_TILES))))
        self._custom_crop_enabled = os.getenv("CUSTOM_AUGMENT_CROP_ENABLED", "false").strip().casefold() in {"1", "true", "yes", "on"}
        self._custom_crop_max_targets = max(0, int(os.getenv("CUSTOM_AUGMENT_CROP_MAX_TARGETS", str(DEFAULT_CUSTOM_CROP_MAX_TARGETS))))
        self._custom_crop_padding = min(1.0, max(0.0, float(os.getenv("CUSTOM_AUGMENT_CROP_PADDING", str(DEFAULT_CUSTOM_CROP_PADDING)))))
        self._custom_promote_confidence = float(os.getenv("CUSTOM_AUGMENT_PROMOTE_CONF", str(DEFAULT_CUSTOM_PROMOTE_CONFIDENCE)))
        self._custom_instant_confidence = float(os.getenv("CUSTOM_AUGMENT_INSTANT_CONF", str(DEFAULT_CUSTOM_INSTANT_CONFIDENCE)))
        self._custom_confirm_frames = max(1, int(os.getenv("CUSTOM_AUGMENT_CONFIRM_FRAMES", str(DEFAULT_CUSTOM_CONFIRM_FRAMES))))
        self._custom_confirm_window = max(
            self._custom_confirm_frames,
            int(os.getenv("CUSTOM_AUGMENT_CONFIRM_WINDOW", str(DEFAULT_CUSTOM_CONFIRM_WINDOW))),
        )
        self._custom_confirm_window_seconds = max(
            0.0,
            float(os.getenv("CUSTOM_AUGMENT_CONFIRM_WINDOW_SECONDS", str(DEFAULT_CUSTOM_CONFIRM_WINDOW_SECONDS))),
        )
        self._reach_stacker_min_aspect = float(os.getenv("CUSTOM_AUGMENT_REACH_STACKER_MIN_ASPECT", str(DEFAULT_REACH_STACKER_MIN_ASPECT)))
        self._reach_stacker_narrow_min_confidence = float(
            os.getenv(
                "CUSTOM_AUGMENT_REACH_STACKER_NARROW_MIN_CONF",
                str(DEFAULT_REACH_STACKER_NARROW_MIN_CONFIDENCE),
            )
        )
        self._reach_stacker_max_area_ratio = float(
            os.getenv("CUSTOM_AUGMENT_REACH_STACKER_MAX_AREA_RATIO", str(DEFAULT_REACH_STACKER_MAX_AREA_RATIO))
        )
        self._reach_stacker_custom_only_compact_aspect = float(
            os.getenv(
                "CUSTOM_AUGMENT_REACH_STACKER_CUSTOM_ONLY_COMPACT_ASPECT",
                str(DEFAULT_REACH_STACKER_CUSTOM_ONLY_COMPACT_ASPECT),
            )
        )
        self._reach_stacker_custom_only_large_area_ratio = float(
            os.getenv(
                "CUSTOM_AUGMENT_REACH_STACKER_CUSTOM_ONLY_LARGE_AREA_RATIO",
                str(DEFAULT_REACH_STACKER_CUSTOM_ONLY_LARGE_AREA_RATIO),
            )
        )
        self._reach_stacker_custom_only_compact_min_confidence = float(
            os.getenv(
                "CUSTOM_AUGMENT_REACH_STACKER_CUSTOM_ONLY_COMPACT_MIN_CONF",
                str(DEFAULT_REACH_STACKER_CUSTOM_ONLY_COMPACT_MIN_CONFIDENCE),
            )
        )
        self._reach_stacker_target_compact_aspect = float(
            os.getenv(
                "CUSTOM_AUGMENT_REACH_STACKER_TARGET_COMPACT_ASPECT",
                str(DEFAULT_REACH_STACKER_TARGET_COMPACT_ASPECT),
            )
        )
        self._reach_stacker_target_compact_min_confidence = float(
            os.getenv(
                "CUSTOM_AUGMENT_REACH_STACKER_TARGET_COMPACT_MIN_CONF",
                str(DEFAULT_REACH_STACKER_TARGET_COMPACT_MIN_CONFIDENCE),
            )
        )
        self._reach_stacker_long_aspect = float(
            os.getenv("CUSTOM_AUGMENT_REACH_STACKER_LONG_ASPECT", str(DEFAULT_REACH_STACKER_LONG_ASPECT))
        )
        self._reach_stacker_long_max_area_ratio = float(
            os.getenv(
                "CUSTOM_AUGMENT_REACH_STACKER_LONG_MAX_AREA_RATIO",
                str(DEFAULT_REACH_STACKER_LONG_MAX_AREA_RATIO),
            )
        )
        self._reach_stacker_long_min_confidence = float(
            os.getenv(
                "CUSTOM_AUGMENT_REACH_STACKER_LONG_MIN_CONF",
                str(DEFAULT_REACH_STACKER_LONG_MIN_CONFIDENCE),
            )
        )
        self._reach_stacker_max_aspect = max(
            self._reach_stacker_min_aspect,
            float(os.getenv("CUSTOM_AUGMENT_REACH_STACKER_MAX_ASPECT", str(DEFAULT_REACH_STACKER_MAX_ASPECT))),
        )
        self._reach_stacker_min_height_ratio = min(1.0, max(0.0, float(os.getenv(
            "CUSTOM_AUGMENT_REACH_STACKER_MIN_HEIGHT_RATIO",
            str(DEFAULT_REACH_STACKER_MIN_HEIGHT_RATIO),
        ))))
        self._retained_detections: Dict[str, Dict[str, Any]] = {}
        self._retention_frame_index = 0
        self._retention_next_synthetic_track_id = -1
        try:
            self._retention_frames = max(0, int(os.getenv("AREA_DETECTION_RETENTION_FRAMES", str(DEFAULT_RETENTION_FRAMES))))
        except ValueError:
            self._retention_frames = DEFAULT_RETENTION_FRAMES
        try:
            self._retention_seconds = max(0.0, float(os.getenv("AREA_DETECTION_RETENTION_SECONDS", str(DEFAULT_RETENTION_SECONDS))))
        except ValueError:
            self._retention_seconds = DEFAULT_RETENTION_SECONDS
        try:
            self._box_smoothing_alpha = min(0.85, max(0.0, float(os.getenv("AREA_BOX_SMOOTHING", str(DEFAULT_BOX_SMOOTHING)))))
        except ValueError:
            self._box_smoothing_alpha = DEFAULT_BOX_SMOOTHING

        import torch
        self.device = 0 if torch.cuda.is_available() else "cpu"
        device_str = "cuda:0" if self.device == 0 else "cpu"

        if self.detector_kind == "hybrid":
            self.model_path = self._resolve_model_path(configured_model or "yolov8s-world.pt")
            logger.info(
                "Loading HYBRID Ensemble (YOLO-World + COCO YOLO) on %s with prompts: %s",
                device_str,
                self.area_target_classes,
            )
            self.model = YOLOWorld(self.model_path)
            if self.device == 0:
                self.model.to(device_str)
            self.model.set_classes(list(self.area_target_classes))

            # Auxiliary COCO YOLO detector for high robustness on challenging angles / occlusions
            coco_path = self._resolve_model_path(os.getenv("SENTRIAI_BASE_YOLO_MODEL") or DEFAULT_AREA_YOLO_MODEL)
            self.aux_model = YOLO(coco_path)
            if self.device == 0:
                self.aux_model.to(device_str)
        elif self.detector_kind == "world":
            self.aux_model = None
            self.model_path = self._resolve_model_path(
                configured_model or "yolov8s-world.pt"
            )
            logger.info(
                "Loading YOLO-World model from %s (device: %s) with prompts: %s",
                self.model_path,
                device_str,
                self.area_target_classes,
            )
            self.model = YOLOWorld(self.model_path)
            if self.device == 0:
                self.model.to(device_str)
            self.model.set_classes(list(self.area_target_classes))
        else:
            self.aux_model = None
            super().__init__(
                model_path=configured_model or DEFAULT_AREA_YOLO_MODEL,
                conf_threshold=self.conf_threshold,
                target_classes=list(self.area_target_classes),
            )
        self.tracker = tracker

    @staticmethod
    def _canonicalize_detection_class(class_name: str) -> tuple[str, Optional[str]]:
        c_lower = class_name.casefold()
        if c_lower in {"train", "bus"}:
            return "truck", class_name
        return class_name, None

    def _now(self) -> float:
        clock = getattr(self, "_clock", None)
        if callable(clock):
            return float(clock())
        return time.monotonic()

    def _ensure_temporal_state(self) -> None:
        """Initialise temporal state for normal instances and lightweight tests."""
        if not hasattr(self, "_hysteresis_tracks"):
            self._hysteresis_tracks = {}
        if not hasattr(self, "_hysteresis_confidence"):
            self._hysteresis_confidence = {}
        if not hasattr(self, "_hysteresis_frame_index"):
            self._hysteresis_frame_index = 0
        if not hasattr(self, "_track_initiation_confidence"):
            self._track_initiation_confidence = DEFAULT_TRACK_INITIATION_CONFIDENCE
        if not hasattr(self, "_track_continuation_confidence"):
            self._track_continuation_confidence = DEFAULT_TRACK_CONTINUATION_CONFIDENCE
        if not hasattr(self, "_confidence_smoothing_alpha"):
            self._confidence_smoothing_alpha = DEFAULT_CONFIDENCE_SMOOTHING
        if not hasattr(self, "_motion_history"):
            self._motion_history = {}
        if not hasattr(self, "_static_track_ids"):
            self._static_track_ids = set()
        if not hasattr(self, "_motion_window_frames"):
            self._motion_window_frames = DEFAULT_MOTION_WINDOW_FRAMES
        if not hasattr(self, "_static_max_speed_px_per_frame"):
            self._static_max_speed_px_per_frame = DEFAULT_STATIC_MAX_SPEED_PX_PER_FRAME

    def _apply_track_hysteresis(self, detections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Expose only confident new tracks while tolerating brief low-confidence hits.

        The detector is deliberately run at the continuation threshold.  This
        method is the public-facing initiation gate: ByteTrack may observe weak
        candidates, but they cannot create UI boxes or zone violations until a
        high-confidence frame confirms their identity.
        """
        self._ensure_temporal_state()
        self._hysteresis_frame_index += 1
        frame_index = self._hysteresis_frame_index
        output: List[Dict[str, Any]] = []

        for detection in detections:
            raw_track_id = detection.get("trackId")
            confidence = float(detection.get("confidence") or 0.0)
            if raw_track_id is None:
                # Untracked low-confidence detections are rain/reflection noise.
                if confidence >= self._track_initiation_confidence:
                    output.append(detection)
                continue
            try:
                track_id = int(raw_track_id)
            except (TypeError, ValueError):
                continue

            known = track_id in self._hysteresis_tracks
            required_confidence = (
                self._track_continuation_confidence
                if known
                else self._track_initiation_confidence
            )
            if confidence < required_confidence:
                continue

            if not known:
                self._hysteresis_confidence[track_id] = {"value": confidence}
            else:
                previous = self._hysteresis_confidence.get(track_id, {}).get("value", confidence)
                alpha = self._confidence_smoothing_alpha
                self._hysteresis_confidence[track_id] = {
                    "value": (alpha * confidence) + ((1.0 - alpha) * float(previous))
                }
            self._hysteresis_tracks[track_id] = frame_index
            detection["trackId"] = track_id
            detection["confidence"] = round(self._hysteresis_confidence[track_id]["value"], 3)
            output.append(detection)

        # ByteTrack IDs can be reused.  Drop temporal state after a bounded
        # absence so a recycled ID must satisfy initiation confidence again.
        stale_before = frame_index - max(self._motion_window_frames, 60)
        for track_id, last_seen in list(self._hysteresis_tracks.items()):
            if last_seen < stale_before:
                self._hysteresis_tracks.pop(track_id, None)
                self._hysteresis_confidence.pop(track_id, None)
                self._motion_history.pop(track_id, None)
                self._static_track_ids.discard(track_id)
        return output

    def _suppress_static_detections(self, detections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Filter long-observed stationary objects from monitoring output.

        A shipping container can be visually classified as a truck or reach
        stacker.  It is never eligible for the Area-monitor overlay or zone
        state machine after its centre stays below the configured velocity gate.
        """
        self._ensure_temporal_state()
        output: List[Dict[str, Any]] = []
        for detection in detections:
            raw_track_id = detection.get("trackId")
            bbox = self._bbox_from_detection(detection)
            if raw_track_id is None or bbox is None:
                output.append(detection)
                continue
            try:
                track_id = int(raw_track_id)
            except (TypeError, ValueError):
                output.append(detection)
                continue

            history = self._motion_history.get(track_id)
            if history is None:
                history = deque(maxlen=self._motion_window_frames)
                self._motion_history[track_id] = history
            history.append(((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0))

            is_static = False
            if len(history) >= self._motion_window_frames:
                start_x, start_y = history[0]
                end_x, end_y = history[-1]
                average_speed = math.hypot(end_x - start_x, end_y - start_y) / max(1, len(history) - 1)
                is_static = average_speed < self._static_max_speed_px_per_frame
                detection["averageSpeedPxPerFrame"] = round(average_speed, 3)

            # Never suppress real vehicles or people; only static containers are suppressed
            cls_name = str(detection.get("class") or "").casefold()
            if cls_name in VEHICLE_CLASS_NAMES or cls_name == "person" or detection.get("source") == "custom":
                is_static = False

            if is_static:
                self._static_track_ids.add(track_id)
                # Prevent the missed-frame retention layer from resurrecting a
                # just-suppressed static container as a ghost box.
                if hasattr(self, "_retained_detections"):
                    self._retained_detections.pop(f"track:{track_id}", None)
                continue

            self._static_track_ids.discard(track_id)
            output.append(detection)
        return output

    def track(
        self,
        frame: np.ndarray,
        conf: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """
        Run YOLO detection and ByteTrack tracking on a single BGR OpenCV frame.
        Returns structured detection dictionaries with persistent trackId.
        Supports single model (world / standard YOLO) and hybrid ensemble.
        """
        if self.model is None or frame is None:
            return []

        threshold = conf if conf is not None else self.conf_threshold
        h, w = frame.shape[:2]
        if h == 0 or w == 0:
            return []

        class_ids = [
            int(class_id)
            for class_id, class_name in self.model.names.items()
            if class_name in self.area_target_classes
        ]
        if not class_ids and self.detector_kind != "hybrid":
            logger.error("Area target classes are unavailable in the loaded YOLO model: %s", self.area_target_classes)
            return []

        try:
            # 1. Primary Model Inference (YOLO-World or standard YOLO)
            reset_tracker = self._reset_tracker_on_next_frame
            results = self.model.track(
                frame,
                conf=min(threshold, self._track_continuation_confidence),
                classes=class_ids if class_ids else None,
                persist=not reset_tracker,
                tracker=self.tracker,
                imgsz=self.inference_size,
                device=self.device,
                verbose=False,
            )
            self._reset_tracker_on_next_frame = False
            detections: List[Dict[str, Any]] = []

            for r in results:
                boxes = r.boxes
                if boxes is None or len(boxes) == 0:
                    continue

                track_ids = None
                if boxes.id is not None:
                    track_ids = boxes.id.int().cpu().numpy().tolist()

                for i in range(len(boxes)):
                    xyxy = boxes.xyxy[i].cpu().numpy().tolist()
                    cls_id = int(boxes.cls[i].item())
                    confidence = float(boxes.conf[i].item())
                    model_class_name = self.model.names.get(cls_id, f"class_{cls_id}")
                    class_name, raw_class_name = self._canonicalize_detection_class(model_class_name)
                    if self.area_target_classes and model_class_name not in self.area_target_classes and class_name not in self.area_target_classes:
                        continue

                    track_id = int(track_ids[i]) if (track_ids is not None and i < len(track_ids)) else None
                    vietnamese_label = COCO_VIETNAMESE_MAPPING.get(class_name, class_name)

                    x1, y1, x2, y2 = [int(coord) for coord in xyxy]
                    x1 = max(0, min(w - 1, x1))
                    y1 = max(0, min(h - 1, y1))
                    x2 = max(x1 + 1, min(w, x2))
                    y2 = max(y1 + 1, min(h, y2))

                    detection = {
                        "trackId": track_id,
                        "bbox": [x1, y1, x2, y2],
                        "normalized_bbox": [
                            round(x1 / w, 4),
                            round(y1 / h, 4),
                            round(x2 / w, 4),
                            round(y2 / h, 4),
                        ],
                        "class": class_name,
                        "label": vietnamese_label,
                        "confidence": round(confidence, 3),
                        "source": "primary",
                    }
                    if raw_class_name:
                        detection["rawClass"] = raw_class_name
                    detections.append(detection)

            # 2. Auxiliary Model Inference in Hybrid Mode (COCO YOLO fallback)
            # The auxiliary COCO model is a fallback when YOLO-World has no confident target.
            # Running two independent trackers on every frame created duplicate
            # boxes and reduced the usable FPS below the monitor target.
            if self.detector_kind == "hybrid" and self.aux_model is not None and not detections:
                coco_target_ids = [
                    int(cid)
                    for cid, cname in self.aux_model.names.items()
                    if cname in ["person", "car", "truck", "bus", "motorcycle"]
                ]
                aux_results = self.aux_model.track(
                    frame,
                    conf=min(threshold, self._track_continuation_confidence),
                    classes=coco_target_ids,
                    persist=not reset_tracker,
                    tracker=self.tracker,
                    imgsz=self.inference_size,
                    device=self.device,
                    verbose=False,
                )
                for r in aux_results:
                    boxes = r.boxes
                    if boxes is None or len(boxes) == 0:
                        continue

                    track_ids = None
                    if boxes.id is not None:
                        track_ids = boxes.id.int().cpu().numpy().tolist()

                    for i in range(len(boxes)):
                        xyxy = boxes.xyxy[i].cpu().numpy().tolist()
                        cls_id = int(boxes.cls[i].item())
                        confidence = float(boxes.conf[i].item())
                        model_class_name = self.aux_model.names.get(cls_id, f"class_{cls_id}")
                        class_name, raw_class_name = self._canonicalize_detection_class(model_class_name)
                        track_id = int(track_ids[i]) if (track_ids is not None and i < len(track_ids)) else None
                        # Offset aux tracker IDs to avoid collision
                        if track_id is not None:
                            track_id = 1000 + track_id
                        vietnamese_label = COCO_VIETNAMESE_MAPPING.get(class_name, class_name)

                        x1, y1, x2, y2 = [int(coord) for coord in xyxy]
                        x1 = max(0, min(w - 1, x1))
                        y1 = max(0, min(h - 1, y1))
                        x2 = max(x1 + 1, min(w, x2))
                        y2 = max(y1 + 1, min(h, y2))

                        detection = {
                            "trackId": track_id,
                            "bbox": [x1, y1, x2, y2],
                            "normalized_bbox": [
                                round(x1 / w, 4),
                                round(y1 / h, 4),
                                round(x2 / w, 4),
                                round(y2 / h, 4),
                            ],
                            "class": class_name,
                            "label": vietnamese_label,
                            "confidence": round(confidence, 3),
                            "source": "aux",
                        }
                        if raw_class_name:
                            detection["rawClass"] = raw_class_name
                        detections.append(detection)

            detections = self._apply_track_hysteresis(detections)
            detections = self._apply_custom_augmentation(frame, detections, w, h)

            # --- Vehicle Assembly Engine ---
            # Merge adjacent cabin + trailer detections of container trucks into single unified vehicle boxes.
            detections = self._assemble_container_trucks(detections, w, h)

            # --- Cross-class & Cross-source NMS ---
            # YOLO-World can detect the same physical object under multiple text
            # prompts (e.g. "forklift" AND "truck" for the same vehicle, or cabin vs body).
            # We run an IoU + IoMin pass across all classes to guarantee only one
            # best box per physical object.
            detections = self._cross_class_nms(
                detections,
                iou_threshold=0.35,
                iomin_threshold=0.60,
            )

            detections = self._stabilize_track_classes(detections)
            detections = self._suppress_static_detections(detections)
            return self._retain_recent_detections(detections, w, h)
        except Exception as exc:
            logger.error("Error during YOLO tracking inference: %s", exc)
            try:
                return self._retain_recent_detections([], w, h)
            except Exception:
                return []

    def configure_custom_model(
        self,
        version_key: Optional[str],
        artifact_path: Optional[str],
        label_map: Optional[Dict[str, str]],
    ) -> None:
        """Load/unload an evaluated candidate without touching the base detector."""
        if version_key == self._custom_version_key:
            return
        if not version_key or not artifact_path:
            self._custom_model = None
            self._custom_version_key = None
            self._custom_label_map = {}
            self._custom_track_overrides.clear()
            self._custom_evidence.clear()
            self._retained_detections.clear()
            logger.info("Custom augmentation disabled; base YOLO remains active.")
            return
        candidate = Path(artifact_path)
        if not candidate.is_file():
            logger.warning("Custom augmentation artifact is missing: %s", candidate)
            return
        try:
            model = YOLO(str(candidate))
            model.to(self.device)
            self._custom_model = model
            self._custom_version_key = version_key
            self._custom_label_map = {str(label): str(base) for label, base in (label_map or {}).items()}
            self._custom_track_overrides.clear()
            self._custom_evidence.clear()
            self._retained_detections.clear()
            logger.info("Loaded custom augmentation candidate %s", version_key)
        except Exception as exc:
            logger.error("Failed to load custom augmentation %s: %s", version_key, exc)

    @staticmethod
    def default_custom_model_config() -> Optional[Dict[str, Any]]:
        """Return the configured v11n finetune when no DB version is active."""
        artifact_setting = os.getenv("CUSTOM_AUGMENT_ARTIFACT", DEFAULT_CUSTOM_AUGMENT_ARTIFACT).strip()
        if not artifact_setting:
            return None

        backend_root = Path(__file__).resolve().parents[2]
        data_root = backend_root / "data"
        artifact = Path(artifact_setting)
        if not artifact.is_absolute():
            artifact = data_root / artifact
        artifact = artifact.resolve()
        if data_root not in artifact.parents or not artifact.is_file():
            return None

        label_map: Dict[str, str] = {}
        configured_label_map = os.getenv("CUSTOM_AUGMENT_LABEL_MAP", "").strip()
        if configured_label_map:
            try:
                parsed = json.loads(configured_label_map)
                if isinstance(parsed, dict):
                    label_map = {str(label): str(base) for label, base in parsed.items()}
            except json.JSONDecodeError:
                logger.warning("CUSTOM_AUGMENT_LABEL_MAP is not valid JSON; falling back to labels.json")

        if not label_map:
            labels_file = artifact.parent / "labels.json"
            if labels_file.is_file():
                try:
                    parsed = json.loads(labels_file.read_text(encoding="utf-8"))
                    if isinstance(parsed, dict):
                        label_map = {str(label): str(base) for label, base in parsed.items()}
                except Exception as exc:
                    logger.warning("Could not read default custom labels from %s: %s", labels_file, exc)

        if not label_map:
            return None

        return {
            "version_key": os.getenv("CUSTOM_AUGMENT_VERSION_KEY", DEFAULT_CUSTOM_AUGMENT_VERSION),
            "artifact_path": str(artifact),
            "label_map": label_map,
        }

    @staticmethod
    def _overlap(first: List[int], second: List[int]) -> float:
        ax1, ay1, ax2, ay2 = first
        bx1, by1, bx2, by2 = second
        inter = max(0, min(ax2, bx2) - max(ax1, bx1)) * max(0, min(ay2, by2) - max(ay1, by1))
        if not inter:
            return 0.0
        first_area = max(1, (ax2 - ax1) * (ay2 - ay1))
        second_area = max(1, (bx2 - bx1) * (by2 - by1))
        return max(inter / (first_area + second_area - inter), inter / min(first_area, second_area))

    def _custom_base_class(self, custom_label: str) -> Optional[str]:
        base_class = self._custom_label_map.get(custom_label)
        if base_class:
            return base_class
        folded = custom_label.casefold()
        for label, base in self._custom_label_map.items():
            if label.casefold() == folded:
                return base
        return None

    @staticmethod
    def _normalized_bbox(bbox: List[int], width: int, height: int) -> List[float]:
        x1, y1, x2, y2 = bbox
        return [
            round(x1 / width, 4),
            round(y1 / height, 4),
            round(x2 / width, 4),
            round(y2 / height, 4),
        ]

    def _collect_custom_detections(
        self,
        image: np.ndarray,
        width: int,
        height: int,
        offset_x: int = 0,
        offset_y: int = 0,
        imgsz: Optional[int] = None,
        inference_mode: str = "full",
    ) -> List[Dict[str, Any]]:
        if self._custom_model is None or image.size == 0:
            return []
        results = self._custom_model(
            image,
            conf=self._custom_confidence,
            imgsz=imgsz or self._custom_full_frame_size,
            device=self.device,
            verbose=False,
        )
        detections: List[Dict[str, Any]] = []
        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue
            for index in range(len(boxes)):
                custom_label = str(self._custom_model.names.get(int(boxes.cls[index].item()), ""))
                base_class = self._custom_base_class(custom_label)
                if not base_class:
                    continue
                xyxy = boxes.xyxy[index].cpu().numpy().tolist()
                bbox = [
                    max(0, min(width - 1, offset_x + int(xyxy[0]))),
                    max(0, min(height - 1, offset_y + int(xyxy[1]))),
                    max(1, min(width, offset_x + int(xyxy[2]))),
                    max(1, min(height, offset_y + int(xyxy[3]))),
                ]
                if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
                    continue
                confidence = float(boxes.conf[index].item())
                detections.append({
                    "trackId": None,
                    "bbox": bbox,
                    "normalized_bbox": self._normalized_bbox(bbox, width, height),
                    "class": base_class,
                    "label": custom_label,
                    "confidence": round(confidence, 3),
                    "source": "custom",
                    "customInference": inference_mode,
                    "candidateVersion": self._custom_version_key,
                })
        return detections

    def _tile_windows(self, width: int, height: int) -> List[tuple[int, int, int, int]]:
        if not self._custom_tile_enabled:
            return []
        tile_size = min(self._custom_tile_size, max(width, height))
        tile_width = min(tile_size, width)
        tile_height = min(tile_size, height)
        if tile_width >= width and tile_height >= height:
            return []

        step_x = max(1, int(tile_width * (1.0 - self._custom_tile_overlap)))
        step_y = max(1, int(tile_height * (1.0 - self._custom_tile_overlap)))

        def positions(total: int, tile: int, step: int) -> List[int]:
            if total <= tile:
                return [0]
            values = list(range(0, total - tile + 1, step))
            if values[-1] != total - tile:
                values.append(total - tile)
            return values

        x_positions = positions(width, tile_width, step_x)
        y_positions = positions(height, tile_height, step_y)
        windows = [
            (x1, y1, x1 + tile_width, y1 + tile_height)
            for y1 in y_positions
            for x1 in x_positions
        ]
        if len(windows) <= self._custom_tile_max_tiles:
            return windows

        # Keep coverage stable across arbitrary resolutions by sampling evenly
        # across the full grid instead of favoring the top-left of large frames.
        max_tiles = self._custom_tile_max_tiles
        selected: List[tuple[int, int, int, int]] = []
        seen: set[tuple[int, int, int, int]] = set()
        for index in np.linspace(0, len(windows) - 1, num=max_tiles, dtype=int).tolist():
            window = windows[index]
            if window not in seen:
                selected.append(window)
                seen.add(window)
        for window in windows:
            if len(selected) >= max_tiles:
                break
            if window not in seen:
                selected.append(window)
                seen.add(window)
        return selected

    def _collect_custom_tiled_detections(
        self,
        frame: np.ndarray,
        width: int,
        height: int,
    ) -> List[Dict[str, Any]]:
        detections: List[Dict[str, Any]] = []
        for x1, y1, x2, y2 in self._tile_windows(width, height):
            crop = frame[y1:y2, x1:x2]
            if crop.size == 0:
                continue
            detections.extend(
                self._collect_custom_detections(
                    crop,
                    width,
                    height,
                    offset_x=x1,
                    offset_y=y1,
                    imgsz=self._custom_tile_size,
                    inference_mode="tile",
                )
            )
        if len(detections) <= 1:
            return detections
        return self._cross_class_nms(detections, iou_threshold=0.30, iomin_threshold=0.55)

    def _collect_custom_crop_detections(
        self,
        frame: np.ndarray,
        detections: List[Dict[str, Any]],
        width: int,
        height: int,
    ) -> List[Dict[str, Any]]:
        if not self._custom_crop_enabled or self._custom_crop_max_targets <= 0:
            return []
        targets = [
            item
            for item in detections
            if str(item.get("class") or "").casefold() in VEHICLE_CLASS_NAMES
        ]
        targets = sorted(targets, key=lambda item: float(item.get("confidence") or 0.0), reverse=True)
        crop_hits: List[Dict[str, Any]] = []
        for target in targets[: self._custom_crop_max_targets]:
            target_bbox = self._bbox_from_detection(target)
            if target_bbox is None:
                continue
            x1, y1, x2, y2 = target_bbox
            padding_x = int((x2 - x1) * self._custom_crop_padding)
            padding_y = int((y2 - y1) * self._custom_crop_padding)
            crop_x1, crop_y1 = max(0, x1 - padding_x), max(0, y1 - padding_y)
            crop_x2, crop_y2 = min(width, x2 + padding_x), min(height, y2 + padding_y)
            crop = frame[crop_y1:crop_y2, crop_x1:crop_x2]
            if crop.size == 0:
                continue
            crop_hits.extend(
                self._collect_custom_detections(
                    crop,
                    width,
                    height,
                    offset_x=crop_x1,
                    offset_y=crop_y1,
                    imgsz=self._custom_tile_size,
                    inference_mode="crop",
                )
            )
        if len(crop_hits) <= 1:
            return crop_hits
        return self._cross_class_nms(crop_hits, iou_threshold=0.30, iomin_threshold=0.55)

    def _best_custom_target(
        self,
        custom_bbox: List[int],
        detections: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        best: Optional[Dict[str, Any]] = None
        best_overlap = 0.0
        for detection in detections:
            class_name = str(detection.get("class") or "").casefold()
            if class_name not in VEHICLE_CLASS_NAMES:
                continue
            overlap = self._overlap(custom_bbox, detection["bbox"])
            if overlap > best_overlap:
                best = detection
                best_overlap = overlap
        return best if best_overlap >= self._custom_match_overlap else None

    @staticmethod
    def _bbox_area(bbox: List[int]) -> int:
        x1, y1, x2, y2 = bbox
        return max(1, (x2 - x1) * (y2 - y1))

    @staticmethod
    def _bbox_aspect_ratio(bbox: List[int]) -> float:
        x1, y1, x2, y2 = bbox
        return max(1, x2 - x1) / max(1, y2 - y1)

    @staticmethod
    def _normalized_area_ratio(detection: Dict[str, Any]) -> float:
        normalized = detection.get("normalized_bbox")
        if isinstance(normalized, (list, tuple)) and len(normalized) >= 4:
            try:
                x1, y1, x2, y2 = [float(value) for value in normalized[:4]]
                return max(0.0, x2 - x1) * max(0.0, y2 - y1)
            except (TypeError, ValueError):
                return 0.0
        return 0.0

    def _ensure_custom_gate_state(self) -> None:
        if not hasattr(self, "_custom_evidence"):
            self._custom_evidence = {}
        if not hasattr(self, "_custom_evidence_next_id"):
            self._custom_evidence_next_id = 1
        if not hasattr(self, "_custom_promote_confidence"):
            self._custom_promote_confidence = DEFAULT_CUSTOM_PROMOTE_CONFIDENCE
        if not hasattr(self, "_custom_instant_confidence"):
            self._custom_instant_confidence = DEFAULT_CUSTOM_INSTANT_CONFIDENCE
        if not hasattr(self, "_custom_confirm_frames"):
            self._custom_confirm_frames = DEFAULT_CUSTOM_CONFIRM_FRAMES
        if not hasattr(self, "_custom_confirm_window"):
            self._custom_confirm_window = DEFAULT_CUSTOM_CONFIRM_WINDOW
        if not hasattr(self, "_custom_confirm_window_seconds"):
            self._custom_confirm_window_seconds = DEFAULT_CUSTOM_CONFIRM_WINDOW_SECONDS
        if not hasattr(self, "_reach_stacker_min_aspect"):
            self._reach_stacker_min_aspect = DEFAULT_REACH_STACKER_MIN_ASPECT
        if not hasattr(self, "_reach_stacker_narrow_min_confidence"):
            self._reach_stacker_narrow_min_confidence = DEFAULT_REACH_STACKER_NARROW_MIN_CONFIDENCE
        if not hasattr(self, "_reach_stacker_max_area_ratio"):
            self._reach_stacker_max_area_ratio = DEFAULT_REACH_STACKER_MAX_AREA_RATIO
        if not hasattr(self, "_reach_stacker_custom_only_compact_aspect"):
            self._reach_stacker_custom_only_compact_aspect = DEFAULT_REACH_STACKER_CUSTOM_ONLY_COMPACT_ASPECT
        if not hasattr(self, "_reach_stacker_custom_only_large_area_ratio"):
            self._reach_stacker_custom_only_large_area_ratio = DEFAULT_REACH_STACKER_CUSTOM_ONLY_LARGE_AREA_RATIO
        if not hasattr(self, "_reach_stacker_custom_only_compact_min_confidence"):
            self._reach_stacker_custom_only_compact_min_confidence = DEFAULT_REACH_STACKER_CUSTOM_ONLY_COMPACT_MIN_CONFIDENCE
        if not hasattr(self, "_reach_stacker_target_compact_aspect"):
            self._reach_stacker_target_compact_aspect = DEFAULT_REACH_STACKER_TARGET_COMPACT_ASPECT
        if not hasattr(self, "_reach_stacker_target_compact_min_confidence"):
            self._reach_stacker_target_compact_min_confidence = DEFAULT_REACH_STACKER_TARGET_COMPACT_MIN_CONFIDENCE
        if not hasattr(self, "_reach_stacker_long_aspect"):
            self._reach_stacker_long_aspect = DEFAULT_REACH_STACKER_LONG_ASPECT
        if not hasattr(self, "_reach_stacker_long_max_area_ratio"):
            self._reach_stacker_long_max_area_ratio = DEFAULT_REACH_STACKER_LONG_MAX_AREA_RATIO
        if not hasattr(self, "_reach_stacker_long_min_confidence"):
            self._reach_stacker_long_min_confidence = DEFAULT_REACH_STACKER_LONG_MIN_CONFIDENCE
        if not hasattr(self, "_reach_stacker_max_aspect"):
            self._reach_stacker_max_aspect = DEFAULT_REACH_STACKER_MAX_ASPECT
        if not hasattr(self, "_reach_stacker_min_height_ratio"):
            self._reach_stacker_min_height_ratio = DEFAULT_REACH_STACKER_MIN_HEIGHT_RATIO
        if not hasattr(self, "_custom_tile_enabled"):
            self._custom_tile_enabled = os.getenv("CUSTOM_AUGMENT_TILE_ENABLED", "false").strip().casefold() in {"1", "true", "yes", "on"}
        if not hasattr(self, "_custom_tile_size"):
            self._custom_tile_size = int(os.getenv("CUSTOM_AUGMENT_TILE_SIZE", str(DEFAULT_CUSTOM_TILE_SIZE)))
        if not hasattr(self, "_custom_tile_overlap"):
            self._custom_tile_overlap = float(os.getenv("CUSTOM_AUGMENT_TILE_OVERLAP", str(DEFAULT_CUSTOM_TILE_OVERLAP)))
        if not hasattr(self, "_custom_tile_max_tiles"):
            self._custom_tile_max_tiles = int(os.getenv("CUSTOM_AUGMENT_TILE_MAX_TILES", str(DEFAULT_CUSTOM_TILE_MAX_TILES)))
        if not hasattr(self, "_custom_crop_enabled"):
            self._custom_crop_enabled = os.getenv("CUSTOM_AUGMENT_CROP_ENABLED", "false").strip().casefold() in {"1", "true", "yes", "on"}
        if not hasattr(self, "_custom_crop_max_targets"):
            self._custom_crop_max_targets = int(os.getenv("CUSTOM_AUGMENT_CROP_MAX_TARGETS", str(DEFAULT_CUSTOM_CROP_MAX_TARGETS)))
        if not hasattr(self, "_custom_crop_padding"):
            self._custom_crop_padding = float(os.getenv("CUSTOM_AUGMENT_CROP_PADDING", str(DEFAULT_CUSTOM_CROP_PADDING)))

    def _custom_candidate_shape_ok(
        self,
        custom: Dict[str, Any],
        target: Optional[Dict[str, Any]],
    ) -> bool:
        custom_bbox = self._bbox_from_detection(custom)
        if custom_bbox is None:
            return False
        custom_aspect = self._bbox_aspect_ratio(custom_bbox)
        custom_area_ratio = self._normalized_area_ratio(custom)

        # Extremely narrow noise box filter (aspect < 0.25)
        if custom_aspect < 0.25:
            return False
        # Extremely huge box taking entire screen (> 75% of screen area)
        if custom_area_ratio > 0.75:
            return False

        custom_class = str(custom.get("class") or "").casefold()
        if custom_class == "reach stacker":
            normalized = custom.get("normalized_bbox") or []
            try:
                height_ratio = max(0.0, float(normalized[3]) - float(normalized[1]))
                y2_ratio = float(normalized[3])
            except (IndexError, TypeError, ValueError):
                height_ratio = 0.0
                y2_ratio = 0.0

            # 1. Aspect ratio: Reach stackers have wide chassis & boom (aspect 0.75 - 3.50).
            # Tall vertical container trucks (aspect < 0.75) are trucks, not reach stackers.
            if custom_aspect < self._reach_stacker_min_aspect:
                return False
            if custom_aspect > self._reach_stacker_max_aspect:
                return False

            # 2. Area ratio: Reach stackers in yard occupy <= 10% of screen.
            # Massive foreground container trucks taking > 10% of frame are trucks.
            if custom_area_ratio > self._reach_stacker_max_area_ratio:
                return False

            # 3. Y2 position: Foreground vehicles extending to bottom edge (y2 > 0.85) with tall aspect are trucks.
            if y2_ratio > 0.85 and custom_aspect < 0.90:
                return False

            if height_ratio < self._reach_stacker_min_height_ratio:
                return False

            # 4. Minimum size: Reach stacker is massive heavy machinery.
            # Small distant passenger cars (area < 1.0% or height < 5.5%) are not reach stackers.
            if custom_area_ratio < 0.010 or height_ratio < 0.055:
                return False

        return True

    def _custom_candidate_allows_instant_promotion(
        self,
        custom: Dict[str, Any],
        target: Optional[Dict[str, Any]],
    ) -> bool:
        confidence = float(custom.get("confidence") or 0.0)
        custom_class = str(custom.get("class") or "").casefold()
        if target is None:
            return confidence >= 0.35
        if custom_class == "reach stacker" and target is not None:
            target_class = str(target.get("class") or "").casefold()
            target_raw = str(target.get("rawClass") or "").casefold()
            is_standard_truck = (target_class == "truck" and target_raw not in {"boat", "train"})
            if is_standard_truck:
                # A regular standard truck requires >= 0.60 confidence for instant promotion
                return confidence >= 0.60
        return confidence >= self._custom_instant_confidence

    def _custom_candidate_promote_confidence(
        self,
        custom: Dict[str, Any],
        target: Optional[Dict[str, Any]],
    ) -> float:
        return self._custom_promote_confidence

    def _find_custom_evidence_match(self, custom: Dict[str, Any]) -> Optional[str]:
        bbox = self._bbox_from_detection(custom)
        if bbox is None:
            return None
        now = self._now()
        class_name = str(custom.get("class") or "").casefold()
        best_key: Optional[str] = None
        best_score = 0.0
        for key, record in self._custom_evidence.items():
            if str(record.get("class") or "").casefold() != class_name:
                continue
            age_frames = self._custom_frame_index - int(record.get("last_seen", -1))
            age_seconds = now - float(record.get("last_seen_time", -1e9))
            in_frame_window = age_frames <= self._custom_confirm_window
            in_time_window = self._custom_confirm_window_seconds > 0.0 and age_seconds <= self._custom_confirm_window_seconds
            if not in_frame_window and not in_time_window:
                continue
            retained_bbox = self._bbox_from_detection(record.get("detection") or {})
            if retained_bbox is None:
                continue
            overlap = self._overlap(bbox, retained_bbox)
            distance_ratio = self._center_distance_ratio(bbox, retained_bbox)
            if overlap < 0.18 and distance_ratio > 0.75:
                continue
            score = overlap + max(0.0, 1.0 - distance_ratio) * 0.25
            if score > best_score:
                best_key = key
                best_score = score
        return best_key

    def _custom_evidence_key(
        self,
        custom: Dict[str, Any],
        target: Optional[Dict[str, Any]],
    ) -> str:
        class_name = str(custom.get("class") or "custom").casefold()
        if target is not None and target.get("trackId") is not None:
            try:
                return f"track:{int(target['trackId'])}:{class_name}"
            except (TypeError, ValueError):
                pass

        matched = self._find_custom_evidence_match(custom)
        if matched:
            return matched

        key = f"custom:{self._custom_evidence_next_id}:{class_name}"
        self._custom_evidence_next_id += 1
        return key

    def _custom_candidate_confirmed(
        self,
        custom: Dict[str, Any],
        target: Optional[Dict[str, Any]],
    ) -> bool:
        self._ensure_custom_gate_state()
        if not self._custom_candidate_shape_ok(custom, target):
            return False

        custom_conf = float(custom.get("confidence") or 0.0)
        custom_class = str(custom.get("class") or "").casefold()

        # Allow finetuned reach stacker detections to refine base YOLO truck guesses ONLY when geometric profile matches
        if target is not None and custom_class == "reach stacker":
            target_class = str(target.get("class") or "").casefold()
            target_conf = float(target.get("confidence") or 0.0)
            target_bbox = self._bbox_from_detection(target)
            if target_class == "truck" and target_bbox:
                target_aspect = self._bbox_aspect_ratio(target_bbox)
                target_area = self._normalized_area_ratio(target)
                # Tall vertical container trucks (aspect < 0.75 or area > 0.09) are regular trucks, never reach stackers!
                if target_aspect < 0.75 or target_area > 0.09:
                    return False
            if target_class == "truck" and target_conf >= 0.85 and custom_conf < 0.25:
                return False

        key = self._custom_evidence_key(custom, target)
        now = self._now()
        confidence = float(custom.get("confidence") or 0.0)
        previous = self._custom_evidence.get(key)
        if previous:
            age_frames = self._custom_frame_index - int(previous.get("last_seen", -1))
            age_seconds = now - float(previous.get("last_seen_time", -1e9))
            in_frame_window = age_frames <= self._custom_confirm_window
            in_time_window = self._custom_confirm_window_seconds > 0.0 and age_seconds <= self._custom_confirm_window_seconds
        else:
            age_frames = self._custom_confirm_window + 1
            in_frame_window = False
            in_time_window = False

        if previous and (in_frame_window or in_time_window):
            # Multiple overlapping full/tile/crop candidates in the same frame
            # are one observation, not multiple confirmations.
            increment = 0 if age_frames == 0 else 1
            hits = int(previous.get("hits", 0)) + increment
            max_confidence = max(float(previous.get("max_confidence", 0.0)), confidence)
            confirmed = bool(previous.get("confirmed"))
        else:
            hits = 1
            max_confidence = confidence
            confirmed = False

        confirmed = confirmed or self._custom_candidate_allows_instant_promotion(custom, target)
        promote_confidence = self._custom_candidate_promote_confidence(custom, target)
        confirmed = confirmed or (hits >= self._custom_confirm_frames and max_confidence >= promote_confidence)
        self._custom_evidence[key] = {
            "class": custom.get("class"),
            "detection": self._clone_detection(custom),
            "hits": hits,
            "last_seen": self._custom_frame_index,
            "last_seen_time": now,
            "max_confidence": max_confidence,
            "confirmed": confirmed,
        }
        self._expire_custom_evidence()
        return confirmed

    def _expire_custom_evidence(self) -> None:
        now = self._now()
        stale_before = self._custom_frame_index - max(self._custom_confirm_window * 3, 18)
        for key, record in list(self._custom_evidence.items()):
            stale_by_frame = int(record.get("last_seen", self._custom_frame_index)) < stale_before
            stale_by_time = (
                self._custom_confirm_window_seconds > 0.0
                and now - float(record.get("last_seen_time", now)) > self._custom_confirm_window_seconds * 3
            )
            if stale_by_frame and stale_by_time:
                del self._custom_evidence[key]

    def _apply_custom_detection(
        self,
        target: Dict[str, Any],
        custom: Dict[str, Any],
        width: int,
        height: int,
    ) -> None:
        target.update({
            "bbox": custom["bbox"],
            "normalized_bbox": self._normalized_bbox(custom["bbox"], width, height),
            "class": custom["class"],
            "label": custom["label"],
            "confidence": custom["confidence"],
            "source": "custom",
            "candidateVersion": self._custom_version_key,
            "customConfirmed": True,
        })
        if custom.get("customInference"):
            target["customInference"] = custom["customInference"]
        track_id = target.get("trackId")
        if track_id is not None:
            self._custom_track_overrides[int(track_id)] = {
                "class": custom["class"],
                "label": custom["label"],
                "confidence": custom["confidence"],
                "customConfirmed": True,
                "customInference": custom.get("customInference"),
                "seen": self._custom_frame_index,
                "bbox": list(custom["bbox"]),
            }

    def _apply_custom_augmentation(
        self,
        frame: np.ndarray,
        detections: List[Dict[str, Any]],
        width: int,
        height: int,
    ) -> List[Dict[str, Any]]:
        """Use a candidate only to refine an existing tracked base detection.

        This avoids a second global tracker and means candidate activation cannot
        remove people or ordinary COCO vehicles detected by the base pipeline.
        """
        self._ensure_custom_gate_state()
        self._custom_frame_index += 1
        if self._custom_model is not None and self._custom_frame_index % self._custom_interval == 0:
            try:
                candidate_hits: List[Dict[str, Any]] = []
                if self._custom_full_frame:
                    candidate_hits.extend(
                        self._collect_custom_detections(
                            frame,
                            width,
                            height,
                            imgsz=self._custom_full_frame_size,
                            inference_mode="full",
                        )
                    )
                if self._custom_tile_enabled:
                    candidate_hits.extend(self._collect_custom_tiled_detections(frame, width, height))
                if self._custom_crop_enabled:
                    candidate_hits.extend(self._collect_custom_crop_detections(frame, detections, width, height))
                if len(candidate_hits) > 1:
                    candidate_hits = self._cross_class_nms(candidate_hits, iou_threshold=0.30, iomin_threshold=0.55)

                for custom in candidate_hits:
                    target = self._best_custom_target(custom["bbox"], detections)
                    if target and self._custom_candidate_confirmed(custom, target):
                        self._apply_custom_detection(target, custom, width, height)
                    elif target is None and self._custom_candidate_confirmed(custom, None):
                        custom["customConfirmed"] = True
                        detections.append(custom)

            except Exception as exc:
                logger.warning("Custom augmentation inference failed; retaining base detections: %s", exc)

        expiry = self._custom_frame_index - max(30, self._custom_interval * 15)
        for track_id, override in list(self._custom_track_overrides.items()):
            if override["seen"] < expiry:
                del self._custom_track_overrides[track_id]
        for detection in detections:
            track_id = detection.get("trackId")
            override = self._custom_track_overrides.get(int(track_id)) if track_id is not None else None
            if override:
                # Spatial continuity check: prevent stale recycled track ID collisions
                prev_bbox = override.get("bbox")
                if prev_bbox is not None and "bbox" in detection:
                    curr_cx = (detection["bbox"][0] + detection["bbox"][2]) / 2.0
                    curr_cy = (detection["bbox"][1] + detection["bbox"][3]) / 2.0
                    prev_cx = (prev_bbox[0] + prev_bbox[2]) / 2.0
                    prev_cy = (prev_bbox[1] + prev_bbox[3]) / 2.0
                    dist = math.hypot(curr_cx - prev_cx, curr_cy - prev_cy)
                    if dist > 350:  # Distance too far = new object with recycled ID
                        del self._custom_track_overrides[int(track_id)]
                        continue

                target_cls = str(detection.get("class") or "").casefold()
                target_raw = str(detection.get("rawClass") or "").casefold()
                is_standard_truck = (target_cls == "truck" and target_raw not in {"boat", "train"})
                # If base YOLO sees a confident regular truck and custom model hasn't recently confirmed reach stacker, revert override
                if is_standard_truck and float(detection.get("confidence", 0.0)) >= 0.50 and (self._custom_frame_index - override["seen"]) > self._custom_interval * 3:
                    del self._custom_track_overrides[int(track_id)]
                    continue

                # Smoothly update override bbox with current position
                override["bbox"] = list(detection["bbox"])
                detection.update({key: value for key, value in override.items() if key not in {"seen", "bbox"}})
                detection["candidateVersion"] = self._custom_version_key
                detection["source"] = "custom"
                detection["customConfirmed"] = True
        return detections

    def _ensure_retention_state(self) -> None:
        if not hasattr(self, "_retained_detections"):
            self._retained_detections = {}
        if not hasattr(self, "_retention_frame_index"):
            self._retention_frame_index = 0
        if not hasattr(self, "_retention_next_synthetic_track_id"):
            self._retention_next_synthetic_track_id = -1
        if not hasattr(self, "_retention_frames"):
            self._retention_frames = DEFAULT_RETENTION_FRAMES
        if not hasattr(self, "_retention_seconds"):
            self._retention_seconds = DEFAULT_RETENTION_SECONDS
        if not hasattr(self, "_box_smoothing_alpha"):
            self._box_smoothing_alpha = DEFAULT_BOX_SMOOTHING

    @staticmethod
    def _clone_detection(detection: Dict[str, Any]) -> Dict[str, Any]:
        clone = dict(detection)
        if isinstance(clone.get("bbox"), (list, tuple)):
            clone["bbox"] = list(clone["bbox"])
        if isinstance(clone.get("normalized_bbox"), (list, tuple)):
            clone["normalized_bbox"] = list(clone["normalized_bbox"])
        if isinstance(clone.get("zoneMatches"), list):
            clone["zoneMatches"] = [dict(match) for match in clone["zoneMatches"]]
        return clone

    @staticmethod
    def _bbox_from_detection(detection: Dict[str, Any]) -> Optional[List[int]]:
        bbox = detection.get("bbox")
        if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
            return None
        try:
            return [int(round(float(value))) for value in bbox[:4]]
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _detection_family(detection: Dict[str, Any]) -> str:
        class_name = str(detection.get("class") or "").casefold()
        if class_name in VEHICLE_CLASS_NAMES:
            return "vehicle"
        return class_name or "unknown"

    @staticmethod
    def _center_distance_ratio(first: List[int], second: List[int]) -> float:
        fx1, fy1, fx2, fy2 = first
        sx1, sy1, sx2, sy2 = second
        first_center = ((fx1 + fx2) / 2.0, (fy1 + fy2) / 2.0)
        second_center = ((sx1 + sx2) / 2.0, (sy1 + sy2) / 2.0)
        distance = float(np.hypot(first_center[0] - second_center[0], first_center[1] - second_center[1]))
        first_scale = max(1.0, ((fx2 - fx1) + (fy2 - fy1)) / 2.0)
        second_scale = max(1.0, ((sx2 - sx1) + (sy2 - sy1)) / 2.0)
        return distance / max(first_scale, second_scale)

    @staticmethod
    def _has_custom_identity(detection: Dict[str, Any]) -> bool:
        return bool(detection.get("candidateVersion")) or detection.get("source") == "custom"

    def _apply_retained_label_hint(
        self,
        target: Dict[str, Any],
        retained: Dict[str, Any],
    ) -> None:
        if (
            not self._has_custom_identity(retained)
            or not retained.get("customConfirmed")
            or self._has_custom_identity(target)
        ):
            return
        for key in ("class", "label", "rawClass", "candidateVersion", "customConfirmed"):
            if key in retained:
                target[key] = retained[key]
            elif key in target and key in {"rawClass", "candidateVersion", "customConfirmed"}:
                target.pop(key, None)
        target["source"] = retained.get("source", target.get("source"))

    def _find_retained_match(
        self,
        detection: Dict[str, Any],
        used_keys: set[str],
        custom_only: bool = False,
    ) -> Optional[str]:
        bbox = self._bbox_from_detection(detection)
        if bbox is None:
            return None
        now = self._now()
        family = self._detection_family(detection)
        best_key: Optional[str] = None
        best_score = 0.0
        match_window = max(self._retention_frames * 2, self._retention_frames + 4)

        for key, record in self._retained_detections.items():
            if key in used_keys:
                continue
            age = self._retention_frame_index - int(record.get("last_seen", -match_window - 1))
            age_seconds = now - float(record.get("last_seen_time", -1e9))
            in_frame_window = 0 <= age <= match_window
            in_time_window = self._retention_seconds > 0.0 and age_seconds <= max(self._retention_seconds * 1.5, 0.1)
            if not in_frame_window and not in_time_window:
                continue
            retained = record.get("detection")
            if not isinstance(retained, dict):
                continue
            if custom_only and not self._has_custom_identity(retained):
                continue
            retained_bbox = self._bbox_from_detection(retained)
            if retained_bbox is None:
                continue
            retained_family = self._detection_family(retained)
            same_family = family == retained_family or (family == "vehicle" and retained_family == "vehicle")
            overlap = self._overlap(bbox, retained_bbox)
            distance_ratio = self._center_distance_ratio(bbox, retained_bbox)
            if overlap < 0.20 and not (same_family and distance_ratio <= 0.80):
                continue
            score = overlap + max(0.0, 1.0 - distance_ratio) * 0.25
            if custom_only:
                score += 0.20
            if score > best_score:
                best_key = key
                best_score = score

        return best_key

    def _next_synthetic_track_id(self) -> int:
        track_id = self._retention_next_synthetic_track_id
        self._retention_next_synthetic_track_id -= 1
        return track_id

    def _smooth_detection_bbox(
        self,
        current: Dict[str, Any],
        previous: Dict[str, Any],
        width: int,
        height: int,
    ) -> None:
        alpha = self._box_smoothing_alpha
        if alpha <= 0.0:
            return
        current_bbox = self._bbox_from_detection(current)
        previous_bbox = self._bbox_from_detection(previous)
        if current_bbox is None or previous_bbox is None:
            return
        if self._overlap(current_bbox, previous_bbox) < 0.10:
            return
        smoothed = [
            int(round((coord * alpha) + (previous_bbox[index] * (1.0 - alpha))))
            for index, coord in enumerate(current_bbox)
        ]
        smoothed[0] = max(0, min(width - 1, smoothed[0]))
        smoothed[1] = max(0, min(height - 1, smoothed[1]))
        smoothed[2] = max(smoothed[0] + 1, min(width, smoothed[2]))
        smoothed[3] = max(smoothed[1] + 1, min(height, smoothed[3]))
        current["bbox"] = smoothed
        current["normalized_bbox"] = self._normalized_bbox(smoothed, width, height)

    def _overlaps_output(self, detection: Dict[str, Any], output: List[Dict[str, Any]]) -> bool:
        bbox = self._bbox_from_detection(detection)
        if bbox is None:
            return True
        for existing in output:
            existing_bbox = self._bbox_from_detection(existing)
            if existing_bbox is None:
                continue
            if self._overlap(bbox, existing_bbox) >= 0.45:
                return True
        return False

    def _retain_recent_detections(
        self,
        detections: List[Dict[str, Any]],
        width: int,
        height: int,
    ) -> List[Dict[str, Any]]:
        """Hold short detector misses so boxes and labels do not flicker."""
        self._ensure_retention_state()
        self._retention_frame_index += 1
        current_frame = self._retention_frame_index
        now = self._now()
        if self._retention_frames <= 0 and self._retention_seconds <= 0.0:
            return detections

        output: List[Dict[str, Any]] = []
        used_keys: set[str] = set()
        keys_to_remove: set[str] = set()

        for detection in detections:
            current = self._clone_detection(detection)
            bbox = self._bbox_from_detection(current)
            if bbox is None:
                output.append(current)
                continue

            key: Optional[str] = None
            raw_track_id = current.get("trackId")
            if raw_track_id is not None:
                try:
                    track_id = int(raw_track_id)
                    current["trackId"] = track_id
                    key = f"track:{track_id}"
                except (TypeError, ValueError):
                    key = None
                hint_key = self._find_retained_match(current, used_keys, custom_only=True)
                if hint_key:
                    retained = self._retained_detections[hint_key]["detection"]
                    self._apply_retained_label_hint(current, retained)
                    if hint_key != key:
                        used_keys.add(hint_key)
                        keys_to_remove.add(hint_key)
            else:
                match_key = self._find_retained_match(current, used_keys)
                if match_key:
                    retained = self._retained_detections[match_key]["detection"]
                    retained_track_id = retained.get("trackId")
                    if retained_track_id is not None:
                        current["trackId"] = int(retained_track_id)
                    self._apply_retained_label_hint(current, retained)
                    key = match_key
                elif self._has_custom_identity(current):
                    track_id = self._next_synthetic_track_id()
                    current["trackId"] = track_id
                    key = f"synthetic:{track_id}"

            previous = self._retained_detections.get(key, {}).get("detection") if key else None
            if isinstance(previous, dict):
                self._smooth_detection_bbox(current, previous, width, height)

            if key:
                used_keys.add(key)
                stored = self._clone_detection(current)
                stored.pop("retained", None)
                stored["normalized_bbox"] = self._normalized_bbox(stored["bbox"], width, height)
                self._retained_detections[key] = {
                    "detection": stored,
                    "last_seen": current_frame,
                    "last_seen_time": now,
                }

            output.append(current)

        for key in keys_to_remove:
            self._retained_detections.pop(key, None)

        for key, record in list(self._retained_detections.items()):
            if key in used_keys:
                continue
            age = current_frame - int(record.get("last_seen", current_frame))
            age_seconds = now - float(record.get("last_seen_time", now))
            expired_by_frame = self._retention_frames > 0 and age > self._retention_frames
            expired_by_time = self._retention_seconds > 0.0 and age_seconds > self._retention_seconds
            if (
                (self._retention_seconds > 0.0 and expired_by_time)
                or (self._retention_seconds <= 0.0 and expired_by_frame)
            ):
                del self._retained_detections[key]
                continue
            retained = record.get("detection")
            if not isinstance(retained, dict):
                del self._retained_detections[key]
                continue
            if self._overlaps_output(retained, output):
                continue
            ghost = self._clone_detection(retained)
            ghost["retained"] = True
            try:
                confidence = float(ghost.get("confidence") or 0.0)
            except (TypeError, ValueError):
                confidence = 0.0
            frame_decay = age / max(1, self._retention_frames + 1) if self._retention_frames > 0 else 0.0
            time_decay = age_seconds / max(0.1, self._retention_seconds) if self._retention_seconds > 0.0 else 0.0
            decay_progress = max(frame_decay, time_decay)
            decay = max(0.50, 1.0 - decay_progress * 0.50)
            ghost["confidence"] = round(confidence * decay, 3)
            output.append(ghost)

        expiry = current_frame - max(self._retention_frames * 4, 60)
        for key, record in list(self._retained_detections.items()):
            stale_by_frame = int(record.get("last_seen", current_frame)) < expiry
            stale_by_time = (
                self._retention_seconds > 0.0
                and now - float(record.get("last_seen_time", now)) > max(self._retention_seconds * 4, 8.0)
            )
            if stale_by_frame and stale_by_time:
                del self._retained_detections[key]

        return output

    def reset_tracking(self) -> None:
        """Start a fresh ByteTrack sequence after a local-video seek."""
        self._reset_tracker_on_next_frame = True
        self._track_class_history.clear()
        self._track_last_seen.clear()
        self._ensure_temporal_state()
        self._hysteresis_tracks.clear()
        self._hysteresis_confidence.clear()
        self._hysteresis_frame_index = 0
        self._motion_history.clear()
        self._static_track_ids.clear()
        self._custom_track_overrides.clear()
        self._ensure_retention_state()
        self._retained_detections.clear()
        self._retention_frame_index = 0

    def _stabilize_track_classes(self, detections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Apply an exponentially decayed class vote per persistent ByteTrack ID."""
        self._tracking_frame_index += 1
        current_frame = self._tracking_frame_index

        for detection in detections:
            raw_track_id = detection.get("trackId")
            if raw_track_id is None:
                continue
            track_id = int(raw_track_id)
            raw_class = str(detection.get("class") or "")
            if not raw_class:
                continue

            # Distinguish compact passenger cars (SUV/sedan) from large cargo trucks:
            # A vehicle with small area (area_ratio <= 0.008) and wide aspect (aspect >= 1.30) and height <= 110px is a CAR, never a TRUCK
            if raw_class == "truck" and "bbox" in detection:
                box = detection["bbox"]
                w_box = box[2] - box[0]
                h_box = box[3] - box[1]
                aspect_box = w_box / max(1, h_box)
                norm = detection.get("normalized_bbox")
                area_ratio_box = (norm[2] - norm[0]) * (norm[3] - norm[1]) if norm and len(norm) >= 4 else 0.0
                if area_ratio_box <= 0.008 and aspect_box >= 1.30 and h_box <= 110:
                    raw_class = "car"
                    detection["class"] = raw_class
                    detection["label"] = COCO_VIETNAMESE_MAPPING.get(raw_class, raw_class)

            history = self._track_class_history.setdefault(track_id, {})
            # An active candidate has already passed its held-out quality gate
            # and is deliberately refining this tracked base box.  Do not let
            # an older generic YOLO-World vote (truck/car) overwrite the
            # verified custom label (for example, forklift) for several
            # frames after the candidate first sees it.
            if detection.get("candidateVersion"):
                history.clear()
                history[raw_class] = max(1.0, float(detection.get("confidence") or 0.0))
                stable_class = raw_class
            else:
                for class_name in list(history):
                    history[class_name] *= 0.78
                    if history[class_name] < 0.01:
                        del history[class_name]

                history[raw_class] = history.get(raw_class, 0.0) + float(detection.get("confidence") or 0.0)
                stable_class = max(history, key=history.get)
            self._track_last_seen[track_id] = current_frame

            if stable_class != raw_class:
                detection["rawClass"] = raw_class
                detection["class"] = stable_class
                detection["label"] = COCO_VIETNAMESE_MAPPING.get(stable_class, stable_class)

        # Prevent growth if an ID is never reused after an object leaves view.
        stale_before = current_frame - 120
        for track_id, last_seen in list(self._track_last_seen.items()):
            if last_seen < stale_before:
                self._track_last_seen.pop(track_id, None)
                self._track_class_history.pop(track_id, None)

        return detections

    def _assemble_container_trucks(
        self,
        detections: List[Dict[str, Any]],
        width: int,
        height: int,
    ) -> List[Dict[str, Any]]:
        """
        Vehicle Assembly Engine:
        Merges fragmented detections of a single container truck (e.g. cabin + trailer)
        into one unified bounding box with class 'truck' and label 'Xe tải'.
        """
        if len(detections) < 2:
            return detections

        merged_any = True
        iterations = 0
        while merged_any and iterations < 10:
            iterations += 1
            merged_any = False
            n = len(detections)
            for i in range(n):
                for j in range(i + 1, n):
                    det_a = detections[i]
                    det_b = detections[j]
                    cls_a = str(det_a.get("class") or "").casefold()
                    cls_b = str(det_b.get("class") or "").casefold()

                    valid_vehicle_classes = {"truck", "car", "container"}
                    if cls_a not in valid_vehicle_classes or cls_b not in valid_vehicle_classes:
                        continue
                    if cls_a in {"reach stacker", "forklift"} or cls_b in {"reach stacker", "forklift"}:
                        continue
                    if det_a.get("source") == "custom" or det_b.get("source") == "custom":
                        continue

                    box_a = det_a.get("bbox")
                    box_b = det_b.get("bbox")
                    if not box_a or not box_b:
                        continue

                    ax1, ay1, ax2, ay2 = box_a
                    bx1, by1, bx2, by2 = box_b

                    gap_x = max(0, max(ax1, bx1) - min(ax2, bx2))
                    gap_y = max(0, max(ay1, by1) - min(ay2, by2))
                    overlap_x = max(0, min(ax2, bx2) - max(ax1, bx1))
                    overlap_y = max(0, min(ay2, by2) - max(ay1, by1))

                    w_a, h_a = max(1, ax2 - ax1), max(1, ay2 - ay1)
                    w_b, h_b = max(1, bx2 - bx1), max(1, by2 - by1)

                    touching = (gap_x <= 40 and overlap_y / min(h_a, h_b) >= 0.20) or \
                               (gap_y <= 40 and overlap_x / min(w_a, w_b) >= 0.20) or \
                               (self._overlap(box_a, box_b) > 0.05)

                    if not touching:
                        continue

                    comb_x1, comb_y1 = min(ax1, bx1), min(ay1, by1)
                    comb_x2, comb_y2 = max(ax2, bx2), max(ay2, by2)
                    comb_w, comb_h = max(1, comb_x2 - comb_x1), max(1, comb_y2 - comb_y1)
                    comb_aspect = max(comb_w / comb_h, comb_h / comb_w)

                    if comb_aspect > 5.5:
                        continue

                    chosen_track = det_a.get("trackId") if cls_a == "truck" else (det_b.get("trackId") or det_a.get("trackId"))
                    max_conf = max(float(det_a.get("confidence", 0.0)), float(det_b.get("confidence", 0.0)))
                    merged_bbox = [comb_x1, comb_y1, comb_x2, comb_y2]

                    merged_det = {
                        "trackId": chosen_track,
                        "bbox": merged_bbox,
                        "normalized_bbox": self._normalized_bbox(merged_bbox, width, height),
                        "class": "truck",
                        "label": COCO_VIETNAMESE_MAPPING.get("truck", "Xe tải"),
                        "confidence": round(max_conf, 3),
                        "source": "assembled",
                    }
                    if det_a.get("rawClass") or det_b.get("rawClass"):
                        merged_det["rawClass"] = det_a.get("rawClass") or det_b.get("rawClass")

                    detections = [d for idx, d in enumerate(detections) if idx != i and idx != j] + [merged_det]
                    merged_any = True
                    break
                if merged_any:
                    break

        return detections

    @staticmethod
    def _cross_class_nms(
        detections: List[Dict[str, Any]],
        iou_threshold: float = 0.35,
        iomin_threshold: float = 0.60,
    ) -> List[Dict[str, Any]]:
        """
        Remove duplicate detections caused by YOLO-World matching the same
        physical object to multiple text-prompt classes or predicting sub-part boxes
        (e.g. cabin vs whole forklift).

        Algorithm:
        1. Sort descending by confidence.
        2. Check both IoU (Intersection-over-Union) AND IoMin (Intersection-over-Minimum-Area).
           IoMin catches nested boxes where a part of the vehicle is detected separately.
        3. Keep the detection with highest confidence for each physical object.
        """
        if len(detections) <= 1:
            return detections

        # Prefer a specific industrial prompt only when it is competitively
        # confident.  Generic prompts (truck/car) otherwise retain priority.
        # This resolves YOLO-World's overlapping "truck" + "forklift" boxes
        # without turning a low-confidence forklift guess into a forced label.
        class_specificity = {
            "reach stacker": 0.35,
            "container handler": 0.30,
            "forklift": 0.25,
            "truck": 0.12,
            "bus": 0.08,
            "car": 0.05,
            "container": 0.05,
            "shipping container": 0.05,
            "personnel carrier": -0.10,
            "utility vehicle": -0.10,
            "golf cart": -0.10,
        }

        def source_priority(detection: Dict[str, Any]) -> int:
            if detection.get("candidateVersion") or detection.get("source") == "custom":
                return 3
            if detection.get("source") == "primary":
                return 2
            if detection.get("source") == "aux":
                return 1
            return 0

        sorted_dets = sorted(
            detections,
            key=lambda d: (
                source_priority(d),
                d.get("confidence", 0.0) + class_specificity.get(str(d.get("class") or "").casefold(), 0.0),
            ),
            reverse=True,
        )
        keep: List[Dict[str, Any]] = []

        for candidate in sorted_dets:
            cx1, cy1, cx2, cy2 = candidate["bbox"]
            area_c = max(1, (cx2 - cx1) * (cy2 - cy1))
            suppressed = False

            for kept in keep:
                kx1, ky1, kx2, ky2 = kept["bbox"]
                area_k = max(1, (kx2 - kx1) * (ky2 - ky1))

                # Intersection
                ix1 = max(cx1, kx1)
                iy1 = max(cy1, ky1)
                ix2 = min(cx2, kx2)
                iy2 = min(cy2, ky2)
                inter_w = max(0, ix2 - ix1)
                inter_h = max(0, iy2 - iy1)
                inter_area = inter_w * inter_h
                if inter_area == 0:
                    continue

                # IoU and IoMin (containment)
                union = area_c + area_k - inter_area
                iou = inter_area / union if union > 0 else 0.0
                iomin = inter_area / min(area_c, area_k)

                both_vehicles = (
                    str(candidate.get("class") or "").casefold() in VEHICLE_CLASS_NAMES
                    and str(kept.get("class") or "").casefold() in VEHICLE_CLASS_NAMES
                )
                if (
                    iou > iou_threshold
                    or iomin > iomin_threshold
                    or (both_vehicles and (iou > 0.18 or iomin > 0.42))
                ):
                    suppressed = True
                    break

            if not suppressed:
                keep.append(candidate)

        return keep
