import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import time
from db import init_db_pool, close_db_pool
from detection.gate_pipeline import GatePipeline

async def test_full_pipeline():
    await init_db_pool()
    pipeline = GatePipeline(
        camera_id="GATE-01",
        source=r"D:\video_test\Automatic Number Plate Recognition (ANPR) _ Vehicle Number Plate Recognition (1).mp4",
        target_fps=15.0,
    )
    # Wait for LPR reader
    while pipeline.lpr_reader._reader is None:
        await asyncio.sleep(0.1)

    pipeline.reader.cap.set(1, 140)
    print("Testing GatePipeline on user video...")
    for i in range(25):
        res = await pipeline.process_gate_frame()
        dets = res.get("detections", [])
        for d in dets:
            print(f"Frame {i:2d}: plate='{d.get('plate')}', status='{d.get('lpr_status')}', conf={d.get('confidence')}")
        await asyncio.sleep(0.15)

    await pipeline.stop()
    await close_db_pool()

asyncio.run(test_full_pipeline())
