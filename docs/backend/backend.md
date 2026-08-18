# Backend Architecture & Slice Handoff Reference

> Maintained by backend workers for integration handoff to frontend and team orchestrators.

## 1. VS-AREA-VIOLATION — Giám sát khu vực (Camera BAI-KIEM)

- **Status**: Stabilized implementation; formal verification pending
- **Assigned Slice**: `VS-AREA-VIOLATION`
- **Owner**: Hữu Thuận
- **Branch**: `feature/vs-area-violation`
- **OpenAPI Contract**: `backend/node-api/openapi/area.yaml`

### 1.1 REST Endpoints

- `GET /api/v1/events/area`
  - **Query Parameters**:
    - `limit`: number (1..100, default 50)
    - `offset`: number (>= 0, default 0)
    - `zone_id`: UUID string (optional)
    - `status`: `'OPEN' | 'CLOSED'` (optional)
  - **Response**: Standard envelope containing `AreaEventsResponseData`:
    ```json
    {
      "success": true,
      "data": {
        "items": [
          {
            "id": "c1f7b8...-uuid",
            "cameraId": "BAI-KIEM",
            "zoneId": "z1...-uuid",
            "zoneName": "Khu vực cấm xe máy",
            "objectLabel": "Xe máy",
            "status": "OPEN",
            "enteredAt": "2026-08-18T02:00:00.000Z",
            "exitedAt": null,
            "durationSeconds": null,
            "clipUrl": null
          }
        ],
        "total": 1,
        "limit": 50,
        "offset": 0
      },
      "timestamp": "2026-08-18T02:00:00.000Z"
    }
    ```

### 1.2 WebSocket Channels

1. **Live Camera Feed with Detections & Zones**: `WS /ws/feed/area`
   - Client receives:
     ```json
     {
       "type": "frame",
       "cameraId": "BAI-KIEM",
       "timestamp": 1787018400000,
       "image": "data:image/jpeg;base64,...",
       "fps": 10.0,
       "detections": [
         {
           "trackId": 17,
           "bbox": [120, 80, 220, 300],
           "normalized_bbox": [0.1875, 0.1667, 0.3438, 0.625],
           "class": "motorcycle",
           "label": "Xe máy",
           "confidence": 0.91,
           "status": "VIOLATION",
           "zoneMatches": [
             {
               "zoneId": "uuid",
               "zoneName": "Khu vực cấm xe máy",
               "status": "VIOLATION"
             }
           ]
         }
       ],
       "zones": [
         {
           "id": "uuid",
           "name": "Khu vực cấm xe máy",
           "polygon": [{"x": 0.1, "y": 0.2}],
           "ruleType": "PROHIBIT_SPECIFIED",
           "targetLabels": ["Xe máy"]
         }
       ]
     }
     ```

2. **Violation Events Notification**: `WS /ws/events/area`
   - Client receives on entry (`STARTED`) and exit (`ENDED`):
     ```json
     {
       "type": "zone_violation",
       "action": "STARTED",
       "id": "uuid",
       "cameraId": "BAI-KIEM",
       "zoneId": "uuid",
       "zoneName": "Khu vực cấm xe máy",
       "objectLabel": "Xe máy",
       "status": "OPEN",
       "enteredAt": "2026-08-18T02:00:00.000Z",
       "exitedAt": null,
       "durationSeconds": null,
       "clipUrl": null
     }
     ```

3. **Floating Cross-Tab Urgent Alerts**: `WS /ws/alerts`
   - Client receives on new violation `STARTED`:
     ```json
     {
       "type": "alert",
       "level": "critical",
       "title": "CẢNH BÁO VI PHẠM ZONE",
       "message": "Phát hiện Xe máy trong Khu vực cấm xe máy",
       "cameraId": "BAI-KIEM",
       "timestamp": "2026-08-18T02:00:00.000Z",
       "data": {
         "violationId": "uuid",
         "zoneId": "uuid",
         "zoneName": "Khu vực cấm xe máy",
         "objectLabel": "Xe máy"
       }
     }
     ```

### 1.3 Database Models & Data Rules

- `zones`: Polygon points in JSON normalized `[0,1]`. Polled every 5s by Python worker.
- `zone_violations`: OPEN on entry, CLOSED on exit with duration. `clip_path` updated on 10s clip generation.
- `object_labels`: Vietnamese category mapping for YOLO classes.

### 1.4 Verification Summary

> The prior automated evidence is historical and was invalidated by the 2026-08-18 stabilization changes. No verifier was rerun at the user's request.

The latest user-reported follow-up is addressed in the worker: Area inference is limited to `person`/`truck` (`truck` is the configured `Container` label), a missing track has a 5-second identity-reconnect window while an observed exit retains the 3-frame close rule, and new clips are H.264/yuv420p MP4 with browser-friendly fast-start metadata. Existing FMP4 historical clips are not transcoded. Entry remains exact-polygon-only, while an already-open violation gets a `0.02` normalized outward boundary buffer (about 13px at 640px inference width) to stop detector jitter at the edge from repeatedly closing and reopening one event.

- Python Unit tests for Point-in-polygon covers, Rule Matrix, state transitions, missing-track continuity, track reidentification, boundary jitter suppression, and H.264 clip output: PASSED (15/15) on 2026-08-18.
- Node.js typecheck: PASSED. The standalone Neon REST verifier remains pending after a sandbox TLS failure and an approved retry timeout.
