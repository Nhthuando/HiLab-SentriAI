import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2
import torch
import easyocr
import json
from detection.detector import YoloDetector
from detection.lpr import LicensePlateReader, validate_and_normalize_plate

cap = cv2.VideoCapture(r"D:\video_test\0_te10.mp4")
total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
print(f"Total frames: {total_frames}, FPS: {cap.get(cv2.CAP_PROP_FPS)}")

# Check frame at 1.0s
cap.set(cv2.CAP_PROP_POS_FRAMES, min(25, total_frames - 1))
ret, frame = cap.read()
if not ret:
    print("Cannot read frame")
    exit(1)

print("Frame shape:", frame.shape)
detector = YoloDetector()
dets = detector.detect(frame)
print(f"YOLO detections ({len(dets)}):")
for d in dets:
    print(" ", d["class"], d["bbox"], "conf:", d["confidence"])

reader = easyocr.Reader(["en"], gpu=torch.cuda.is_available(), verbose=False)
full_results = reader.readtext(frame)
print("EasyOCR on full frame:")
for r in full_results:
    is_valid, norm = validate_and_normalize_plate(r[1])
    print(f"  Text: '{r[1]}' (conf: {r[2]:.2f}) -> is_valid: {is_valid}, norm: '{norm}'")

for idx, d in enumerate(dets):
    if d["class"] in ["car", "truck", "bus", "motorcycle"]:
        x1, y1, x2, y2 = d["bbox"]
        crop = frame[y1:y2, x1:x2]
        c_results = reader.readtext(crop)
        print(f"\nCrop {idx} ({d['class']} at {d['bbox']}):")
        for r in c_results:
            is_valid, norm = validate_and_normalize_plate(r[1])
            print(f"   Crop text: '{r[1]}' (conf: {r[2]:.2f}) -> is_valid: {is_valid}, norm: '{norm}'")
