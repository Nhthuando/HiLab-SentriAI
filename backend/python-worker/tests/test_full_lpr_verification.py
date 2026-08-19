import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from detection.gate_pipeline import GatePipeline

def run_benchmark():
    print("=== INITIALIZING GATE PIPELINE (FAST-ALPR CCT TRANSFORMER) ===")
    pipeline = GatePipeline(camera_id="GATE-01")
    time.sleep(1.0)
    print("Pipeline ready. Running 30 benchmark frames...\n")

    results_summary = []
    total_time = 0.0

    for i in range(1, 31):
        t0 = time.time()
        res = pipeline.process_single_frame()
        dur = (time.time() - t0) * 1000.0
        total_time += dur

        dets = res.get("detections", [])
        plates_info = [f"'{d['plate']}' ({d['lpr_status']}, {int(d['confidence']*100)}%)" for d in dets]
        plates_str = ", ".join(plates_info) if plates_info else "No plates"

        print(f"Frame {i:02d} ({dur:5.1f}ms): {len(dets)} plate(s) -> {plates_str}")
        if dets:
            results_summary.extend([d['plate'] for d in dets])

    avg_fps = 30.0 / (total_time / 1000.0)
    print("\n=== BENCHMARK COMPLETED ===")
    print(f"Average latency per frame: {total_time/30.0:.1f}ms (~{avg_fps:.1f} FPS)")
    print(f"Unique plates detected: {set(results_summary)}")

if __name__ == "__main__":
    run_benchmark()
