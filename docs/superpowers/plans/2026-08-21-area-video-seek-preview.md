# Area Video Seek Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make local-video seeking responsive without waiting for AI inference, while retaining the existing monitored stream and Zone workflow.

**Architecture:** A worker preview reader opens a short-lived, independent `cv2.VideoCapture` for a requested local-video timestamp and returns a JPEG. The existing pipeline receives the normal seek request in parallel and remains the authority for detections, tracking, and violations. The UI temporarily renders the preview image until the processed feed catches up.

**Tech Stack:** FastAPI, OpenCV, Express proxy, React 19, TypeScript.

## Global Constraints

- Preview is available only for a seekable local video; RTSP behavior remains unchanged.
- Preview access must not move the pipeline's `VideoCapture` or reset tracking.
- The existing POST playback endpoint remains the only operation that commits a seek.
- No Zone, label, violation, or camera activation workflow changes.

---

### Task 1: Isolated worker preview extraction

**Files:**
- Modify: `backend/python-worker/stream/reader.py`
- Modify: `backend/python-worker/main.py`
- Test: `backend/python-worker/tests/test_area_pipeline.py`

**Interfaces:**
- Produces: `StreamReader.preview_frame(position_seconds: float) -> np.ndarray | None`.
- Produces: `GET /cameras/{camera_id}/playback/preview?positionSeconds=<float>` returning `image/jpeg`.

- [ ] Add a test that an invalid/non-local reader produces no preview and that preview extraction does not change the main reader frame position.
- [ ] Implement `preview_frame` using a separate `cv2.VideoCapture(self.source)`, seek with `CAP_PROP_POS_MSEC`, read one frame, resize it to the feed resolution, and release that capture in `finally`.
- [ ] Add the FastAPI endpoint: validate a non-negative finite timestamp, return 404 for unknown camera, 409 for a non-seekable source, 503 for unreadable video frame, and JPEG at quality 82 for a valid preview.
- [ ] Run `python tests/test_area_pipeline.py`.

### Task 2: API proxy and typed client

**Files:**
- Modify: `backend/node-api/src/routes/cameras.ts`
- Modify: `frontend/src/api/cameras.ts`

**Interfaces:**
- Consumes: worker `GET /playback/preview` JPEG response.
- Produces: `getCameraPlaybackPreview(cameraId, positionSeconds): Promise<{ image: string }>`.

- [ ] Add a Node route that validates camera and timestamp, applies a 5-second upstream timeout, verifies image content type, and returns a data URL in the existing success envelope.
- [ ] Add the typed frontend function using `apiClient.get` and URL-encoded timestamp.
- [ ] Run `npm.cmd run typecheck` in `backend/node-api`.

### Task 3: Responsive seek UI

**Files:**
- Modify: `frontend/src/hooks/useAreaMonitor.ts`
- Modify: `frontend/src/components/AreaMonitor.tsx`

**Interfaces:**
- Consumes: `getCameraPlaybackPreview`.
- Produces: `previewPlayback(positionSeconds): Promise<string | null>` returned from `useAreaMonitor`.

- [ ] Add a monotonically increasing preview request token in the hook, so a late response for an older slider position cannot replace the latest preview.
- [ ] On slider release or keyboard seek, request preview and commit the existing seek in parallel; display the preview without detection overlays while waiting.
- [ ] Clear the preview when the processed feed position is within one second of the requested seek position, or when preview retrieval fails.
- [ ] Run `npx.cmd tsc -b` in `frontend`.

### Task 4: Regression verification

**Files:**
- Test: `backend/python-worker/tests/test_area_pipeline.py`
- Test: `backend/node-api/src/tests/test_yard_training_profile.ts` (existing smoke test)

- [ ] Run worker tests and Node typecheck.
- [ ] Confirm manual behavior: dragging stays local, release shows a preview promptly, no false Zone transition occurs during preview, and live/RTSP continues to show no slider.
