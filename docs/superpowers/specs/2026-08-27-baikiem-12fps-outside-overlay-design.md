# BAI-KIEM 12 FPS and Outside-Zone Overlay Design

## Goal

Increase the BAI-KIEM processing target from 10 FPS to 12 FPS without changing V9 inference accuracy, and make detections at the image/Zone boundary visible without changing Zone membership or violation behavior.

## Approved behavior

- Keep the active V9 `best.pt`, inference size 896, confidence policy, class mapping, ByteTrack configuration, and ZoneChecker unchanged.
- Change only the BAI-KIEM target processing rate from 10 FPS to 12 FPS.
- Continue to render detections that match a Zone with the existing allowed/violation colors and labels.
- Render detections whose status is `OUTSIDE` with a neutral gray overlay and the suffix `NGOÀI ZONE`.
- Outside-Zone detections must not create Zone events, appear as violations, or affect persistence.

## Data flow

The Python Worker continues to run V9 and ZoneChecker exactly as before. ZoneChecker annotates every supported detection with `zoneMatches` and `status`. The WebSocket payload already contains detections marked `OUTSIDE`; only the frontend currently discards them. The frontend will stop discarding those records and will select neutral presentation when `zoneMatches` is empty or `status` is `OUTSIDE`.

## Performance boundary

The deployed RTX 3050 Laptop GPU measured about 9.6 FPS under the current 10 FPS cap, with roughly 32-35% average GPU utilization and a sampled peak of 61%. Existing V9 artifacts report 19.715 model FPS and 15.233 end-to-end FPS at inference size 896. A 12 FPS target leaves operational headroom while avoiding any accuracy-affecting optimization such as reducing inference size, changing confidence, changing weights, or enabling a different precision mode.

## Failure and safety behavior

- If the machine cannot sustain 12 FPS, the loop naturally runs at its achievable rate; it must not skip detection or lower image size automatically.
- A detection outside all Zones remains visible but neutral and must never be described as allowed or violating.
- Existing event lists and event persistence remain driven only by ZoneChecker transitions.

## Verification

- Frontend TypeScript typecheck and production build pass.
- Existing relevant frontend/backend tests pass where available.
- The active V9 SHA-256 remains `3772e978fc4635a6a2d3dffb59286bd89c0ebbc6cc6e27dc77532b5006eaab52`.
- After restarting the Python Worker, `/health` reports BAI-KIEM near 12 FPS while GATE-01 remains demand-paused.
- A boundary detection with no `zoneMatches` is visible as `NGOÀI ZONE` and produces no Zone event.

## Out of scope

- Retraining or replacing V9.
- Changing confidence thresholds, inference size, JPEG quality, tracking, Zone geometry, or the bottom-center Zone rule.
- Expanding a Zone to include the image boundary.
