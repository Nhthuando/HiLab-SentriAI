"""
detection.detector — Ultralytics YOLO Object Detection Pipeline

Loads the configured lightweight YOLO model, runs inference on video frames,
and maps COCO classes to domain Vietnamese labels.
"""
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from ultralytics import YOLO

logger = logging.getLogger("sentriai.detection")
DEFAULT_YOLO_MODEL = "yolo11n.pt"

# Area and Gate share this COCO-only display mapping. Non-COCO machinery is
# deliberately absent: it may be emitted only by an active custom model through
# the registry capability control plane.
COCO_VIETNAMESE_MAPPING: Dict[str, str] = {
    "person": "Người",
    "car": "Xe ô tô",
    "truck": "Xe tải",
    "motorcycle": "Xe máy",
    "bus": "Xe buýt",
    "bicycle": "Xe đạp",
}


class YoloDetector:
    TOP_VIEW_VEHICLE_ALIASES = {"parking meter", "toilet", "suitcase"}

    def __init__(
        self,
        model_path: Optional[str] = None,
        conf_threshold: float = 0.25,
        target_classes: Optional[List[str]] = None,
    ):
        configured_model = (
            model_path
            or os.environ.get("SENTRIAI_BASE_YOLO_MODEL")
            or os.environ.get("YOLO_MODEL_PATH")
            or DEFAULT_YOLO_MODEL
        )
        self.model_path = self._resolve_model_path(configured_model)
        self.conf_threshold = conf_threshold
        self.target_classes = target_classes or ["car", "truck", "motorcycle", "bus", "person", "bicycle"]
        self.enable_high_angle_aliases = False
        self.model: Optional[YOLO] = None
        self._load_model()

    @staticmethod
    def _resolve_model_path(model_path: str) -> str:
        """Resolve model path against models/ directory or environment."""
        # 1. Direct path check
        if os.path.isfile(model_path):
            return model_path

        # 2. Check python-worker/models/ directory
        models_dir = Path(__file__).resolve().parent.parent / "models"
        candidate = models_dir / model_path
        if candidate.is_file():
            return str(candidate)

        # 3. Check environment variable override
        env_path = os.environ.get("YOLO_MODEL_PATH")
        if env_path and os.path.isfile(env_path):
            return env_path

        # 4. Fallback: if models_dir exists and model_path is a filename, place in models_dir
        if models_dir.is_dir() and not os.path.dirname(model_path):
            return str(models_dir / model_path)

        return model_path

    def _load_model(self) -> None:
        """Load YOLO model and assign the best available device."""
        self.device, self.device_reason = self._select_device()

        try:
            logger.info("Loading YOLO model from %s on %s...", self.model_path, self.device)
            self.model = YOLO(self.model_path)
            self.model.to(self.device)
            logger.info("YOLO model loaded successfully on %s.", self.device)
        except Exception as exc:
            if self.device != "cpu":
                logger.warning("Failed to load YOLO on %s (%s). Falling back to CPU.", self.device, exc)
                self.device = "cpu"
                self.device_reason = "fallback_after_cuda_load_error"
                self.model = YOLO(self.model_path)
                self.model.to(self.device)
                logger.info("YOLO model loaded successfully on CPU fallback.")
                return
            logger.error("Failed to load YOLO model: %s", exc)
            raise

    @staticmethod
    def _select_device() -> Tuple[str, str]:
        requested = (os.getenv("YOLO_DEVICE") or os.getenv("SENTRIAI_AI_DEVICE") or "auto").strip().lower()
        try:
            import torch
            cuda_available = torch.cuda.is_available()
            cuda_count = torch.cuda.device_count() if cuda_available else 0
        except Exception as exc:
            logger.warning("Could not inspect torch CUDA availability: %s", exc)
            cuda_available = False
            cuda_count = 0

        if requested in {"cpu", "cuda", "0"}:
            if requested == "cpu":
                return "cpu", "forced_cpu"
            if cuda_available:
                return "cuda", f"forced_cuda:{cuda_count}_device(s)"
            logger.warning(
                "YOLO GPU was requested but torch cannot see CUDA. Install a CUDA-enabled torch build to use GPU."
            )
            return "cpu", "cuda_requested_but_unavailable"

        if cuda_available:
            return "cuda", f"auto_cuda:{cuda_count}_device(s)"
        return "cpu", "auto_cpu_torch_cuda_unavailable"

    def runtime_info(self) -> Dict[str, Any]:
        return {
            "model": os.path.basename(str(self.model_path)),
            "device": self.device,
            "deviceReason": self.device_reason,
        }

    def detect(
        self,
        frame: np.ndarray,
        conf: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """
        Run YOLO detection on a single BGR OpenCV frame.
        Returns a list of structured detection dictionaries.
        """
        if self.model is None or frame is None:
            return []

        threshold = conf if conf is not None else self.conf_threshold
        h, w = frame.shape[:2]

        try:
            # Run inference (verbose=False to avoid console spam)
            results = self.model(frame, conf=threshold, device=self.device, verbose=False)
            detections: List[Dict[str, Any]] = []

            for r in results:
                boxes = r.boxes
                if boxes is None:
                    continue

                for i in range(len(boxes)):
                    xyxy = boxes.xyxy[i].cpu().numpy().tolist()
                    cls_id = int(boxes.cls[i].item())
                    confidence = float(boxes.conf[i].item())
                    class_name = self.model.names.get(cls_id, f"class_{cls_id}")

                    is_high_angle_alias = (
                        self.enable_high_angle_aliases
                        and class_name in self.TOP_VIEW_VEHICLE_ALIASES
                        and self._is_high_angle_vehicle_alias(xyxy, w, h)
                    )

                    # Filter target classes if specified
                    if self.target_classes and class_name not in self.target_classes and not is_high_angle_alias:
                        continue

                    source_class = class_name
                    if is_high_angle_alias:
                        class_name = "truck"

                    vietnamese_label = COCO_VIETNAMESE_MAPPING.get(class_name, class_name)

                    # Bbox coordinates as [x1, y1, x2, y2]
                    x1, y1, x2, y2 = [int(coord) for coord in xyxy]
                    x1 = max(0, min(w - 1, x1))
                    y1 = max(0, min(h - 1, y1))
                    x2 = max(x1 + 1, min(w, x2))
                    y2 = max(y1 + 1, min(h, y2))

                    detections.append({
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
                        "_top_view_alias": is_high_angle_alias,
                        "_source_class": source_class,
                    })

            return detections
        except Exception as exc:
            logger.error("Error during YOLO inference: %s", exc)
            return []

    @staticmethod
    def _is_high_angle_vehicle_alias(box: List[float], frame_w: int, frame_h: int) -> bool:
        """Reject ordinary small COCO objects while recovering large top-view vehicles."""
        if len(box) != 4 or frame_w <= 0 or frame_h <= 0:
            return False
        x1, y1, x2, y2 = [float(value) for value in box]
        width = max(1.0, x2 - x1)
        height = max(1.0, y2 - y1)
        area_ratio = (width * height) / float(frame_w * frame_h)
        return height >= width * 1.15 and y2 >= frame_h * 0.80 and area_ratio >= 0.045

    @staticmethod
    def crop_bbox(frame: np.ndarray, bbox: List[int]) -> Optional[np.ndarray]:
        """Crop region of interest from frame."""
        if frame is None or len(bbox) < 4:
            return None
        x1, y1, x2, y2 = bbox
        h, w = frame.shape[:2]
        x1 = max(0, min(w - 1, x1))
        y1 = max(0, min(h - 1, y1))
        x2 = max(x1 + 1, min(w, x2))
        y2 = max(y1 + 1, min(h, y2))
        return frame[y1:y2, x1:x2].copy()
