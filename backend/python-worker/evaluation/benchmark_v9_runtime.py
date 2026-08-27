"""Benchmark the final V9 checkpoint through the real one-pass Area pipeline."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import torch

from training.benchmark_models import _area_cell


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(
    video: Path,
    base_model: Path,
    checkpoint: Path,
    labels: Path,
    output: Path,
    *,
    image_sizes: list[int],
    frames: int,
    warmup: int,
) -> dict[str, Any]:
    video = video.resolve()
    base_model = base_model.resolve()
    checkpoint = checkpoint.resolve()
    labels = labels.resolve()
    if not video.is_file() or not base_model.is_file() or not checkpoint.is_file() or not labels.is_file():
        raise FileNotFoundError("one or more V9 runtime benchmark inputs are missing")
    label_map = json.loads(labels.read_text(encoding="utf-8"))
    if not isinstance(label_map, dict) or not label_map:
        raise ValueError("V9 label map is invalid")
    rows = []
    for image_size in image_sizes:
        row = _area_cell(
            video, base_model, imgsz=image_size, roi_enabled=False,
            measured_frames=frames, warmup_frames=warmup, half=True,
            runtime_mode="UNIFIED", unified_artifact=checkpoint,
            unified_label_map={str(key): str(value) for key, value in label_map.items()},
        )
        rows.append({"imageSize": image_size, **row})
    report = {
        "schemaVersion": 1,
        "runtimeMode": "UNIFIED",
        "sourceFile": video.name,
        "artifactPath": str(checkpoint),
        "artifactSha256": _sha256(checkpoint),
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "targetEndToEndFps": 8.0,
        "rows": rows,
    }
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--base-model", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--imgsz", type=int, nargs="+", default=[768, 896])
    parser.add_argument("--frames", type=int, default=80)
    parser.add_argument("--warmup", type=int, default=10)
    args = parser.parse_args()
    print(json.dumps(run(
        args.video, args.base_model, args.checkpoint, args.labels, args.output,
        image_sizes=args.imgsz, frames=args.frames, warmup=args.warmup,
    ), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
