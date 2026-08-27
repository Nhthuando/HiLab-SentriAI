# BAI-KIEM Pixel-Aware Zone Boundary Tolerance Design

## Goal

Treat a detection as inside a BAI-KIEM Zone when its bottom-center ground-contact point is no more than 12 pixels outside the saved polygon. This fixes edge jitter without changing V9, confidence thresholds, tracking, the saved Zone geometry, or the polygon drawn by the frontend.

## Current Behavior

`ZoneChecker` evaluates the normalized bottom-center point of every bounding box against the exact polygon. It already creates a normalized `0.02` buffer, but that buffer only sustains an already-open violation. It does not classify an allowed object or a first observation near the boundary as inside. Because normalized X and Y units represent different pixel distances on a non-square frame, reusing `0.02` for general membership would produce an uneven tolerance.

## Chosen Design

Add a pixel-aware membership tolerance with a default value of 12 pixels.

For each processed frame:

1. `AreaPipeline` passes the actual frame width and height to `ZoneChecker`.
2. `ZoneChecker` scales the normalized Zone polygon into that frame's pixel coordinate system.
3. It expands the pixel-space polygon by 12 pixels with Shapely.
4. It scales the detection's normalized bottom-center point into the same pixel coordinate system.
5. The detection is a Zone member when the expanded polygon covers that point.

This tolerance applies consistently to both `ALLOWED` and `VIOLATION` classifications from the first qualifying frame. A point farther than 12 pixels from the polygon remains `OUTSIDE`.

## Existing Event Hysteresis

The existing normalized `boundary_hysteresis` remains separate and continues to protect an already-open violation from rapid close/reopen cycles. It does not define the visible membership tolerance. This preserves current event stability while making the UI membership decision explicit and pixel-aware.

## Interfaces

- `ZoneChecker` receives an optional `frame_size=(width, height)` for each `check_detections` call.
- Unit tests that omit `frame_size` use the existing 640×480 fallback.
- `AreaPipeline` passes `frame.shape[1]` and `frame.shape[0]`.
- The tolerance is owned by `ZoneChecker` as `boundary_tolerance_pixels=12.0` and is clamped to a safe non-negative range.

No WebSocket, REST, database, or frontend contract changes are required.

## Safety and Side Effects

- The logical Zone extends by exactly 12 pixels on every edge, while the drawn polygon remains unchanged.
- An object genuinely outside but within the 12-pixel band is intentionally treated as inside.
- Adjacent Zones separated by less than 24 pixels can both match the same ground-contact point. Existing multi-Zone behavior already supports more than one `zoneMatch` and remains deterministic.
- Pixel-space buffering adds negligible CPU cost compared with model inference. Buffered polygons are built once per Zone per processed frame, not once per detection.
- V9 weights, inference size, confidence policy, ByteTrack settings, and FPS target remain unchanged.

## Verification

Add tests proving that:

- An allowed object whose bottom-center is 11 pixels outside a Zone is classified `ALLOWED` and receives a `zoneMatch`.
- A violating object in the same 11-pixel band can enter normal pending/active violation processing.
- A bottom-center point 13 pixels outside the Zone remains `OUTSIDE`.
- The result is equivalent for differently sized frames when the physical pixel offset is the same.
- Existing exact-inside, exit-grace, missing-track, and event-hysteresis tests still pass.

Runtime QA uses the reported BAI-KIEM frame at 12:43 and confirms the reach stacker changes from `NGOÀI ZONE` to the Zone's configured allowed/violation result without changing its V9 detection.

## Out of Scope

- Box-overlap or center-point membership rules.
- Automatically editing or expanding stored Zone vertices.
- Drawing the tolerance band in the UI.
- Retraining, replacing, or tuning V9.
