"""
detection.tracked_detector — ByteTrack-enabled YOLO Object Tracking

Extends YoloDetector with multi-object tracking (ByteTrack) to provide
persistent trackId across video frames for camera BAI-KIEM.
"""
import logging
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from detection.detector import COCO_VIETNAMESE_MAPPING, YoloDetector

logger = logging.getLogger("sentriai.detection.tracked")


class TrackedYoloDetector(YoloDetector):
    """
    YOLO11 Object Detector with ByteTrack tracking for persistent object identities.
    Area monitoring is restricted to person and truck detections. The truck class is
    mapped to the business label Container by the active object-label snapshot.
    """

    def __init__(
        self,
        model_path: str = "yolo11n.pt",
        conf_threshold: float = 0.45,
        tracker: str = "bytetrack.yaml",
        target_classes: Optional[Sequence[str]] = None,
    ):
        # Area monitoring only needs people and trucks (displayed as Container by DB mapping).
        self.area_target_classes = tuple(target_classes or ("person", "truck"))
        super().__init__(
            model_path=model_path,
            conf_threshold=conf_threshold,
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
        if not class_ids:
            logger.error("Area target classes are unavailable in the loaded YOLO model: %s", self.area_target_classes)
            return []

        try:
            # Restrict inference itself so unrelated COCO false positives never reach rules.
            results = self.model.track(
                frame,
                conf=threshold,
                classes=class_ids,
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

                # Check if IDs are available from tracker
                track_ids = None
                if boxes.id is not None:
                    track_ids = boxes.id.int().cpu().numpy().tolist()

                for i in range(len(boxes)):
                    xyxy = boxes.xyxy[i].cpu().numpy().tolist()
                    cls_id = int(boxes.cls[i].item())
                    confidence = float(boxes.conf[i].item())
                    class_name = self.model.names.get(cls_id, f"class_{cls_id}")
                    if class_name not in self.area_target_classes:
                        continue

                    track_id = int(track_ids[i]) if (track_ids is not None and i < len(track_ids)) else None
                    vietnamese_label = COCO_VIETNAMESE_MAPPING.get(class_name, class_name)

                    # Bbox coordinates as [x1, y1, x2, y2]
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
                    })

            return detections
        except Exception as exc:
            logger.error("Error during YOLO tracking inference: %s", exc)
            return []
