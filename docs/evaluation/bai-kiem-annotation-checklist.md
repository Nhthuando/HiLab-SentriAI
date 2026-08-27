# BAI-KIEM Golden Set — Annotation Checklist

## Ground-truth gate

The extraction tool creates candidate images with `annotationStatus: PENDING`; it never invents boxes or negative labels. A frame is excluded from class-accuracy evaluation until a reviewer changes it to `ANNOTATED` with a YOLO label file, or explicitly marks it `NEGATIVE` after inspecting the whole frame.

Local artifact directory: `backend/data/evaluation/bai-kiem-golden-v1/` (gitignored). Validate it with:

```powershell
cd backend/python-worker
& '.venv/Scripts/python.exe' -m evaluation.golden_dataset validate ../../backend/data/evaluation/bai-kiem-golden-v1/golden-manifest.json
```

Extraction evidence on 2026-08-22: the sequential 10-second pass requested 60 interval timestamps plus five additional imaging-hard-case timestamps (`5000`, `115000`, `125000`, `525000`, and `595000` ms). Global SHA-256 deduplication and dHash deduplication within a two-second adjacency window retained all 65 byte-unique, time-separated candidates and decoded 14,876 source frames. Limiting perceptual rejection to adjacent candidates prevents a coarse full-frame dHash collision from deleting small/far-object changes several seconds apart. All five hard-case timestamps are present. The contiguous 120-second time blocks assign 14 frames to `calibration`, 25 to `validation`, and 26 to `test`, with no time block crossing a split. All 65 records are `PENDING`; therefore 0 records are currently evaluatable. The manifest contains no absolute path, and the local artifact has both `images/` and empty `labels/` directories ready for review.

## Canonical classes

- `person`: visible people, including partially occluded people when a defensible body extent can be boxed.
- `bicycle`, `car`, `motorcycle`, `bus`, `truck`: use the corresponding COCO meaning. A generic rigid or articulated road truck remains `truck`.
- `reach_stacker`: a reach stacker whose telescopic boom/spreader or overall machine geometry supports this exact class. Do not relabel a truck based on aspect ratio.
- `container_truck`: a tractor/truck visibly carrying or configured with a shipping-container chassis. Do not use this class for a generic truck.
- `forklift`: a forklift with mast/forks; do not merge it with `reach_stacker`.
- `mobile_crane`: a self-propelled mobile crane; do not merge it with reach stackers or fixed cranes.
- `shipping_container`: a static freight container. This is not a vehicle. Its presence is especially important on designated negative/hard-background frames, but it is annotated only when this class is in the evaluation contract.

## Box and visibility policy

- Draw one tight axis-aligned box around the visible extent of each target object; exclude cast shadows.
- For truncation at the image edge, box only the visible extent and add the `partial` tag in review notes.
- For occlusion, box the inferred full extent only when it is unambiguous; otherwise box the visible extent and tag `occluded`.
- Do not annotate reflections, monitor imagery, posters, or objects whose class cannot be distinguished.
- Tag a box `small` when normalized box area is below 1%. Tag a frame/object `far` when distance/perspective makes the object materially harder even if its area is at least 1%.
- Mark genuinely unresolvable regions as ignore regions in the review sidecar. Predictions overlapping ignore regions must not become false positives.

## Required hard cases and negatives

- Include near and far reach stackers, ordinary trucks, container trucks, static shipping containers, empty yard, poles, roofs, cranes/equipment, blur/compression, rain, and different lighting where the local source actually contains them.
- A `NEGATIVE` frame means no target class instance is present anywhere outside an ignore region. Static-container-only frames are negatives for vehicle classes, not automatically negatives if `shipping_container` itself is evaluated.
- Maintain 20–30% reviewed negative frames. Do not manufacture this ratio by reclassifying uncertain frames.
- Never move a golden frame into training. Source-video/time-block splits must remain separated from train material.

## Truck versus reach-stacker review

1. Require visible class evidence, not a wide box or low-confidence detector suggestion.
2. If the machine identity remains uncertain, mark the region ignore/needs-adjudication; do not guess.
3. Record every overlap disagreement (`truck` prediction on `reach_stacker` ground truth and vice versa) for the confusion report.

## Double review

1. Reviewer A labels the frame without seeing model predictions.
2. Reviewer B independently checks class, box extent, small/far/partial/occluded tags, and negative status.
3. Disagreements are recorded and adjudicated by a third pass; never silently overwrite the first decision.
4. Re-run manifest validation, verify every `ANNOTATED` record has a label file, and review every `NEGATIVE` record at full resolution.
5. Only after zero `PENDING` records remain may precision, recall, confusion, or false-positive acceptance be reported as evaluated.
