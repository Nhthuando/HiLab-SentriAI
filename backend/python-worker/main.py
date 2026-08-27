"""
SentriAI — Python AI Worker
Entry point: FastAPI server + OpenCV/YOLO video stream pipelines.
Port: 8001 (Architecture §6.1)
"""
import asyncio
import logging
import math
import os
import uuid
from contextlib import asynccontextmanager
from typing import Any, Dict

import cv2
from fastapi import Body, FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

import dotenv

# Load environment configuration
for env_path in ["backend/.env", ".env", "../.env", "../../backend/.env"]:
    if os.path.exists(env_path):
        dotenv.load_dotenv(env_path)
        break
else:
    dotenv.load_dotenv()

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

    gate_target_fps = float(os.getenv("GATE_TARGET_FPS", "15.0"))
    area_target_fps = float(os.getenv("AREA_TARGET_FPS", "25.0"))

    gate_pipeline = GatePipeline(
        camera_id="GATE-01",
        source=gate_source,
        target_fps=gate_target_fps,
        resolution=(1600, 900),
    )
    area_pipeline = AreaPipeline(
        camera_id="BAI-KIEM",
        source=area_source,
        target_fps=area_target_fps,
        resolution=(1280, 720),
    )

    await area_pipeline.prepare()

    pipelines["GATE-01"] = gate_pipeline
    pipelines["BAI-KIEM"] = area_pipeline

    logger.info("Camera pipelines initialized and paused until a feed subscriber connects.")

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
            "active": bool(getattr(p, "_active", False)),
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


@app.post("/cameras/{camera_id}/activation")
async def set_camera_activation(camera_id: str, payload: Dict[str, bool] = Body(default={})):
    """Start or pause inference for a camera based on live-feed subscriber demand."""
    cid = camera_id.strip().upper()
    if cid in ["GATE", "GATE1", "GATE_01"]:
        cid = "GATE-01"
    elif cid in ["AREA", "BAIKIEM", "BAI_KIEM"]:
        cid = "BAI-KIEM"

    pipeline = pipelines.get(cid)
    if not pipeline:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")

    is_active = bool(payload.get("active", True))
    if is_active:
        pipeline.start()
    else:
        pipeline.pause()

    return {"cameraId": cid, "active": is_active}


@app.get("/cameras/{camera_id}/playback")
async def get_camera_playback(camera_id: str):
    cid = camera_id.strip().upper()
    if cid in ["GATE", "GATE1", "GATE_01"]:
        cid = "GATE-01"
    elif cid in ["AREA", "BAIKIEM", "BAI_KIEM"]:
        cid = "BAI-KIEM"
    pipeline = pipelines.get(cid)
    if not pipeline:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")
    seconds_state = pipeline.get_playback_state()
    milliseconds_state = pipeline.reader.get_playback_status()
    return {"cameraId": cid, **seconds_state, **milliseconds_state}


@app.post("/cameras/{camera_id}/playback")
async def seek_camera_playback(camera_id: str, payload: Dict[str, float] = Body(default={})):
    if "positionSeconds" not in payload:
        raise HTTPException(status_code=422, detail="positionSeconds is required")
    cid = camera_id.strip().upper()
    if cid in ["GATE", "GATE1", "GATE_01"]:
        cid = "GATE-01"
    elif cid in ["AREA", "BAIKIEM", "BAI_KIEM"]:
        cid = "BAI-KIEM"
    pipeline = pipelines.get(cid)
    if not pipeline:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")
    if cid == "BAI-KIEM":
        state = await pipeline.request_seek(float(payload["positionSeconds"]))
    else:
        state = pipeline.request_seek(float(payload["positionSeconds"]))
    return {"cameraId": cid, **state}


@app.delete("/cameras/{camera_id}/violations")
async def delete_camera_violations(camera_id: str):
    cid = camera_id.strip().upper()
    if cid in ["AREA", "BAIKIEM", "BAI_KIEM"]:
        cid = "BAI-KIEM"
    if cid != "BAI-KIEM":
        raise HTTPException(
            status_code=409,
            detail="Coordinated violation reset is available only for BAI-KIEM",
        )
    pipeline = pipelines.get(cid)
    if pipeline is None:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")

    result = await pipeline.delete_all_events()
    return {
        "cameraId": cid,
        "deletedRecords": result["deleted_records"],
        "clearedActive": result["cleared_active"],
        "clearedPending": result["cleared_pending"],
    }


def _area_clip_pipeline(camera_id: str):
    cid = camera_id.strip().upper()
    if cid in ["AREA", "BAIKIEM", "BAI_KIEM"]:
        cid = "BAI-KIEM"
    if cid != "BAI-KIEM":
        raise HTTPException(status_code=409, detail="Area clips are available only for BAI-KIEM")
    pipeline = pipelines.get(cid)
    if pipeline is None:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")
    return pipeline


def _validate_violation_id(violation_id: str) -> str:
    try:
        return str(uuid.UUID(violation_id))
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail="violation_id must be a UUID") from exc


@app.post("/cameras/{camera_id}/violations/{violation_id}/clip")
async def request_violation_clip(camera_id: str, violation_id: str):
    pipeline = _area_clip_pipeline(camera_id)
    state = await pipeline.clip_service.request(_validate_violation_id(violation_id))
    if state is None:
        raise HTTPException(status_code=404, detail="Area violation not found")
    return state


@app.get("/cameras/{camera_id}/violations/{violation_id}/clip")
async def get_violation_clip(camera_id: str, violation_id: str):
    pipeline = _area_clip_pipeline(camera_id)
    state = await pipeline.clip_service.get_state(_validate_violation_id(violation_id))
    if state is None:
        raise HTTPException(status_code=404, detail="Area violation not found")
    return state


@app.get("/cameras/{camera_id}/playback/preview")
async def get_camera_playback_preview(camera_id: str, positionSeconds: float):
    if not math.isfinite(positionSeconds) or positionSeconds < 0:
        raise HTTPException(status_code=422, detail="positionSeconds must be a non-negative finite number")
    cid = camera_id.strip().upper()
    if cid in ["GATE", "GATE1", "GATE_01"]:
        cid = "GATE-01"
    elif cid in ["AREA", "BAIKIEM", "BAI_KIEM"]:
        cid = "BAI-KIEM"
    pipeline = pipelines.get(cid)
    if not pipeline:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")
    if not pipeline.get_playback_state().get("seekable"):
        raise HTTPException(status_code=409, detail="Camera source is not seekable")
    frame = await asyncio.to_thread(pipeline.reader.preview_frame, positionSeconds)
    if frame is None:
        raise HTTPException(status_code=503, detail="Cannot decode preview frame")
    ret, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 82])
    if not ret:
        raise HTTPException(status_code=500, detail="Cannot encode preview frame")
    return Response(content=buf.tobytes(), media_type="image/jpeg")


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
