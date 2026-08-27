# BAI-KIEM local-video annotation contract

## Prepared dataset

- Review directory: `backend/data/training/annotation/baikiem-local-v1-review`
- CVAT import ZIP: `backend/data/training/annotation/baikiem-local-v1-review/baikiem-local-v1-cvat.zip`
- Frames: 943 (`train`: 414, `val`: 225, `test`: 304)
- Sources: 16 locked source IDs
- Approximate unpacked size: 198 MiB
- Status: `PENDING_REVIEW`; proposal boxes are annotation assistance only and must not be used as training truth.

The locked positive test source is `KiemHoa-Hik (2)_fastseek.mp4`. The locked cross-camera negative test source is `output_test.mp4`. Neither source may be moved into train or validation.

## Exact class IDs

| ID | Class | Review meaning |
|---:|---|---|
| 0 | `person` | A visible person |
| 1 | `bicycle` | A bicycle |
| 2 | `car` | A passenger car |
| 3 | `motorcycle` | A motorcycle |
| 4 | `truck` | A road truck; never a reach stacker or warehouse forklift |
| 5 | `reach_stacker` | Container-handling reach stacker, including its boom/spreader in one consistent whole-machine box |
| 6 | `forklift` | Warehouse/counterbalance forklift; never a reach stacker or truck |

Do not rename classes, change their order, rename images, or move images between subsets.

## Import into local CVAT

The local CVAT v2.71.0 environment is installed at `.local/cvat` and available at `http://localhost:8080`. Local credentials and safe start/stop commands are stored in `.local/CVAT-README.txt` (the whole `.local` directory is ignored by Git).

The package has already been imported as project `BAI-KIEM local v1`:

- task `train` / ID 2: 414 frames
- task `val` / ID 3: 225 frames
- task `test` / ID 4: 304 frames

The following steps are retained as the reproducible re-import procedure:

1. Open the locally installed CVAT and create a project named `BAI-KIEM local v1`.
2. Use **Project → Actions → Import dataset**.
3. Select **Ultralytics YOLO Detection** and upload `baikiem-local-v1-cvat.zip`.
4. Let CVAT create tasks for the `train`, `val`, and `test` subsets. Keep those subset names unchanged.

The package follows CVAT's Ultralytics layout (`data.yaml`, split text files, `images/<split>`, and `labels/<split>`). It stays on the local machine; do not upload these private frames to Roboflow or another hosted annotation service.

## Mandatory review rules

Review every one of the 943 frames, including frames that intentionally contain no boxes.

- Fix every box so it tightly and consistently covers the visible object.
- Add every missing relevant object, even when the proposal model emitted nothing.
- Delete false `reach_stacker` boxes in `output_test`, the June hard-negative clips, and indoor forklift clips.
- In the KiemHoa videos, label the container reach stacker as `reach_stacker`; include the boom/spreader consistently as part of the machine box.
- Label indoor counterbalance forklifts as `forklift`, not `truck` and not `reach_stacker`.
- Keep road trucks as `truck`.
- Review `person`, `bicycle`, `car`, `motorcycle`, and `truck` too. A frame with no relevant object must remain an empty label file.
- Do not copy boxes from an adjacent frame without checking the current frame. Video blur, occlusion, scale, and partial exits must be reviewed frame by frame.

Mark each CVAT job complete only after all frames in that job have been checked.

## Export and finalization

1. Export the completed project as **Ultralytics YOLO Detection**, including images.
2. Keep the original subset names and filenames.
3. Return the exported ZIP to the project workspace and report its path.

The finalizer will then overlay the reviewed labels on a clean copy of the original package, mark each reviewed frame explicitly, and reject the result if any frame is pending, an image changed, a class ID is invalid, a box is outside image bounds, or the locked splits leak into each other. Only the resulting content-addressed `LOCAL_VIDEO_REVIEWED` snapshot is allowed into training.

## Why human review is required

The initial boxes came from the current generic YOLO11n and the old reach-stacker checkpoint. They are deliberately permissive: they accelerate annotation, but they also contain known truck/reach-stacker confusion and miss indoor forklifts. Training directly on those proposals would teach the new model the same errors we are trying to remove.
