import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2
import re
import torch
import easyocr
from detection.detector import YoloDetector

def clean_and_normalize_plate_text(raw_text: str) -> tuple[bool, str]:
    if not raw_text:
        return False, ""
    # Clean whitespace and non-alphanumeric
    cleaned = re.sub(r"[^A-Za-z0-9]", "", raw_text).upper()
    if len(cleaned) < 4:
        return False, ""
    
    # Reject common non-plate words
    for bad in ["CAMERA", "NUMBER", "PLATE", "SAFEPRO", "AUTOMATIC", "RECOGNITION", "TRANSIT", "SYSTEM"]:
        if bad in cleaned:
            return False, ""

    # Common OCR misreads for State codes (e.g. XA02MN1826 / IXA02 / 4A02 -> KA02)
    if (cleaned.startswith("XA") or cleaned.startswith("4A") or cleaned.startswith("IXA") or cleaned.startswith("1XA")):
        cleaned = "KA" + re.sub(r"^(IXA|1XA|XA|4A)", "", cleaned)
    if cleaned.startswith("02") and len(cleaned) >= 8:
        cleaned = "KA" + cleaned

    # Format 1: State / Universal Plate e.g. KA02MN1826 -> KA-02-MN-1826, DL02HH7258 -> DL-02-HH-7258
    m_std = re.match(r"^([A-Z]{2})0?([1-9]|0[1-9]|[1-9][0-9])([A-Z]{1,3})(\d{3,4})$", cleaned)
    if m_std:
        s_code, dist, series, num = m_std.groups()
        return True, f"{s_code}-{int(dist):02d}-{series}-{num}"

    # Format 2: Vietnamese plate e.g. 15R15845 -> 15R-158.45, 29A12345 -> 29A-123.45, 51C88899 -> 51C-888.99
    m_vn = re.match(r"^(\d{2}[A-Z]{1,2})(\d{3})(\d{2})$", cleaned)
    if m_vn:
        return True, f"{m_vn.group(1)}-{m_vn.group(2)}.{m_vn.group(3)}"
    m_vn4 = re.match(r"^(\d{2}[A-Z]{1,2})(\d{4})$", cleaned)
    if m_vn4:
        return True, f"{m_vn4.group(1)}-{m_vn4.group(2)}"

    # Format 3: Alphanumeric prefix + number e.g. ABC1234 -> ABC-1234, 7XYZ123 -> 7XYZ-123
    m_gen = re.match(r"^([A-Z0-9]{3,4})(\d{3,4})$", cleaned)
    if m_gen:
        return True, f"{m_gen.group(1)}-{m_gen.group(2)}"

    if 4 <= len(cleaned) <= 10:
        return True, cleaned

    return False, cleaned

video_path = r"D:\video_test\Automatic Number Plate Recognition (ANPR) _ Vehicle Number Plate Recognition (1).mp4"
cap = cv2.VideoCapture(video_path)
reader = easyocr.Reader(["en"], gpu=torch.cuda.is_available(), verbose=False)
detector = YoloDetector()

print("Testing enhanced plate scanner on video...")
for f_idx in [30, 80, 150, 220, 300, 400, 500]:
    cap.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
    ret, frame = cap.read()
    if not ret:
        break
    h, w = frame.shape[:2]
    dets = detector.detect(frame)
    cars = [d for d in dets if d["class"] in ["car", "truck", "bus"] and d["confidence"] > 0.4]
    
    # 1. Check ANPR overlay / frame OCR
    frame_ocr = reader.readtext(frame[0:200, 0:400])
    found_plate = None
    for r in frame_ocr:
        is_v, n_p = clean_and_normalize_plate_text(r[1])
        if is_v and len(n_p) >= 6:
            found_plate = n_p
            break

    # 2. Check Car bumper OCR
    if not found_plate:
        for car in cars:
            cx1, cy1, cx2, cy2 = car["bbox"]
            cw, ch = cx2 - cx1, cy2 - cy1
            bumper = frame[cy1 + int(ch * 0.5): cy2, cx1 + int(cw * 0.15): cx1 + int(cw * 0.85)]
            if bumper.size > 0:
                scaled = cv2.resize(bumper, (bumper.shape[1] * 2, bumper.shape[0] * 2), interpolation=cv2.INTER_CUBIC)
                gray = cv2.cvtColor(scaled, cv2.COLOR_BGR2GRAY)
                b_ocr = reader.readtext(gray)
                for r in b_ocr:
                    is_v, n_p = clean_and_normalize_plate_text(r[1])
                    if is_v and len(n_p) >= 6:
                        found_plate = n_p
                        break

    print(f"Frame {f_idx:3d} (Cars: {len(cars)}): Recognized Plate -> {found_plate}")

cap.release()
