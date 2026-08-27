# BAI-KIEM V9 Locked-Test Pre-label Design

## Purpose

Use the annotation-only checkpoint trained from CVAT task 9 to create editable
rectangle proposals for the 200 images in CVAT task 10. This reduces manual
annotation time without allowing locked-test images, annotations, or metrics to
influence training, validation, checkpoint selection, confidence tuning, or the
active SentriAI model.

## Data boundary

- CVAT task 9 is the only annotation source used by the helper training run.
- CVAT task 10 is read only after training has completed and the checkpoint has
  already been selected from task-9 validation metrics.
- Task-10 labels are review ground truth only and are permanently ineligible for
  train or validation manifests.
- The pre-label workflow must not calculate detection metrics because task 10 has
  no reviewed ground truth yet.
- The helper remains isolated from every active-model path.

## Workflow

1. Snapshot task 10 while it is empty and record its media mapping, annotation
   hash, task-9 source hash, helper hash, and rollback payload.
2. Verify the locked package maps one-to-one to the 200 CVAT frames by filename,
   width, and height.
3. Run the five-class helper at low confidence. Run official YOLO11n only for
   helper-absent COCO classes `bicycle`, `motorcycle`, and `bus`.
4. Normalize proposals, remove invalid boxes, filter low-confidence noise, and
   apply class-agnostic NMS to prevent two labels on one object.
5. Render 12 evenly distributed audit frames before any CVAT mutation.
6. Re-fetch both tasks. Refuse to write if task 9 or task 10 changed after the
   snapshot, or if the checkpoint hash changed.
7. Replace the still-empty task-10 annotation payload with proposals, verify the
   resulting semantic hash, and rollback to the empty snapshot on any mismatch.

## Review thresholds

The locked-test proposals prioritize recall but avoid unusable noise:

- `person`: 0.35
- `car`: 0.25
- `truck`: 0.25
- `forklift`: 0.20
- `reach_stacker`: 0.20
- `bicycle`: 0.30
- `motorcycle`: 0.30
- `bus`: 0.50

These thresholds are annotation-assist settings only. They are not runtime
thresholds and must never be selected using locked-test metrics.

## Safety and acceptance

- Task 9 retains the exact semantic hash captured before training.
- Task 10 is empty at snapshot and at the final pre-write guard.
- The task-10 media mapping exactly matches the locked package.
- Every written shape is a valid rectangle using a task-10 label ID.
- An apply receipt states that locked data was not used for training and that the
  helper was not activated.
- Focused tests cover filtering, mapping guards, hash guards, and payload creation.

