"""
SentriAI Python Worker — Object Detection Module (detection)
"""
from detection.area_pipeline import AreaPipeline
from detection.detector import COCO_VIETNAMESE_MAPPING, YoloDetector
from detection.tracked_detector import TrackedYoloDetector

__all__ = [
    "YoloDetector",
    "TrackedYoloDetector",
    "AreaPipeline",
    "COCO_VIETNAMESE_MAPPING",
]
