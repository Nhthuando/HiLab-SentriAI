import cv2
import time
from fast_alpr import ALPR

print("Initializing fast-alpr on GPU/ONNX...")
t0 = time.time()
alpr = ALPR(
    detector_model="yolo-v9-t-384-license-plate-end2end",
    ocr_model="global-plates-mobile-vit-v2-model",
)
print(f"ALPR initialized in {time.time()-t0:.2f}s")

video_path = r"D:\video_test\pexels-george-morina-5222550 (2160p).mp4"
cap = cv2.VideoCapture(video_path)

frames_to_test = [50, 100, 150, 180, 210, 240, 270, 300, 330, 360, 390, 420]

for f_idx in frames_to_test:
    cap.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
    ret, frame = cap.read()
    if not ret:
        break
    h, w = frame.shape[:2]
    resized = cv2.resize(frame, (1280, 720))
    t_start = time.time()
    results = alpr.predict(resized)
    t_cost = (time.time() - t_start) * 1000.0

    print(f"\nFrame {f_idx:03d} ({t_cost:.1f}ms): {len(results)} plate(s) found:")
    for p in results:
        txt = p.ocr.text if p.ocr else "NO_OCR"
        conf = sum(p.ocr.confidence) / max(1, len(p.ocr.confidence)) if (p.ocr and p.ocr.confidence) else 0.0
        bb = p.detection.bounding_box
        print(f"   -> Plate: '{txt}' | Conf: {conf:.2f} | Bbox: [{bb.x1}, {bb.y1}, {bb.x2}, {bb.y2}]")

cap.release()
print("\nTest completed!")
