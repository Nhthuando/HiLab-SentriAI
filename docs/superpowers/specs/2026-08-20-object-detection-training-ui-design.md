# Object Detection Training UI Design

## Scope

Extend the existing Settings → Object Labels tab with one bounded flow, `M3-OBJECT-DETECTION-TRAINING`. It lets the single local user see whether saved annotation samples are trainable, explicitly start a training run, monitor GPU-protected progress, inspect an evaluated candidate model, and activate or roll back a version.

The flow implements visual/mock behavior only. It does not define or call an API, change backend behavior, upload model artifacts, or auto-start training after a sample is saved.

## Evidence and constraints

- Product extension `ext-20260820-object-detection-training` requires manual start, evaluation before activation, and no interruption of monitoring.
- Architecture extension §11 requires a GPU governor that protects Area Monitor at 8 FPS, candidate versions, explicit activation and rollback.
- Database spec defines the states and information future integration must expose: dataset readiness, job status/progress/pause reason, candidate metrics, active version.
- The existing `ObjectLabelTab` is the approved, established workspace for importing media, selecting a video frame, drawing boxes and saving samples. The new control is therefore an inline panel, not a route or a new Settings tab.

## Chosen interaction model

The panel appears below the saved sample list and has three mutually exclusive states:

1. **Dataset readiness:** Shows total valid samples, label coverage, source count and any excluded sample count. The primary action is disabled until the local mock reaches the stated readiness threshold; no save action triggers training.
2. **Training in progress:** Replaces the start action with progress, epoch, current Area FPS and a clear governor status. A `PAUSED_GPU` state uses an amber notice explaining that monitor inference has priority; it never reads as a failure.
3. **Candidate/version review:** Shows held-out mAP, per-class forklift metric, benchmark FPS, version identifier and timestamp. `Activate` is enabled only on an evaluated passing candidate. `Rollback` is available only when a prior inactive version exists. Activation always requires a confirmation dialog.

## Layout and visual language

- Reuse existing Modern Industrial tokens, Inter/IBM Plex Mono typography, panel/card geometry and semantic colors.
- Header: `Huấn luyện model` + compact non-blocking subtitle `Mẫu đã lưu không tự khởi động train`.
- Readiness and metric cells use concise mono numerals; forklift metric is visually first-class but does not hide overall mAP.
- Green: active/ready/passed; amber: governor pause or awaiting more samples; rose: failed evaluation; blue: primary user action.
- At desktop width, readiness, job progress and candidate cards are a three-column responsive grid. At narrow width they stack in this semantic order.
- Controls are semantic buttons, include visible focus, disabled explanation and `aria-live` on asynchronous/mock status messages.

## Mock data and transitions

The component keeps isolated local mock state. It derives readiness from existing annotation samples, but uses mock job/version records for progress and metrics. Required mock transitions:

```text
not_ready -> ready -> queued -> running <-> paused_gpu -> evaluating -> candidate
candidate -> activate_confirm -> active
active + prior_version -> rollback_confirm -> prior_active
```

The mock must show empty/readiness, disabled, running, paused, evaluation-passed, evaluation-failed and recoverable error visual states. Reload persistence and real job resume are intentionally production integration gaps.

## Acceptance for review

- The user can understand why Train is disabled without leaving the tab.
- Saving samples changes readiness only; it never changes job state.
- During `PAUSED_GPU`, the UI explicitly says Area monitoring has priority and preserves current candidate/active model state.
- Candidate quality and FPS are both visible before activation.
- Activation/rollback affordances cannot be triggered accidentally and work by keyboard.
- The existing image/video import, video scrubber, bounding-box editing, label saving and zone-label availability remain visually and functionally unchanged in mock mode.

## Verification plan

- Run the existing Vite build.
- Open the Settings → Object Labels route in a real browser at desktop and mobile widths.
- Exercise disabled Train, start, pause/resume presentation, candidate activation confirmation and rollback confirmation.
- Confirm no network/API integration was added and existing label workflow remains available.

## Explicit non-goals

- No automatic train after saving a sample.
- No guarantee that a model becomes accurate without representative samples.
- No backend endpoint, database migration, Python training process or model activation implementation in this UI-design step.

## Repair: non-technical wording and progressive disclosure

**Scope:** Only `ObjectTrainingPanel.tsx`; `ObjectLabelTab` layout, import, frame selection, bbox editing and save behavior are protected.

**Change:** Replace internal terminology in the primary path with user language: `Cải thiện nhận diện`, `Bản nhận diện mới`, `Dùng bản mới`, and `Quay về bản trước`. The panel communicates a simple three-step sequence: save enough samples, start improvement, then choose a checked result. GPU/FPS/mAP and mock/demo wording move behind an opt-in `Xem thông tin kỹ thuật` disclosure. The visible paused state says the camera is being protected, not that a GPU governor intervened.

**Reason:** A non-technical operator needs an action and plain consequence, not model lifecycle terms. The status remains honest, while technical evidence is still available to an operator who needs it.

**Verification:** Build the frontend; in the live panel, verify the primary path contains no `candidate`, `rollback`, `GPU`, `FPS`, `mAP`, `epoch`, or `mock` wording until the technical disclosure is opened. Confirm all existing label flow controls remain unchanged.
