# BAI-KIEM V9 600-Frame Annotation-Assist Design

## Decision

Run a second annotation-assist round after the user reviewed CVAT task 9 through displayed frame 600. Freeze internal frames 0-599, fine-tune the successful 210-frame helper on all 600 corrected frames, and replace only internal frames 600-999 with newly audited proposals.

The user explicitly requested continuation of the already approved annotation-assist workflow. This document records the boundary and initialization delta; all safety rules from the 210-frame design remain in force.

## Training

- Use all 600 corrected native frames and every class with reviewed boxes.
- Initialize from the isolated 210-frame annotation-helper checkpoint, not from V8 and not from an active application model.
- Use a lower learning rate and a bounded 25-epoch run because this is fine-tuning, not a fresh model.
- Keep batch 1, workers 0, no RAM cache, AMP, bounded CPU threads, and BelowNormal process priority.
- Treat validation metrics as annotation-assist diagnostics only; the frames are temporally related and are not the locked test.

## CVAT safety

- Snapshot all current task-9 annotations before training.
- Preserve frames 0-599 by semantic hash.
- Predict and replace frames 600-999 only.
- Abort if task 9 changes after the snapshot.
- Verify task 10 is empty before and after applying proposals.
- Roll back task 9 automatically if post-apply hashes differ.
- Do not activate the helper checkpoint in SentriAI.

## Proposal quality

- Generate low-threshold raw proposals sequentially with batch 1.
- Apply the established balanced review thresholds and cross-class NMS.
- Render evenly spaced samples from frames 600-999 and visually audit them before CVAT mutation.
- If the audit is noisy, tighten filtering and render again rather than uploading the noisy proposal set.

## Completion

- 600 reviewed frames and their boxes are exported and hashed.
- A new isolated helper checkpoint and metrics receipt exist.
- Frames 600-999 contain audited new proposals.
- Frames 0-599 have identical before/after semantic hashes.
- Task 10 remains empty and job 8 remains in progress from frame 600.
