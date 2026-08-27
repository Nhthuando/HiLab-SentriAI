# BAI-KIEM Pixel-Aware Zone Boundary Tolerance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Classify a detection as inside a BAI-KIEM Zone when its bottom-center point is no more than 12 physical frame pixels outside the saved polygon.

**Architecture:** `AreaPipeline` supplies the actual `(width, height)` of every decoded frame to `ZoneChecker`. `ZoneChecker` converts normalized polygons and bottom-center points to pixel coordinates, applies a 12 px membership buffer, and leaves the existing event-only hysteresis unchanged.

**Tech Stack:** Python 3.12, OpenCV, Shapely, `unittest`.

## Global Constraints

- Keep `backend/data/training/models/baikiem-v9-unified-candidate-final/best.pt` unchanged.
- Keep inference size 896, confidence thresholds, ByteTrack, target FPS, stored Zone vertices, WebSocket DTOs, and frontend rendering unchanged.
- Use a default membership tolerance of exactly `12.0` pixels.
- Apply membership tolerance to both `ALLOWED` and `VIOLATION` classifications from the first qualifying frame.
- Keep the existing normalized `boundary_hysteresis` separate for already-open violation persistence.
- Do not stage or commit unrelated files from the existing dirty worktree.

---

### Task 1: Specify pixel-aware membership behavior with failing tests

**Files:**
- Modify: `backend/python-worker/tests/test_area_pipeline.py`

**Interfaces:**
- Consumes: `ZoneChecker.check_detections(..., frame_size=(width, height))`.
- Produces: regression coverage for 11 px inside tolerance, 13 px outside tolerance, allowed and violating rules, and resolution independence.

- [ ] **Step 1: Add a normalized bbox helper for a ground-contact point**

Add this helper near the existing `detection` test helper:

```python
def detection_at_bottom_center(
    track_id: int,
    canonical_class: str,
    center_x: float,
    bottom_y: float,
) -> dict[str, object]:
    item = detection(track_id, canonical_class)
    item["normalized_bbox"] = [center_x - 0.01, bottom_y - 0.1, center_x + 0.01, bottom_y]
    return item
```

- [ ] **Step 2: Add allowed membership and strict outside tests**

Use a Zone whose right edge is `x=0.5`, a 640×480 frame, and bottom-center offsets of 11 px and 13 px:

```python
def test_pixel_tolerance_includes_eleven_pixels_but_excludes_thirteen(self):
    checker = ZoneChecker(boundary_tolerance_pixels=12.0)
    zone = [{
        "id": "zone-edge", "name": "Edge",
        "polygon_points": [
            {"x": 0.0, "y": 0.0}, {"x": 0.5, "y": 0.0},
            {"x": 0.5, "y": 1.0}, {"x": 0.0, "y": 1.0},
        ],
        "rule_type": "ALLOW_SPECIFIED", "target_labels": ["Xe nâng container"],
    }]
    class_map = {"reach_stacker": ["Xe nâng container"]}

    near = detection_at_bottom_center(1, "reach_stacker", (320 + 11) / 640, 0.8)
    far = detection_at_bottom_center(2, "reach_stacker", (320 + 13) / 640, 0.8)
    annotated, _ = checker.check_detections(
        [near, far], zone, class_map, frame_size=(640, 480)
    )

    self.assertEqual(annotated[0]["status"], "ALLOWED")
    self.assertEqual(len(annotated[0]["zoneMatches"]), 1)
    self.assertEqual(annotated[1]["status"], "OUTSIDE")
    self.assertEqual(annotated[1]["zoneMatches"], [])
```

- [ ] **Step 3: Add violation and resolution-independence tests**

Verify an 11 px offset is a Zone match for `PROHIBIT_SPECIFIED`, and verify the same 11 px result at 640×480 and 1280×720 by calculating normalized X independently for each frame width.

- [ ] **Step 4: Run the new tests and confirm RED**

Run:

```powershell
.venv/Scripts/python.exe -m unittest tests.test_area_pipeline.TestZoneGeometryAndRules -v
```

Working directory: `backend/python-worker`.

Expected: FAIL because `ZoneChecker` does not accept `boundary_tolerance_pixels` or `frame_size` yet.

### Task 2: Implement pixel-aware membership in ZoneChecker

**Files:**
- Modify: `backend/python-worker/zone/zone_checker.py`
- Test: `backend/python-worker/tests/test_area_pipeline.py`

**Interfaces:**
- Consumes: normalized Zone polygons, normalized detection bboxes, `frame_size: Tuple[int, int]`.
- Produces: `ZoneChecker(boundary_tolerance_pixels=12.0)` and pixel-aware `zoneMatches`/status values.

- [ ] **Step 1: Import Shapely scaling and store the tolerance**

```python
from shapely.affinity import scale as scale_geometry

class ZoneChecker:
    def __init__(
        self,
        camera_id: str = "BAI-KIEM",
        grace_frames: int = 3,
        missing_grace_seconds: float = 12.0,
        boundary_hysteresis: float = 0.02,
        minimum_violation_seconds: float = 1.0,
        boundary_tolerance_pixels: float = 12.0,
    ):
        ...
        self.boundary_tolerance_pixels = min(
            100.0, max(0.0, float(boundary_tolerance_pixels))
        )
```

- [ ] **Step 2: Extend `check_detections` with actual frame size**

Add the optional keyword after `timestamp` to preserve existing callers:

```python
frame_size: Tuple[int, int] = (640, 480),
```

Validate positive finite width and height; fall back to `(640, 480)` for malformed direct/test calls.

- [ ] **Step 3: Build pixel-space membership polygons once per Zone**

For every valid normalized polygon:

```python
pixel_poly = scale_geometry(
    poly,
    xfact=frame_width,
    yfact=frame_height,
    origin=(0.0, 0.0),
)
membership_poly = (
    pixel_poly.buffer(self.boundary_tolerance_pixels)
    if self.boundary_tolerance_pixels > 0.0
    else pixel_poly
)
```

Keep the existing normalized `buffered_poly` for active-event hysteresis.

- [ ] **Step 4: Use pixel membership for visible Zone classification**

For each detection:

```python
det_point_pixels = Point(px * frame_width, py * frame_height)
membership_inside = membership_poly.covers(det_point_pixels)
```

Use `membership_inside` instead of exact normalized containment when adding `zoneMatches` and when allowing a new allowed/violation classification. Keep `sustained_inside` unchanged for existing events.

- [ ] **Step 5: Run geometry/state-machine tests and confirm GREEN**

Run:

```powershell
.venv/Scripts/python.exe -m unittest tests.test_area_pipeline.TestZoneGeometryAndRules tests.test_area_pipeline.TestViolationStateMachine -v
```

Expected: PASS.

### Task 3: Pass decoded frame dimensions from AreaPipeline

**Files:**
- Modify: `backend/python-worker/detection/area_pipeline.py:306`
- Modify: `backend/python-worker/tests/test_area_pipeline.py`

**Interfaces:**
- Consumes: OpenCV frame shape `(height, width, channels)`.
- Produces: `frame_size=(frame.shape[1], frame.shape[0])` for every production Zone check.

- [ ] **Step 1: Add a pipeline contract test**

Inject a mocked `zone_checker`, process a 64×48 test frame, and assert:

```python
zone_checker.check_detections.assert_called_once()
self.assertEqual(
    zone_checker.check_detections.call_args.kwargs["frame_size"],
    (64, 48),
)
```

- [ ] **Step 2: Run the contract test and confirm RED**

Run the exact new test with `python -m unittest ... -v`.

Expected: FAIL because `frame_size` is absent.

- [ ] **Step 3: Pass actual dimensions**

```python
annotated_detections, transitions = self.zone_checker.check_detections(
    detections=raw_detections,
    zones=snapshot.zones,
    class_to_labels=snapshot.class_to_labels,
    timestamp=now_dt,
    frame_size=(int(frame.shape[1]), int(frame.shape[0])),
)
```

- [ ] **Step 4: Run the contract test and complete Area pipeline suite**

Run:

```powershell
.venv/Scripts/python.exe -m unittest tests.test_area_pipeline -v
```

Expected: PASS.

### Task 4: Protect V9 and verify the reported boundary frame

**Files:**
- Read: `backend/data/training/models/baikiem-v9-unified-candidate-final/best.pt`
- Read: live BAI-KIEM feed at 12:43.

**Interfaces:**
- Consumes: restarted worker and current V9 production model.
- Produces: checksum and runtime evidence that only Zone membership changed.

- [ ] **Step 1: Run Python syntax and focused regression tests**

```powershell
.venv/Scripts/python.exe -m compileall -q zone detection/area_pipeline.py
.venv/Scripts/python.exe -m unittest tests.test_area_pipeline -v
```

- [ ] **Step 2: Verify the protected V9 checksum**

Expected SHA-256:

```text
3772E978FC4635A6A2D3DFFB59286BD89C0EBBC6CC6E27DC77532B5006EAAB52
```

- [ ] **Step 3: Restart only Python Worker**

Resolve the process listening on port 8001, verify its command line is the SentriAI worker, stop it, and start `main.py` from `backend/python-worker`. Leave Node API and Vite running.

- [ ] **Step 4: QA the exact reported frame**

Seek BAI-KIEM to 763 seconds (12:43), capture the raw WebSocket detection and browser overlay, and verify:

- V9 still reports `canonicalClass=reach_stacker` with the same high confidence.
- `zoneMatches` includes `Zone mới 1`.
- Status is the Zone rule result rather than `OUTSIDE`.
- No duplicate box is introduced.

- [ ] **Step 5: Restore demand-driven runtime state**

Close the isolated QA browser. Leave playback at the user's 12:43 inspection point and let subscriber demand control worker activation.
