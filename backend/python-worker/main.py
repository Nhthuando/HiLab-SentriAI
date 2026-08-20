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
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from db import check_db_health, close_db_pool, close_stale_open_violations, init_db_pool
from detection import AreaPipeline, GatePipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("sentriai.worker")

# Global pipeline dictionary
pipelines: Dict[str, Any] = {}


class SeekRequest(BaseModel):
    positionMs: int


class CameraConfigUpdate(BaseModel):
    minConfidence: float


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

    # 2. Initialize Camera Pipelines (GATE-01 with LPR and BAI-KIEM with Area Violation)
    gate_source = os.getenv("GATE_CAMERA_URL") or os.getenv("VIDEO_GATE_PATH") or "./data/samples/gate_sample.mp4"
    area_source = os.getenv("AREA_CAMERA_URL") or os.getenv("VIDEO_AREA_PATH") or "./data/samples/area_sample.mp4"

    gate_pipeline = GatePipeline(
        camera_id="GATE-01",
        source=gate_source,
        target_fps=15.0,
        resolution=(1600, 900),
    )
    area_pipeline = AreaPipeline(
        camera_id="BAI-KIEM",
        source=area_source,
        target_fps=15.0,
        resolution=(854, 480),
    )

    pipelines["GATE-01"] = gate_pipeline
    pipelines["BAI-KIEM"] = area_pipeline

    # Start stream loops in background
    gate_pipeline.start()
    area_pipeline.start()
    logger.info("Camera pipelines started (GATE-01: GatePipeline, BAI-KIEM: AreaPipeline).")

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
    stats = {}
    for cam_id, p in pipelines.items():
        detector = getattr(p, "detector", None)
        lpr_reader = getattr(p, "lpr_reader", None)
        stats[cam_id] = {
            "fps": getattr(p, "fps_measured", 0.0) or getattr(p, "target_fps", 15.0),
            "frame_count": getattr(p, "frame_count", 0),
            "connected": getattr(getattr(p, "reader", None), "is_connected", True),
            "resolution": list(getattr(p, "resolution", (0, 0))),
            "detector": detector.runtime_info() if hasattr(detector, "runtime_info") else None,
            "lpr": lpr_reader.runtime_info() if hasattr(lpr_reader, "runtime_info") else None,
        }
    return {
        "status": "ok",
        "service": "python-worker",
        "database": "connected" if db_ok else "disconnected",
        "cameras": stats,
    }


@app.websocket("/ws/hub")
async def websocket_hub(websocket: WebSocket):
    """
    WebSocket endpoint for Node.js API PythonConnector.
    Maintains persistent duplex connection and handles ping/heartbeats.
    """
    await websocket.accept()
    logger.info("Accepted inbound WebSocket connection from Node.js API (/ws/hub).")
    try:
        while True:
            msg = await websocket.receive_text()
            # Respond to ping or heartbeat
            if msg == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        logger.info("Node.js API client disconnected from /ws/hub.")
    except Exception as exc:
        logger.debug("WebSocket hub closed: %s", exc)


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


@app.get("/cameras/{camera_id}/playback")
async def get_playback(camera_id: str):
    cid = camera_id.strip().upper()
    if cid in ["GATE", "GATE1", "GATE_01"]:
        cid = "GATE-01"
    elif cid in ["AREA", "BAIKIEM", "BAI_KIEM"]:
        cid = "BAI-KIEM"

    pipeline = pipelines.get(cid)
    if not pipeline:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")
    return pipeline.reader.get_playback_status()


@app.post("/cameras/{camera_id}/seek")
async def seek_camera(camera_id: str, body: SeekRequest):
    cid = camera_id.strip().upper()
    if cid in ["GATE", "GATE1", "GATE_01"]:
        cid = "GATE-01"
    elif cid in ["AREA", "BAIKIEM", "BAI_KIEM"]:
        cid = "BAI-KIEM"

    pipeline = pipelines.get(cid)
    if not pipeline:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")
    if hasattr(pipeline, "reset_tracking_state"):
        pipeline.reset_tracking_state()
    else:
        pipeline.tracker.tracks.clear()
    return pipeline.reader.seek_ms(body.positionMs)


@app.get("/cameras/{camera_id}/config")
async def get_camera_config(camera_id: str):
    cid = camera_id.strip().upper()
    if cid in ["GATE", "GATE1", "GATE_01"]:
        cid = "GATE-01"
    elif cid in ["AREA", "BAIKIEM", "BAI_KIEM"]:
        cid = "BAI-KIEM"

    pipeline = pipelines.get(cid)
    if not pipeline:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")
    if not hasattr(pipeline, "min_confidence"):
        raise HTTPException(status_code=400, detail="Confidence configuration is only supported for gate cameras")
    return {
        "cameraId": cid,
        "minConfidence": getattr(pipeline, "min_confidence", 0.70),
    }


@app.post("/cameras/{camera_id}/config")
async def update_camera_config(camera_id: str, body: CameraConfigUpdate):
    cid = camera_id.strip().upper()
    if cid in ["GATE", "GATE1", "GATE_01"]:
        cid = "GATE-01"
    elif cid in ["AREA", "BAIKIEM", "BAI_KIEM"]:
        cid = "BAI-KIEM"

    pipeline = pipelines.get(cid)
    if not pipeline:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")
    if not hasattr(pipeline, "update_min_confidence"):
        raise HTTPException(status_code=400, detail="Confidence configuration is only supported for gate cameras")

    if not 0.50 <= body.minConfidence <= 0.95:
        raise HTTPException(status_code=422, detail="minConfidence must be between 0.50 and 0.95")
    try:
        val = pipeline.update_min_confidence(body.minConfidence)
    except OSError as exc:
        logger.error("[%s] Failed to persist camera configuration: %s", cid, exc)
        raise HTTPException(status_code=500, detail="Could not persist camera configuration") from exc
    logger.info("[%s] Updated min_confidence threshold to %.2f (%.0f%%)", cid, val, val * 100)

    return {
        "cameraId": cid,
        "minConfidence": getattr(pipeline, "min_confidence", 0.70),
    }


if __name__ == "__main__":
    port = int(os.getenv("PYTHON_WORKER_PORT", "8001"))
    logger.info("Starting SentriAI Python Worker on port %d", port)
    try:
        uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
    except KeyboardInterrupt:
        logger.info("Received KeyboardInterrupt (Ctrl+C). Terminating cleanly...")
    finally:
        os._exit(0)
