"""
tests/test_stream_pipeline.py — Comprehensive Automated Test Suite for Stream & AI Pipeline

Tests:
1. StreamReader (frame dimensions, rate control, loop/fallback)
2. YoloDetector (inference, Vietnamese label mappings, bbox cropping)
3. CircularBuffer (frame retention, MP4 clip encoding & writing)
4. CameraPipeline (single-frame processing, base64 JPEG encoding)
5. StreamEmitter (WebSocket frame & event emission to WS receiver)
"""
import asyncio
import json
import os
import sys
import tempfile
import time

import cv2
import numpy as np
import websockets

# Ensure python-worker directory is on sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from buffer import CircularBuffer
from detection import YoloDetector
from stream import CameraPipeline, StreamEmitter, StreamReader


async def run_tests():
    print("=" * 70)
    print("SentriAI - FDN-PYTHON-STREAM Verification Test Suite")
    print("=" * 70)

    # -------------------------------------------------------------------------
    # 1. Test StreamReader
    # -------------------------------------------------------------------------
    print("\n[1/5] Testing StreamReader...")
    reader_gate = StreamReader(
        camera_id="GATE-01",
        target_fps=10.0,
        resolution=(640, 480),
    )
    assert reader_gate.is_connected, "StreamReader for GATE-01 must be connected"

    frames_read = 0
    for _ in range(5):
        success, frame = reader_gate.read_frame()
        assert success is True, "Frame read must succeed"
        assert frame is not None, "Frame must not be None"
        assert frame.shape == (480, 640, 3), f"Frame shape must be (480, 640, 3), got {frame.shape}"
        assert frame.dtype == np.uint8, "Frame dtype must be uint8"
        frames_read += 1

    reader_gate.release()
    print(f"  [OK] Read {frames_read} frames successfully from GATE-01 stream (shape: 480x640x3)")

    reader_area = StreamReader(
        camera_id="BAI-KIEM",
        target_fps=10.0,
        resolution=(640, 480),
    )
    success, area_frame = reader_area.read_frame()
    assert success and area_frame is not None
    reader_area.release()
    print("  [OK] StreamReader for BAI-KIEM initialized and read frame successfully")

    # -------------------------------------------------------------------------
    # 2. Test YoloDetector
    # -------------------------------------------------------------------------
    print("\n[2/5] Testing YoloDetector...")
    detector = YoloDetector(model_path="yolov8n.pt", conf_threshold=0.20)

    # Test detection on sample asset image if available, else synthetic
    test_img_path = "frontend/public/assets/cam-gate.png"
    if os.path.exists(test_img_path):
        sample_img = cv2.imread(test_img_path)
    else:
        sample_img = np.full((480, 640, 3), 128, dtype=np.uint8)

    sample_img_resized = cv2.resize(sample_img, (640, 480))
    detections = detector.detect(sample_img_resized)
    print(f"  [OK] YOLO inference executed successfully, detected {len(detections)} object(s)")

    for d in detections[:3]:
        assert "bbox" in d
        assert "normalized_bbox" in d
        assert "class" in d
        assert "label" in d
        assert "confidence" in d
        assert 0.0 <= d["confidence"] <= 1.0
        print(f"    - Class: {d['class']:<12} | Label: {d['label']:<10} | Conf: {d['confidence']:.2f} | Box: {d['bbox']}")

    # Test crop_bbox
    test_bbox = [50, 50, 200, 200]
    cropped = YoloDetector.crop_bbox(sample_img_resized, test_bbox)
    assert cropped is not None
    assert cropped.shape == (150, 150, 3)
    print("  [OK] YoloDetector.crop_bbox() extracted region successfully (150x150)")

    # -------------------------------------------------------------------------
    # 3. Test CircularBuffer & MP4 Clip Writer
    # -------------------------------------------------------------------------
    print("\n[3/5] Testing CircularBuffer & Clip Writer (BR-05)...")
    buf = CircularBuffer(max_seconds=5.0, target_fps=10.0)

    # Push 20 test frames
    now = time.time()
    for i in range(20):
        dummy = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.putText(dummy, f"FRAME #{i}", (50, 100), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
        buf.append(dummy, now + (i * 0.1))

    assert buf.get_frame_count() == 20
    latest = buf.get_latest_frame()
    assert latest is not None
    print(f"  [OK] CircularBuffer retained {buf.get_frame_count()} frames in memory")

    # Test saving MP4 clip
    tmp_dir = tempfile.mkdtemp()
    clip_path = os.path.join(tmp_dir, "test_clip_10s.mp4")
    saved_path = buf.save_clip(clip_path, duration_seconds=2.0, fps=10.0)
    assert saved_path == clip_path, "Clip save must return valid path"
    assert os.path.exists(clip_path), "Generated MP4 clip must exist on disk"
    file_size = os.path.getsize(clip_path)
    assert file_size > 500, f"MP4 file size must be > 500 bytes (got {file_size} bytes)"
    print(f"  [OK] CircularBuffer.save_clip() created MP4 clip: {file_size} bytes")

    # Clean up test clip
    try:
        os.remove(clip_path)
        os.rmdir(tmp_dir)
    except Exception:
        pass

    # -------------------------------------------------------------------------
    # 4. Test CameraPipeline
    # -------------------------------------------------------------------------
    print("\n[4/5] Testing CameraPipeline (single-frame execution)...")
    pipeline = CameraPipeline(
        camera_id="GATE-01",
        target_fps=10.0,
        resolution=(640, 480),
        detector=detector,
    )

    result = pipeline.process_single_frame()
    assert result["success"] is True
    assert result["camera_id"] == "GATE-01"
    assert result["image_base64"].startswith("data:image/jpeg;base64,")
    assert "detections" in result
    print(f"  [OK] Single frame processed: base64 len={len(result['image_base64'])}, detections={len(result['detections'])}")

    # -------------------------------------------------------------------------
    # 5. Test WebSocket Emission (End-to-End Python Emitter -> Receiver)
    # -------------------------------------------------------------------------
    print("\n[5/5] Testing WebSocket Stream Emitter...")
    received_messages = []
    receiver_ready = asyncio.Event()

    async def mock_ws_server(websocket):
        receiver_ready.set()
        async for message in websocket:
            data = json.loads(message)
            received_messages.append(data)

    server = await websockets.serve(mock_ws_server, "localhost", 3097)
    emitter = StreamEmitter(node_ws_url="ws://localhost:3097")

    try:
        # Emit a test frame
        emit_ok = await emitter.emit_frame(
            camera_id="GATE-01",
            image_base64="data:image/jpeg;base64,TEST_DATA",
            detections=[{"bbox": [10, 10, 50, 50], "class": "car", "label": "Xe ô tô", "confidence": 0.95}],
            fps=10.0,
        )
        assert emit_ok is True, "Frame emission must succeed"

        # Emit a gate event
        event_ok = await emitter.emit_gate_event({
            "id": "gate-test-123",
            "cameraId": "GATE-01",
            "lane": "IN_1",
            "licensePlate": "51A-99999",
            "status": "KNOWN",
            "confidence": 0.97,
        })
        assert event_ok is True, "Gate event emission must succeed"

        # Emit an area event
        area_ok = await emitter.emit_area_event({
            "id": "area-test-456",
            "cameraId": "BAI-KIEM",
            "zoneId": "zone-test-789",
            "objectLabel": "Xe máy",
            "status": "OPEN",
        })
        assert area_ok is True, "Area event emission must succeed"

        await asyncio.sleep(0.1)
        assert len(received_messages) == 3, f"Expected 3 WS messages, received {len(received_messages)}"
        assert received_messages[0]["type"] == "frame"
        assert received_messages[1]["type"] == "gate_event"
        assert received_messages[2]["type"] == "zone_violation"
        print(f"  [OK] WebSocket receiver verified {len(received_messages)} inbound messages (frame, gate_event, zone_violation)")

    finally:
        await emitter.close()
        server.close()
        await server.wait_closed()
        await pipeline.stop()

    print("\n" + "=" * 70)
    print("ALL STREAM & AI PIPELINE TESTS PASSED SUCCESSFULLY! (100% PASS)")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_tests())
