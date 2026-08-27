# Backend Architecture & Slice Handoff Reference

> Maintained by backend workers for integration handoff to frontend and team orchestrators.

## 0. FDN-TRAINING-PERSISTENCE — verified training-data foundation

- **Status**: `backend_verified` on 2026-08-20 against the user-confirmed Neon development/test database.
- **Public API**: no endpoint is introduced by this foundation. Existing `POST /api/v1/samples/batch` accepts only a server-registered imported image/video source, records media kind and selected video-frame timestamp, and stores a normalised bbox. `GET /api/v1/samples` converts the bbox back to canvas percentages for the existing UI.
- **Persistence rules**: legacy samples without source provenance remain intact but cannot be exported for training; no frame or source is inferred. The database permits exactly one active custom augmentation, keeps base YOLO outside the version table, and rejects incomplete video provenance or an active/rejected model without evaluation.
- **Verification**: Prisma schema validation/migration deploy, Node build, REST contract suite, and a create/read/delete sample-provenance fixture all passed. The fixture was removed after the check.

## 0.1 Object-detection training runtime — partial handoff

- **OpenAPI contract**: `backend/node-api/openapi/training.yaml`.
- **Ready API flow**: `GET /training/datasets/readiness` → `POST /training/datasets/export` → `POST /training/jobs` → `POST /training/jobs/{id}/start`; jobs and versions are listed through `GET /training/jobs` and `GET /training/jobs/versions`.
- **Safety contract**: export copies verified source media into an immutable snapshot and separates train/validation by source; a job creates `CANDIDATE` only after checksum and held-out quality gate pass. `REJECTED` versions cannot activate. `POST /training/jobs/versions/{id}/use` activates only a custom augmentation, and `POST /training/jobs/versions/return` disables it while base YOLO remains live.
- **Camera contract**: a training runner starts only when monitors are idle and stops at the next guarded batch if a camera becomes active; it then records `PAUSED_GPU` and retries later. The Area worker loads only the active custom artifact and otherwise retains base detections.
- **Known verification boundary**: no actual labelled training dataset exists yet, so GPU training, held-out metrics and active-candidate FPS have not been run or claimed as passed.

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

Area inference is registry-controlled: YOLO11 COCO owns only `person`/`bicycle`/`car`/`motorcycle`/`bus`/`truck`; a checksum-verified custom `ACTIVE` artifact owns only exact non-COCO classes in its manifest. Until the legacy configured model has an equivalent DB row, `CUSTOM_AUGMENT_FORCE_DEFAULT=true` is a bounded migration bridge: DB `ACTIVE` wins, and the configured artifact is accepted only under `backend/data` with exact `labels.json` plus passing saved quality/base-regression gates. YOLO-World prompts, bus/train coercion, container aliases, geometry relabeling and static-motion suppression are not runtime fallbacks. Missing tracks keep the 12-second exact-class reconnect window; observed exits keep the 3-frame close rule; one-second event confirmation and H.264/yuv420p fast-start clips remain unchanged.

Label API capability is server authority. Zone POST/PUT accepts only exact registered, currently detectable names and returns controlled `LABEL_NOT_REGISTERED`, `LABEL_NOT_DETECTABLE` or `LABEL_AMBIGUOUS` 400 errors. Legacy GET remains readable. Python keeps one atomic capability/zone/model snapshot and preserves the exact prior snapshot on refresh failure.

Detection benchmark defaults are base initiate/continue `0.30/0.14`, custom `0.45/0.25`, and custom 2-of-3 temporal confirmation. They are not hard floors: existing calibrated `AREA_TRACK_*` values or explicit `AREA_BASE_*` values remain effective, while continuation still cannot exceed initiation and a low hit cannot create a new event. ROI is disabled by default; when enabled it uses bounded 640 tiles, 0.20 overlap, every third frame, maximum 8 tiles, class-aware dedupe and separate ROI/full-frame clocks. See `backend/.env.example` and `docs/evaluation/bai-kiem-baseline-report.md`.

- Python Unit tests for Point-in-polygon covers, Rule Matrix, state transitions, missing-track continuity, track reidentification, boundary jitter suppression, outside-zone classification, local-video rewind/reset and playback pacing, one-second event confirmation, and H.264 clip output: PASSED (20/20) on 2026-08-18.
- Node.js typecheck: PASSED. The standalone Neon REST verifier remains pending after a sandbox TLS failure and an approved retry timeout.

## 2. VS-SETTINGS-ZONE — BAI-KIEM Zone Editor

- **Status**: Implementation complete; live HTTP/DB verification pending user acceptance.
- **Branch**: `feature/vs-settings-zone` (stacked on the committed Area branch).
- **OpenAPI Contract**: `backend/node-api/openapi/zones.yaml`
- **Routes**:
  - `GET /api/v1/zones?camera_id=BAI-KIEM`
  - `POST /api/v1/zones`
  - `PUT /api/v1/zones/:id`
  - `DELETE /api/v1/zones/:id`
  - `GET /api/v1/cameras/BAI-KIEM/snapshot`
- **Rules**: Only `BAI-KIEM` is accepted; polygon points are normalized `[0,1]` with at least three points; `ruleType` is `PROHIBIT_SPECIFIED|ALLOW_SPECIFIED`; duplicate names return `409`; deleting a referenced zone returns `409`.
- **Worker integration**: Area `ZoneSynchronizer` already polls active BAI-KIEM zones every five seconds. Snapshot proxy reads `PYTHON_WORKER_HTTP_URL` (default `http://localhost:8001`).
- **Basic evidence**: Node typecheck and focused pure validation test pass. CRUD/snapshot HTTP evidence is intentionally pending manual user testing.
