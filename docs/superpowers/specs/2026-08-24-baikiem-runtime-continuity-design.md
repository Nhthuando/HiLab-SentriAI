# BAI-KIEM Runtime Detection Continuity Design

## Problem

V8 detects the reach stacker reliably when run directly on the first 30 seconds of `KiemHoa-Hik (2).mp4`: 151/151 sampled frames exceed confidence 0.40, with confidence 0.808-0.822 and sub-pixel box-center variation. The visible 13-15 second initial delay, label dropout, `truck` fallback, and box jumping are therefore runtime integration defects rather than a need for more training.

## Goals

- Show the first confirmed reach-stacker label within one second of the first live frame after the worker is ready.
- Preserve a stable custom track ID and custom box when base YOLO/ByteTrack loses or changes its generic `truck` track.
- Keep a confirmed custom label through short inference gaps without creating a new model inference pass.
- Never display an overlapping generic `truck`, `bus`, or `car` while a live confirmed `reach_stacker` track owns that object.
- Keep the existing 2-of-3 rule before initial custom promotion, confidence 0.40, custom interval 2, and tile inference disabled.
- Do not train, change datasets, access locked test data, or add inference work per frame.

## Design

### Startup prewarm

`AreaPipeline.prepare()` refreshes the initial detection-control snapshot, loads the configured custom artifact, and runs one black-frame detector pass on a worker thread. It resets all tracker state after the pass. `main.py` awaits this preparation during application startup, so first-subscriber latency no longer includes database refresh, model loading, CUDA initialization, or predictor initialization. A preparation failure is logged and leaves the existing fail-closed base detector available.

### Custom-owned spatial identity

Supplemental custom detections no longer use a generic base track ID as their evidence key. Each custom object receives one negative synthetic track ID and is re-associated by canonical class plus the best IoU/center-distance match. A candidate already matched in the same inference opportunity cannot be reused by a second object. Base detections remain useful as corroborating geometry, but they do not own the reach-stacker identity.

### Sticky confirmation and box smoothing

Initial promotion still requires two hits in the latest three custom-inference opportunities. After promotion, a candidate remains confirmed for eight missed custom opportunities. At 10 FPS with custom interval 2 this is approximately 1.6 seconds. Any new matching hit refreshes the track immediately. Boxes use an exponential moving average with 0.65 weight on the current observation, limiting jitter without a material lag, and each normalized edge is capped to a 0.015-frame step.

After confirmation, a spatially overlapping generic base detection may continue the custom track through a longer V8 confidence gap. Its motion and bounded scale update the custom box, but its class and ByteTrack ID never replace the custom label or synthetic identity. Twelve base frames of grace cover brief base-detector gaps; without either custom or spatial base support, normal expiry still applies.

### Output arbitration

Each active confirmed custom candidate emits exactly one custom detection using its stable synthetic ID and most recent smoothed box. An overlapping generic vehicle detection is suppressed for that frame. Non-overlapping base detections and all non-vehicle classes pass through unchanged. Once the custom hold expires, the candidate is removed and the base result may appear again.

## Failure handling

- Model-load or warmup failure keeps base COCO inference active and logs one actionable error.
- A malformed custom box is ignored without modifying base detections.
- State is cleared on seek, rewind, model/control change, and worker shutdown as before.
- No custom observation is retained beyond the bounded hold/expiry window.

## Verification

- Unit tests cover stable identity across changing/missing base IDs, 2-of-3 initial promotion, bounded hold, eventual expiry, box EMA/edge limiting, generic-label suppression, and startup prewarm/reset.
- Existing Area, taxonomy, policy, ROI, emitter, and Node type checks continue to pass.
- A live WebSocket run over the first 30 seconds of `KiemHoa-Hik (2).mp4` must show V8 before one second of emitted video, one stable custom track ID, no overlapping `truck` fallback, no post-confirmation dropout, no reconnect storm, and no deprecated `half` warning.

## Scope exclusions

This change does not claim universal accuracy on unseen cameras. It fixes continuity for detections the model already makes reliably. Domain generalization remains a separate measured dataset/model problem.
