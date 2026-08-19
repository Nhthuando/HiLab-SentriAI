"""
detection.tracked_detector — Configurable YOLO/YOLO-World ByteTrack Detector

Uses either the original YOLO detector or YOLO-World with multi-object tracking
(ByteTrack) to provide persistent trackId across video frames for BAI-KIEM.
"""
import logging
import os
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from detection.detector import COCO_VIETNAMESE_MAPPING, YoloDetector
from ultralytics import YOLO, YOLOWorld

logger = logging.getLogger("sentriai.detection.tracked")


class TrackedYoloDetector(YoloDetector):
    """
    YOLOv8 Object Detector with ByteTrack tracking for persistent object identities.
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
        self.detector_kind = os.getenv("AREA_DETECTOR_KIND", "yolov8").strip().casefold()
        configured_model = model_path or os.getenv("AREA_DETECTOR_MODEL")
        configured_classes = os.getenv("AREA_DETECTOR_CLASSES", "")
        env_classes = tuple(
            item.strip()
            for item in configured_classes.split(",")
            if item.strip()
        )
        default_classes = (
            ("person", "forklift", "truck", "car", "motorcycle")
            if self.detector_kind == "world"
            else ("person", "truck")
        )
        self.area_target_classes = tuple(target_classes or env_classes or default_classes)

        env_conf = os.getenv("AREA_CONF_THRESHOLD")
        if env_conf:
            try:
                self.conf_threshold = float(env_conf)
            except ValueError:
                self.conf_threshold = conf_threshold or 0.25
        else:
            self.conf_threshold = conf_threshold if conf_threshold is not None else 0.25

        import torch
        self.device = 0 if torch.cuda.is_available() else "cpu"
        device_str = "cuda:0" if self.device == 0 else "cpu"

        if self.detector_kind == "hybrid":
            self.model_path = self._resolve_model_path(configured_model or "yolov8s-world.pt")
            logger.info(
                "Loading HYBRID Ensemble (YOLO-World + YOLOv8) on %s with prompts: %s",
                device_str,
                self.area_target_classes,
            )
            self.model = YOLOWorld(self.model_path)
            if self.device == 0:
                self.model.to(device_str)
            self.model.set_classes(list(self.area_target_classes))

            # Auxiliary COCO YOLOv8 detector for high robustness on challenging angles / occlusions
            coco_path = self._resolve_model_path("yolov8n.pt")
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
                model_path=configured_model or "yolov8n.pt",
                conf_threshold=self.conf_threshold,
                target_classes=list(self.area_target_classes),
            )
        self.tracker = tracker

    def track(
        self,
        frame: np.ndarray,
        conf: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """
        Run YOLO detection and ByteTrack tracking on a single BGR OpenCV frame.
        Returns structured detection dictionaries with persistent trackId.
        Supports single model (world / yolov8) and hybrid ensemble.
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
            # 1. Primary Model Inference (YOLO-World or YOLOv8)
            results = self.model.track(
                frame,
                conf=threshold,
                classes=class_ids if class_ids else None,
                persist=True,
                tracker=self.tracker,
                device=self.device,
                verbose=False,
            )
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
                    class_name = self.model.names.get(cls_id, f"class_{cls_id}")
                    if self.area_target_classes and class_name not in self.area_target_classes:
                        continue

                    track_id = int(track_ids[i]) if (track_ids is not None and i < len(track_ids)) else None
                    vietnamese_label = COCO_VIETNAMESE_MAPPING.get(class_name, class_name)

                    x1, y1, x2, y2 = [int(coord) for coord in xyxy]
                    x1 = max(0, min(w - 1, x1))
                    y1 = max(0, min(h - 1, y1))
                    x2 = max(x1 + 1, min(w, x2))
                    y2 = max(y1 + 1, min(h, y2))

                    detections.append({
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
                    })

            # 2. Auxiliary Model Inference in Hybrid Mode (YOLOv8 fallback)
            if self.detector_kind == "hybrid" and self.aux_model is not None:
                coco_target_ids = [
                    int(cid)
                    for cid, cname in self.aux_model.names.items()
                    if cname in ["person", "car", "truck", "bus", "motorcycle"]
                ]
                aux_results = self.aux_model.track(
                    frame,
                    conf=max(0.20, threshold),
                    classes=coco_target_ids,
                    persist=True,
                    tracker=self.tracker,
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
                        class_name = self.aux_model.names.get(cls_id, f"class_{cls_id}")
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

                        detections.append({
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
                        })

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

            return detections
        except Exception as exc:
            logger.error("Error during YOLO tracking inference: %s", exc)
            return []

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

        # Sort by source priority (primary/world > aux/coco) and then confidence
        sorted_dets = sorted(
            detections,
            key=lambda d: (1 if d.get("source") == "primary" else 0, d.get("confidence", 0.0)),
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

                if iou > iou_threshold or iomin > iomin_threshold:
                    suppressed = True
                    break

            if not suppressed:
                keep.append(candidate)

        return keep
