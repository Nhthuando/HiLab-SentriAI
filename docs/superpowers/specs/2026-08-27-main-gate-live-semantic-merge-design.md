# Main and Gate Live Semantic Merge Design

## Goal

Resolve the in-progress merge between `main` and `origin/feature/vs-gate-live` without regressing the verified BAI-KIEM Area Violation flow, the GATE-01 license-plate flow, or Vehicle Settings.

## Approved runtime behavior

- BAI-KIEM keeps the `main` AreaPipeline behavior, including tracking, zone rules, events, clips, reset, playback, and preview.
- BAI-KIEM keeps its current `1280x720` default and environment-driven target FPS.
- GATE-01 keeps the feature branch's validated `1600x900` and 15 FPS defaults for plate-recognition quality.
- Each pipeline starts when its corresponding live view has subscribers and pauses when it no longer has subscribers.
- Environment variables may override camera FPS without coupling the two pipelines.

## Considered approaches

1. Accept whole files from `main` or the feature branch. This is fast but drops behavior wherever both branches changed the same shared file.
2. Resolve by semantic ownership and preserve both public contracts. This is the selected approach because Area-owned files can retain `main`, Gate-owned files can retain the feature work, and shared files can be merged additively.
3. Refactor both pipelines around new shared abstractions. This could reduce duplication but is outside the merge scope and would invalidate more of the existing test evidence.

## Merge ownership

### BAI-KIEM-owned behavior

`main` remains authoritative for AreaPipeline, TrackedYoloDetector, BAI-KIEM activation, event reset, clip generation, playback preview, object-label registry behavior, and Area frontend state. Gate-only changes to shared detection classes are added without changing the Area rule or tracking state machines.

### GATE-01-owned behavior

`origin/feature/vs-gate-live` remains authoritative for GatePipeline, PlateTracker, plate localization, passage deduplication, live plate overlays, UNKNOWN handling, camera confidence configuration, crop display, and Gate playback controls. The `main` database-backed vehicle status, automatic stranger registration, activation lifecycle, and reset-safe playback behavior are then applied to that implementation.

### Shared behavior

- `detector.py` keeps `main` model-path configuration and COCO registry restrictions while adding the Gate branch's CUDA reporting, CPU fallback, and high-angle vehicle recovery.
- `stream/reader.py` keeps the `main` synchronized local-video, preview, seek, loop-reset, and locking behavior while retaining the Gate branch's bounded frame skipping and timecode-compatible accessors.
- `stream/emitter.py` emits additive fields for Area zones, source reset, Gate timecode, and source dimensions. JSON serialization failures do not trigger reconnect storms.
- Worker and Node camera routes support the seconds-based playback/preview contract used by `main`, the millisecond Gate seek compatibility contract, and Gate confidence configuration.
- Frontend camera APIs export both playback/preview and confidence configuration functions.
- Python requirements contain the union of runtime dependencies, use `ultralytics>=8.3.0,<9.0.0`, and retain the CUDA, FastALPR, ONNX, ByteTrack, and clip-writing dependencies from `main`.

## Frontend integration

- `App.tsx` keeps BAI-KIEM zones, object-label registry, media sources, Area alerts, and other `main` state.
- Vehicle data remains backend-owned rather than falling back to mock records.
- `GateMonitor.tsx` keeps both the `main` clear-history action and the feature branch's normalized events, UNKNOWN rows, crop modal, playback controls, timecode, and source-size-aware overlays.
- `VehicleLabelTab.tsx` keeps the `main` pagination, persistent cross-page selection, and bulk actions while retaining the feature branch's Gate confidence control and crop/sample improvements.
- Types are merged additively; existing Area fields are not renamed to fit Gate fields.

## Conflict and data handling

- `.gitignore` is the union of both branches and must not unignore local models, runtime data, clips, crops, caches, or secrets.
- Both database migrations from the Gate branch remain included because they add Gate event context and vehicle backfill required by the new Gate behavior.
- Modify/delete Gate tests are restored when they still exercise supported behavior; obsolete assertions are updated to the merged public contract rather than silently removing regression coverage.
- No existing database data is deleted or rewritten as part of conflict resolution.

## Verification

1. Confirm no unmerged entries or conflict markers remain.
2. Compile all changed Python worker modules.
3. Run the focused Area regression suite, including tracking, reset, clip, playback, and zone tolerance tests.
4. Run the focused Gate regression suite, including LPR, passage deduplication, bbox lifecycle, registration, stream, and playback tests.
5. Run Node API typecheck and the relevant camera, Area, and Gate API tests.
6. Run the frontend TypeScript/Vite production build and lint.
7. Inspect the final staged diff to ensure no unrelated `main` behavior or feature-branch behavior was discarded.
8. Leave the completed merge uncommitted for user review unless the user explicitly asks Codex to create the merge commit.

## Success criteria

- BAI-KIEM retains its current Area Violation behavior and defaults.
- GATE-01 retains the feature branch's verified plate-recognition behavior and defaults.
- Vehicle Settings retains CRUD, pagination, bulk selection, Gate threshold configuration, and sample/crop behavior.
- Both camera control contracts work through Python, Node, and frontend layers.
- Automated verification passes, or any environment-only blocker is reported with the exact failing command and unaffected checks.
