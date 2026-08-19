import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from detection.gate_pipeline import GatePipeline

video_path = r"D:\video_test\pexels-george-morina-5222550 (2160p).mp4"
pipeline = GatePipeline(camera_id="GATE-01", source=video_path)

print("Initializing GatePipeline & LPR weights...")
time.sleep(3)  # Wait for daemon thread to load YOLO & EasyOCR

print("\n--- Running 25 frames verification ---")
for i in range(25):
    t0 = time.time()
    res = pipeline.process_single_frame()
    dt = (time.time() - t0) * 1000
    dets = res.get("detections", [])
    if dets:
        print(f"Frame {i+1:02d} ({dt:.1f}ms): {len(dets)} plate(s)")
        for d in dets:
            print(f"   -> Bbox: {d['bbox']} | Plate: {repr(d['plate'])} | Status: {d['lpr_status']} | Conf: {d['confidence']}")
    else:
        print(f"Frame {i+1:02d} ({dt:.1f}ms): 0 plates")

pipeline.reader.release()
print("\nTest completed successfully!")

