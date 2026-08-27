# BAI-KIEM Golden Evaluation

**Status: BLOCKED**

- Total candidate frames: 26
- Pending: 26
- Annotated: 0
- Negative: 0
- Evaluatable: 0
- Evaluation split: `test`

## Blockers

- annotationStatus contains 26 PENDING frame(s)

## Class accuracy

Precision, recall, AP50, small/far recall, truck/reach-stacker confusion, static-container false detections, and false alerts per minute are **BLOCKED/NOT EVALUATED**. No reviewed ground truth exists.

## Acceptance gates

**Overall: BLOCKED**

- `reachStackerPrecision`: **BLOCKED**; required `>= 0.90`; reach-stacker precision is undefined.
- `reachStackerRecall`: **BLOCKED**; required `>= 0.85`; reach-stacker recall is undefined.
- `truckAsReachStackerRate`: **BLOCKED**; required `< 0.05`; truck ground truth is unavailable.
- `falseAlertsPerMinuteImproved`: **BLOCKED**; current complete-review rate and a baseline rate are both required.
- `farObjectRecallImproved`: **BLOCKED**; current far-object recall and a baseline recall are both required.

The manifest contains 65 frames overall; this report intentionally defaults to the leakage-safe `test` split (26 frames). Calibration and validation records do not affect the final acceptance gate.

## End-to-end Area performance baseline

Command (local assets only):

```powershell
cd backend/python-worker
& '.venv/Scripts/python.exe' training/benchmark_models.py --area-video 'D:\video_test\KiemHoa-Hik (1).mp4' --output '..\data\training\benchmarks\20260822-bai-kiem-area-baseline.json' --matrix-imgsz 640 --matrix-imgsz 896 --matrix-imgsz 960 --matrix-frames 40 --matrix-warmup 5
```

Hardware: Windows 11, NVIDIA GeForce RTX 3050 Laptop GPU 4 GB, PyTorch `2.6.0+cu124`, CUDA available. Timing starts before the first measured frame read/decode/resize and ends after the production `AreaPipeline.publish_result` path. Each cell performs sequential decode, resize to 1280×720, YOLO11 ByteTrack, registry filtering, real `ZoneChecker` lifecycle evaluation, circular buffering, JPEG/base64 feed serialization, and feed/event dispatch to injected no-write sinks. Every cell emitted 45 warmup/measured feed payloads plus one untimed deterministic event-path probe. The probe produced two Area events, one alert, one create call, and one close call. The reported counts come from an injected in-memory adapter with no external client configured; there is no hard-coded production persistence counter.

| Model/runtime | imgsz | ROI | E2E FPS | Detector p95 ms | ROI p95 ms | Peak CUDA allocated/reserved MiB | ≥8 FPS |
| --- | ---: | --- | ---: | ---: | ---: | ---: | --- |
| YOLO11n PyTorch FP16 | 640 | off | 20.277 | 17.449 | 0.010 | 44.1 / 66.0 | PASS |
| YOLO11n PyTorch FP16 | 640 | on, every 3rd frame | 13.333 | 106.459 | 90.805 | 48.8 / 66.0 | PASS |
| YOLO11n PyTorch FP16 | 896 | off | 20.716 | 24.714 | 0.013 | 52.1 / 66.0 | PASS |
| YOLO11n PyTorch FP16 | 896 | on, every 3rd frame | 12.502 | 113.886 | 96.955 | 52.5 / 68.0 | PASS |
| YOLO11n PyTorch FP16 | 960 | off | 20.361 | 28.394 | 0.007 | 54.8 / 70.0 | PASS |
| YOLO11n PyTorch FP16 | 960 | on, every 3rd frame | 12.676 | 126.512 | 105.933 | 55.2 / 70.0 | PASS |

The highest measured ROI-on throughput is YOLO11n at imgsz 640 (13.333 E2E FPS). No production configuration is selected from throughput alone: the required recall comparison among 640/896/960 remains blocked until the pending test frames are reviewed.

## Missing local assets

- YOLO11s PyTorch FP16: `BLOCKED_MISSING_LOCAL_ASSET`; no `yolo11s.pt` was present. The benchmark did not pass a missing model name to Ultralytics and did not download it.
- YOLO11n/YOLO11s TensorRT FP16: `BLOCKED_MISSING_LOCAL_ASSET`; no local `.engine` was present. No export or TensorRT dependency installation was attempted.
- The complete machine-readable matrix is local at `backend/data/training/benchmarks/20260822-bai-kiem-area-baseline.json` (runtime data is gitignored).

## Acceptance boundary

Performance target `Area end-to-end >= 8 FPS`: **PASS for all six locally measurable YOLO11n cells**. Precision/recall/AP50, PR/threshold calibration, small/far recall, truck→reach-stacker confusion, static-container false detections, false alerts/minute, and any accuracy regression decision: **BLOCKED/NOT EVALUATED** because all 26 test frames remain `PENDING`.
