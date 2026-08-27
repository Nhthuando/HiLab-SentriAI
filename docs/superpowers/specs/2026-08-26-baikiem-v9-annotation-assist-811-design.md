# BAI-KIEM V9 811-Frame Annotation-Assist Design

## Decision

Use internal CVAT frames 0-810 as the reviewed training prefix and predict frames 811-999. The user also propagated 41 manual `car` rectangles through frames 811-850 without fully reviewing those frames. Those 41 rectangles are protected, excluded from training, and retained during proposal replacement.

## Accuracy check

- Evaluate the 600-frame helper on the new 811-frame dataset validation split before fine-tuning.
- Fine-tune from the isolated 600-frame helper for at most 15 epochs with early stopping.
- Record before/after precision, recall, mAP50, and mAP50-95 on the exact same validation split.
- If the checkpoint does not improve the diagnostic fitness, do not use a worse final epoch; Ultralytics `best.pt` remains authoritative.

## Data and mutation boundary

- Train/validate on frames 0-810 only.
- Predict frames 811-999 only.
- Preserve all shapes on frames 0-810 by semantic hash.
- Preserve every `source=manual` shape on frames 811-999 by a separate semantic hash.
- Replace only suffix `source=auto` shapes.
- Suppress a new proposal when it overlaps a protected manual rectangle on the same frame.
- Keep task 10 empty and never activate the annotation helper.

## Resource limits

- One process, batch 1, workers 0, no RAM cache, AMP, bounded native threads, BelowNormal priority.
- Stop after at most 15 epochs with patience 5.
- Run predictions sequentially and visually audit evenly spaced remaining frames before CVAT mutation.

