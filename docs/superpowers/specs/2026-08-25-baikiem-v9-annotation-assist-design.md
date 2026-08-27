# BAI-KIEM V9 210-Frame Annotation-Assist Design

## Purpose

Use the 210 frames already corrected by the user as a small, temporary teaching set. Train a helper YOLO11n model from the official pretrained weights, then replace only the machine-generated annotations on CVAT task 9 frames 210-999 so the remaining review is substantially faster.

This helper is not the final V9 model, is not evaluated on or trained with the locked task, and must never be activated in the running application.

## Safety boundary

- CVAT project 2, task 9, job 8 is the only mutable remote object.
- Frames 0-209 are the reviewed prefix and must remain byte-for-byte equivalent at the CVAT annotation-object level.
- Frames 210-999 may be replaced with new auto annotations.
- Task 10/job 9 is locked and read-only; it must contain zero annotations before and after the operation.
- Snapshot the complete task-9 annotations and task metadata before training or mutation.
- Before applying predictions, compare the live reviewed-prefix hash and annotation version with the snapshot. Abort if the user edited the task during the run.
- After applying predictions, fetch annotations again and prove the reviewed-prefix hash is unchanged. Persist a rollback payload and an audit receipt.

## Dataset and labels

- Read native 2592x1520 images from the existing task-9 annotation package; do not decode or duplicate the source videos again.
- Export frames 0-209 only.
- Train every canonical class that has at least one reviewed rectangle in the prefix. Classes absent from these frames are not learned from fabricated negatives.
- Reject unsupported shapes, unknown labels, invalid boxes, or duplicate frame mappings.
- Split the reviewed prefix deterministically into train and validation partitions while keeping source leakage explicitly documented. These metrics are diagnostic only because all 210 frames came from one source.

## Training profile

- Initialize from `yolo11n.pt`, not from V8 and not from a prior V9 candidate.
- Run one low-resource process: CUDA when available, batch 1, workers 0, host/OpenCV/Torch threads limited, no RAM cache, AMP enabled, and a bounded epoch/patience budget.
- Store the helper checkpoint, arguments, class map, dataset hash, and metrics under ignored training artifacts.
- Do not copy the helper checkpoint into any active-model path.

## Proposal generation

- Predict frames 210-999 only with the helper model.
- Apply class-agnostic NMS so one vehicle is not proposed twice under two helper classes.
- Keep conservative high-confidence base-model proposals only for canonical classes absent from the reviewed helper dataset (for example bus/bicycle/motorcycle), using the existing proposal-details file. Never propose `container_truck`; the product maps loaded and unloaded trucks to `truck`.
- Mark all generated rectangles as `source=auto`.

## Completion criteria

- A recoverable, hashed snapshot exists.
- The helper dataset contains exactly 210 native frames and all reviewed prefix boxes.
- Training completes without activating a model.
- Task 9 frames 210-999 receive new proposals.
- Task 9 frames 0-209 are unchanged after canonical hashing.
- Task 10 remains empty.
- A receipt reports class counts, helper metrics, prediction counts, hashes, and the CVAT resume URL.

