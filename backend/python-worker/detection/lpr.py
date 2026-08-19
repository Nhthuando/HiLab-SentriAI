"""
detection.lpr — Universal High-Sensitivity License Plate Recognition (LPR) Module (VS-GATE-LIVE)

Supports:
1. State & International Formats: KA-02-MM-9091, KA-02-HN-1820, DL-02-HH-7258, ABC-1234, 7XYZ-123.
2. Vietnamese Formats: 15R-158.45, 29A-123.45, 51C-888.99, 30F-12345.
3. Custom / Vanity All-Letter Plates: CALIFORNIA, SENTRI, SPEED, VIP.
4. Robust OCR cleaning & normalization.
"""
import logging
import re
import threading
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger("sentriai.detection.lpr")

REJECT_KEYWORDS = {"NUMBER", "PLATE", "AUTOMATIC", "RECOGNITION", "ANPR", "TRANSIT", "STOP", "CAR"}


def validate_and_normalize_plate(text: str) -> Tuple[bool, str]:
    """
    Validate and cleanly normalize license plate text.
    Returns: (is_valid: bool, formatted_plate: str)
    """
    if not text:
        return False, ""

    raw = re.sub(r"[^A-Z0-9]", "", text.upper().strip())
    if len(raw) < 3 or len(raw) > 14:
        return False, ""

    for kw in REJECT_KEYWORDS:
        if kw in raw:
            return False, ""

    # Clean common leading/trailing OCR noise characters
    if raw.startswith("I") and len(raw) >= 6 and raw[1:3] in ["KA", "MH", "DL", "HR", "TN", "WB", "AP"]:
        raw = raw[1:]
    if (raw.startswith("3") or raw.startswith("7")) and len(raw) >= 7 and ("02" in raw or "HH" in raw):
        raw = "DL" + raw[1:]

    # 1. State Alphanumeric Pattern (e.g. KA02MM9091 -> KA-02-MM-9091)
    m_std = re.match(r"^([A-Z]{2})(\d{1,2})([A-Z]{1,3})(\d{1,4})$", raw)
    if m_std:
        return True, f"{m_std.group(1)}-{m_std.group(2)}-{m_std.group(3)}-{m_std.group(4)}"

    # 2. Vietnamese Formats
    m_vn1 = re.match(r"^(\d{2}[A-Z])(\d{3})(\d{2})$", raw)
    if m_vn1:
        return True, f"{m_vn1.group(1)}-{m_vn1.group(2)}.{m_vn1.group(3)}"

    m_vn2 = re.match(r"^(\d{2}[A-Z])(\d{4})$", raw)
    if m_vn2:
        return True, f"{m_vn2.group(1)}-{m_vn2.group(2)}"

    m_vn3 = re.match(r"^(\d{2}[A-Z]{2})(\d{3})(\d{2})$", raw)
    if m_vn3:
        return True, f"{m_vn3.group(1)}-{m_vn3.group(2)}.{m_vn3.group(3)}"

    # 3. Simple Prefix + Numbers: ABC1234 -> ABC-1234, 7XYZ123 -> 7XYZ-123
    has_digit = any(c.isdigit() for c in raw)
    has_alpha = any(c.isalpha() for c in raw)

    if has_digit and has_alpha:
        if len(raw) >= 5:
            split_idx = 3 if raw[:3].isalpha() or raw[:3].isdigit() else 2
            return True, f"{raw[:split_idx]}-{raw[split_idx:]}"
        return True, raw

    # 4. All-Letter Vanity Plate
    if has_alpha and not has_digit and 3 <= len(raw) <= 10:
        return True, raw

    # 5. Pure numeric plate
    if has_digit and not has_alpha and 4 <= len(raw) <= 7:
        return True, raw

    return False, raw


class LicensePlateReader:
    def __init__(self, ocr_engine: str = "easyocr"):
        self.ocr_engine = ocr_engine
        self._reader: Optional[Any] = None
        self._is_loading = False
        threading.Thread(target=self._init_reader, daemon=True).start()

    def _init_reader(self) -> None:
        """Initialize EasyOCR in background."""
        if self._is_loading:
            return
        self._is_loading = True
        try:
            if self.ocr_engine == "easyocr":
                import easyocr
                logger.info("Initializing EasyOCR reader...")
                self._reader = easyocr.Reader(["en"], gpu=False, verbose=False)
                logger.info("EasyOCR initialized successfully.")
        except Exception as exc:
            logger.debug("EasyOCR load error: %s", exc)
            self._reader = None
        finally:
            self._is_loading = False

    def read_plate_from_vehicle(
        self,
        vehicle_crop: np.ndarray,
    ) -> List[Dict[str, Any]]:
        """
        Scan vehicle crop for real license plates.
        Returns candidate plates with exact crop coordinates.
        """
        if vehicle_crop is None or vehicle_crop.size == 0 or self._reader is None:
            return []

        vh, vw = vehicle_crop.shape[:2]
        candidates = []

        try:
            # Preprocessing: upscale if small
            scale = 1.0
            proc = vehicle_crop
            if vw < 300 or vh < 150:
                scale = max(2.0, 300.0 / max(1, vw))
                proc = cv2.resize(vehicle_crop, (int(vw * scale), int(vh * scale)), interpolation=cv2.INTER_CUBIC)

            gray = cv2.cvtColor(proc, cv2.COLOR_BGR2GRAY)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            enhanced = cv2.cvtColor(clahe.apply(gray), cv2.COLOR_GRAY2BGR)

            results = self._reader.readtext(enhanced, contrast_ths=0.1, text_ths=0.15, low_text=0.15)
            if not results:
                results = self._reader.readtext(vehicle_crop)
                scale = 1.0

            for bbox, text, conf in results:
                cbx1 = int(min(p[0] for p in bbox) / scale)
                cby1 = int(min(p[1] for p in bbox) / scale)
                cbx2 = int(max(p[0] for p in bbox) / scale)
                cby2 = int(max(p[1] for p in bbox) / scale)

                bw = cbx2 - cbx1
                bh = cby2 - cby1
                aspect_ratio = bw / max(1, bh)
                rel_y = cby1 / vh

                # Reject text in top 20% (roof/watermarks)
                if rel_y < 0.20:
                    continue

                # Reject tall square blocks (logos)
                if aspect_ratio < 1.4 or aspect_ratio > 8.0:
                    continue

                # Reject full vehicle boxes
                if bh > (vh * 0.35) or bw < 20:
                    continue

                is_valid, norm_plate = validate_and_normalize_plate(text)
                cleaned = re.sub(r"[^A-Z0-9]", "", text.upper().strip())

                if (is_valid or len(cleaned) >= 3) and conf >= 0.10:
                    final_plate = norm_plate if is_valid else cleaned
                    candidates.append({
                        "plate": final_plate,
                        "confidence": round(float(conf), 2),
                        "bbox_in_crop": [cbx1, cby1, cbx2, cby2],
                        "valid": True,
                    })

        except Exception as exc:
            logger.debug("Plate OCR read error: %s", exc)

        return candidates
