import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2
import torch
import easyocr
from detection.detector import YoloDetector
from detection.lpr import LicensePlateReader, validate_and_normalize_plate

def main():
    video_path = r"D:\video_test\Automatic Number Plate Recognition (ANPR) _ Vehicle Number Plate Recognition (1).mp4"
    cap = cv2.VideoCapture(video_path)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    print(f"Video: frames={total_frames}, FPS={fps}")

    detector = YoloDetector()
    lpr = LicensePlateReader()

    # Check frame at frame 30, 60, 100
    for frame_idx in [20, 50, 80, 120, 200]:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if not ret:
            break
        h, w = frame.shape[:2]
        dets = detector.detect(frame)
        print(f"\n--- Frame {frame_idx} ({w}x{h}) ---")
        for d in dets:
            print(f" YOLO: {d['class']} {d['bbox']} conf={d['confidence']}")
            if d['class'] in ['car', 'truck', 'bus']:
                vx1, vy1, vx2, vy2 = d['bbox']
                crop = frame[vy1:vy2, vx1:vx2]
                candidates = lpr.read_plate_from_vehicle(crop)
                print(f"   LPR candidates count: {len(candidates)}")

                for c in candidates:
                    print(f"      Candidate: {c}")

    cap.release()

if __name__ == "__main__":
    main()
