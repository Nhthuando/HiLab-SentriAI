"""Pull completed CVAT rectangles into a locked local review package."""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

import requests

from training.local_video_dataset import refresh_package_indexes
from training.v9_profile import EXPECTED_V9_CLASSES


def _raise(response: requests.Response) -> None:
    if not response.ok:
        raise RuntimeError(f"CVAT HTTP {response.status_code}: {response.text[:1000]}")


def _shape_to_yolo(shape: Mapping[str, Any], width: int, height: int) -> tuple[float, float, float, float]:
    if shape.get("type") != "rectangle":
        raise ValueError(f"unsupported CVAT shape type: {shape.get('type')!r}")
    points = shape.get("points")
    if not isinstance(points, Sequence) or isinstance(points, (str, bytes)) or len(points) != 4:
        raise ValueError("CVAT rectangle must contain four point values")
    x1, y1, x2, y2 = (float(value) for value in points)
    left, right = sorted((x1, x2))
    top, bottom = sorted((y1, y2))
    epsilon = 1e-3
    if (
        width <= 0 or height <= 0 or right <= left or bottom <= top
        or left < -epsilon or top < -epsilon or right > width + epsilon or bottom > height + epsilon
    ):
        raise ValueError("CVAT rectangle is invalid or outside its frame")
    left, top = max(0.0, left), max(0.0, top)
    right, bottom = min(float(width), right), min(float(height), bottom)
    return (
        (left + right) / (2 * width),
        (top + bottom) / (2 * height),
        (right - left) / width,
        (bottom - top) / height,
    )


def pull_reviewed_package(
    original_package: Path,
    output_directory: Path,
    *,
    task_id: int,
    base_url: str,
    username: str,
    password: str,
) -> dict[str, Any]:
    original = original_package.resolve()
    output = output_directory.resolve()
    if output.exists():
        raise FileExistsError(f"reviewed staging directory already exists: {output}")
    manifest = json.loads((original / "annotation-manifest.json").read_text(encoding="utf-8"))
    schema_version = manifest.get("schemaVersion")
    raw_classes = manifest.get("classes")
    if schema_version not in {1, 4} or not isinstance(raw_classes, list) or not raw_classes:
        raise ValueError("original review package schema/classes do not match")
    classes = tuple(str(name) for name in raw_classes)
    if schema_version == 4 and classes != EXPECTED_V9_CLASSES:
        raise ValueError("V9 review package class order does not match the canonical contract")
    frames = manifest.get("frames")
    if not isinstance(frames, list) or not frames:
        raise ValueError("original review package has no frames")

    base_url = base_url.rstrip("/")
    session = requests.Session()
    login = session.post(
        f"{base_url}/api/auth/login",
        json={"username": username, "password": password}, timeout=30,
    )
    _raise(login)
    session.headers.update({"Authorization": f"Token {login.json()['key']}"})

    task_response = session.get(f"{base_url}/api/tasks/{task_id}", timeout=30)
    jobs_response = session.get(f"{base_url}/api/jobs", params={"task_id": task_id, "page_size": 100}, timeout=30)
    meta_response = session.get(f"{base_url}/api/tasks/{task_id}/data/meta", timeout=60)
    labels_response = session.get(f"{base_url}/api/labels", params={"task_id": task_id, "page_size": 100}, timeout=30)
    annotations_response = session.get(f"{base_url}/api/tasks/{task_id}/annotations", timeout=120)
    for response in (task_response, jobs_response, meta_response, labels_response, annotations_response):
        _raise(response)
    task = task_response.json()
    jobs = jobs_response.json().get("results", [])
    if not jobs or any(str(job.get("state")) != "completed" for job in jobs):
        raise ValueError("every CVAT job must be completed before labels can be frozen")
    if int(task.get("size") or 0) != len(frames):
        raise ValueError("CVAT task frame count differs from the locked package")

    meta_frames = meta_response.json().get("frames", [])
    task_frames = {
        str(item["name"]): {"index": index, "width": int(item["width"]), "height": int(item["height"])}
        for index, item in enumerate(meta_frames)
    }
    expected_paths = {str(frame["imagePath"]) for frame in frames}
    if set(task_frames) != expected_paths:
        missing = sorted(expected_paths - set(task_frames))
        extra = sorted(set(task_frames) - expected_paths)
        raise ValueError(f"CVAT frame paths differ from the locked package; missing={missing[:1]} extra={extra[:1]}")
    label_names = {
        int(item["id"]): str(item["name"])
        for item in labels_response.json().get("results", [])
    }
    if set(classes).difference(label_names.values()):
        raise ValueError("CVAT task is missing one or more required class labels")

    annotations = annotations_response.json()
    if annotations.get("tags") or annotations.get("tracks"):
        raise ValueError("review task must contain rectangle shapes only; tags/tracks are unsupported")
    shapes_by_frame: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for shape in annotations.get("shapes", []):
        if not isinstance(shape, Mapping):
            raise ValueError("CVAT returned an invalid shape object")
        shapes_by_frame[int(shape["frame"])].append(shape)

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=str(output.parent)))
    try:
        shutil.copytree(original, temporary, dirs_exist_ok=True, ignore=shutil.ignore_patterns("*.zip"))
        box_count = 0
        duplicate_box_count = 0
        class_counts = {name: 0 for name in classes}
        for frame in frames:
            image_path = str(frame["imagePath"])
            meta = task_frames[image_path]
            rows: list[tuple[int, float, float, float, float]] = []
            unique_rows: set[tuple[int, float, float, float, float]] = set()
            for shape in shapes_by_frame.get(int(meta["index"]), []):
                label_name = label_names.get(int(shape["label_id"]))
                if label_name not in classes:
                    raise ValueError(f"CVAT shape uses an unknown class: {label_name!r}")
                center_x, center_y, width, height = _shape_to_yolo(shape, int(meta["width"]), int(meta["height"]))
                row = (classes.index(label_name), center_x, center_y, width, height)
                # CVAT can retain an accidental second copy of the exact same
                # rectangle.  Keep the reviewed object once so Ultralytics does
                # not silently mutate the frozen dataset during training.
                rounded_row = (row[0], *(round(value, 8) for value in row[1:]))
                if rounded_row in unique_rows:
                    duplicate_box_count += 1
                    continue
                unique_rows.add(rounded_row)
                rows.append(row)
                class_counts[label_name] += 1
                box_count += 1
            rows.sort()
            label_path = temporary / str(frame["labelsPath"])
            label_path.parent.mkdir(parents=True, exist_ok=True)
            label_path.write_text(
                "".join(
                    f"{class_id} {center_x:.8f} {center_y:.8f} {width:.8f} {height:.8f}\n"
                    for class_id, center_x, center_y, width, height in rows
                ),
                encoding="utf-8",
            )

        review_csv = temporary / "review.csv"
        with review_csv.open("r", newline="", encoding="utf-8-sig") as handle:
            review_rows = list(csv.DictReader(handle))
        if len(review_rows) != len(frames):
            raise ValueError("review.csv row count differs from the locked package")
        for row in review_rows:
            row["reviewStatus"] = "REVIEWED"
        with review_csv.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(review_rows[0]))
            writer.writeheader()
            writer.writerows(review_rows)
        refresh_package_indexes(temporary)
        receipt = {
            "schemaVersion": 1,
            "taskId": task_id,
            "taskName": task.get("name"),
            "taskUpdatedDate": task.get("updated_date"),
            "jobIds": [int(job["id"]) for job in jobs],
            "jobStates": [str(job["state"]) for job in jobs],
            "annotationVersion": annotations.get("version"),
            "frameCount": len(frames),
            "boxCount": box_count,
            "duplicateBoxesRemoved": duplicate_box_count,
            "classCounts": class_counts,
            "reviewStatus": "REVIEWED",
        }
        (temporary / "cvat-review-receipt.json").write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        temporary.replace(output)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return {**receipt, "directory": str(output)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--task-id", type=int, required=True)
    parser.add_argument("--base-url", default="http://localhost:8080")
    args = parser.parse_args()
    username = os.environ.get("CVAT_USERNAME", "")
    password = os.environ.get("CVAT_PASSWORD", "")
    if not username or not password:
        raise SystemExit("CVAT_USERNAME and CVAT_PASSWORD are required")
    print(json.dumps(pull_reviewed_package(
        args.package, args.output, task_id=args.task_id, base_url=args.base_url,
        username=username, password=password,
    ), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
