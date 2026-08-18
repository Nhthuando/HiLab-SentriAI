"""
SentriAI — Python AI Worker
Entry point: FastAPI server + OpenCV/YOLO video stream pipelines.
Port: 8001 (Architecture §6.1)
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Dict

import cv2
from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from db import check_db_health, close_db_pool, close_stale_open_violations, init_db_pool
from detection import AreaPipeline
from stream import CameraPipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("sentriai.worker")

# Global pipeline dictionary
pipelines: Dict[str, Any] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup ---
    logger.info("Initializing SentriAI Python AI Worker...")

    # 1. Initialize Database connection pool (Neon PostgreSQL)
    try:
        await init_db_pool()
        logger.info("Database pool initialized.")
        # Clean up any stale OPEN violations for BAI-KIEM from previous crash/restart
        stale_count = await close_stale_open_violations("BAI-KIEM")
        if stale_count > 0:
            logger.info("Cleaned up %d stale OPEN violation(s) on startup.", stale_count)
    except Exception as exc:
        logger.warning("Could not connect to Database on startup (%s). Will retry on demand.", exc)

    # 2. Initialize Camera Pipelines (GATE-01 and BAI-KIEM)
    gate_source = os.getenv("GATE_CAMERA_URL") or "./data/samples/gate_sample.mp4"
    area_source = os.getenv("AREA_CAMERA_URL") or "./data/samples/area_sample.mp4"

    gate_pipeline = CameraPipeline(
        camera_id="GATE-01",
        source=gate_source,
        target_fps=10.0,
        resolution=(640, 480),
    )
    area_pipeline = AreaPipeline(
        camera_id="BAI-KIEM",
        source=area_source,
        target_fps=10.0,
        resolution=(640, 480),
    )

    pipelines["GATE-01"] = gate_pipeline
    pipelines["BAI-KIEM"] = area_pipeline

    # Start stream loops in background
    gate_pipeline.start()
    area_pipeline.start()
    logger.info("Camera pipelines started (GATE-01: CameraPipeline, BAI-KIEM: AreaPipeline).")

    yield

    # --- Shutdown ---
    logger.info("Shutting down SentriAI Python Worker...")
    for cam_id, pipeline in pipelines.items():
        await pipeline.stop()
    pipelines.clear()

    await close_db_pool()
    logger.info("Python Worker shutdown complete.")


app = FastAPI(
    title="SentriAI Python Worker",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    db_ok = await check_db_health()
    stats = {cam_id: p.get_stats() for cam_id, p in pipelines.items()}
    return {
        "status": "ok",
        "service": "python-worker",
        "database": "connected" if db_ok else "disconnected",
        "cameras": stats,
    }


@app.websocket("/ws/hub")
async def ws_hub_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.info("Node.js WebSocket Hub client connected on /ws/hub")
    try:
        while True:
            # Keep connection open for heartbeat / status sync
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info("Node.js WebSocket Hub client disconnected from /ws/hub")
    except Exception as exc:
        logger.debug("Hub WebSocket connection ended: %s", exc)


@app.get("/cameras/{camera_id}/snapshot")
async def get_snapshot(camera_id: str):
    cid = camera_id.strip().upper()
    if cid in ["GATE", "GATE1", "GATE_01"]:
        cid = "GATE-01"
    elif cid in ["AREA", "BAIKIEM", "BAI_KIEM"]:
        cid = "BAI-KIEM"

    pipeline = pipelines.get(cid)
    if not pipeline:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")

    frame = pipeline.buffer.get_latest_frame()
    if frame is None:
        # Generate fresh single frame
        res = pipeline.process_single_frame()
        if res.get("success") and res.get("frame") is not None:
            frame = res["frame"]

    if frame is None:
        raise HTTPException(status_code=503, detail="No frame available from camera stream")

    ret, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ret:
        raise HTTPException(status_code=500, detail="Failed to encode snapshot image")

    return Response(content=buf.tobytes(), media_type="image/jpeg")


if __name__ == "__main__":
    port = int(os.getenv("PYTHON_WORKER_PORT", "8001"))
    logger.info("Starting SentriAI Python Worker on port %d", port)
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
