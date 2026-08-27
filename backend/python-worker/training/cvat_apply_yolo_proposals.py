"""Replace one CVAT task's annotations with a local YOLO proposal package."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import requests


def _raise(response: requests.Response) -> None:
    if not response.ok:
        raise RuntimeError(f"CVAT HTTP {response.status_code}: {response.text[:1000]}")


def run(
    package: Path, *, task_id: int, base_url: str, username: str, password: str,
    minimum_confidence: float = 0.15,
) -> dict:
    package = package.resolve()
    manifest = json.loads((package / "annotation-manifest.json").read_text(encoding="utf-8"))
    classes = manifest.get("classes")
    if not isinstance(classes, list) or not classes:
        raise ValueError("Annotation package class contract is missing")
    if not 0.0 <= minimum_confidence <= 1.0:
        raise ValueError("minimum_confidence must be between zero and one")
    details_path = package / "proposal-details.json"
    proposal_details = json.loads(details_path.read_text(encoding="utf-8")) if details_path.is_file() else None
    if proposal_details is not None and not isinstance(proposal_details, dict):
        raise ValueError("proposal-details.json must contain a frame mapping")
    session = requests.Session()
    login = session.post(
        f"{base_url.rstrip('/')}/api/auth/login",
        json={"username": username, "password": password}, timeout=30,
    )
    _raise(login)
    session.headers.update({"Authorization": f"Token {login.json()['key']}"})
    base_url = base_url.rstrip("/")

    meta_response = session.get(f"{base_url}/api/tasks/{task_id}/data/meta", timeout=30)
    _raise(meta_response)
    meta = meta_response.json()
    task_frames = {
        str(frame["name"]): {
            "frame": index,
            "width": int(frame["width"]),
            "height": int(frame["height"]),
        }
        for index, frame in enumerate(meta.get("frames", []))
    }
    label_response = session.get(
        f"{base_url}/api/labels", params={"task_id": task_id, "page_size": 100}, timeout=30,
    )
    _raise(label_response)
    label_ids = {str(item["name"]): int(item["id"]) for item in label_response.json().get("results", [])}
    missing_labels = set(classes).difference(label_ids)
    if missing_labels:
        raise ValueError(f"CVAT task is missing label: {sorted(missing_labels)[0]}")

    shapes: list[dict] = []
    missing_frames: list[str] = []
    for frame in manifest.get("frames", []):
        image_path = str(frame["imagePath"])
        task_frame = task_frames.get(image_path)
        if task_frame is None:
            missing_frames.append(image_path)
            continue
        width = task_frame["width"]
        height = task_frame["height"]
        detail_items = proposal_details.get(str(frame["frameId"]), []) if proposal_details is not None else None
        if detail_items is not None:
            if not isinstance(detail_items, list):
                raise ValueError(f"Invalid proposal details for {frame['frameId']}")
            for item in detail_items:
                class_name = str(item.get("class"))
                confidence = float(item.get("confidence", 0.0))
                bbox = item.get("bbox")
                if class_name not in classes or confidence < minimum_confidence:
                    continue
                if not isinstance(bbox, list) or len(bbox) != 4:
                    raise ValueError(f"Invalid proposal bbox for {frame['frameId']}")
                x1, y1, x2, y2 = (float(value) for value in bbox)
                x1, y1 = max(0.0, x1), max(0.0, y1)
                x2, y2 = min(1.0, x2), min(1.0, y2)
                if x2 <= x1 or y2 <= y1:
                    continue
                shapes.append({
                    "type": "rectangle", "frame": task_frame["frame"],
                    "label_id": label_ids[class_name],
                    "points": [x1 * width, y1 * height, x2 * width, y2 * height],
                    "occluded": False, "outside": False, "z_order": 0,
                    "rotation": 0.0, "attributes": [], "source": "auto",
                })
            continue
        for raw_line in (package / str(frame["labelsPath"])).read_text(encoding="utf-8").splitlines():
            fields = raw_line.split()
            if not fields:
                continue
            if len(fields) != 5:
                raise ValueError(f"Invalid YOLO proposal row for {frame['frameId']}")
            class_id = int(fields[0])
            center_x, center_y, box_width, box_height = (float(value) for value in fields[1:])
            x1 = max(0.0, (center_x - box_width / 2) * width)
            y1 = max(0.0, (center_y - box_height / 2) * height)
            x2 = min(float(width), (center_x + box_width / 2) * width)
            y2 = min(float(height), (center_y + box_height / 2) * height)
            shapes.append({
                "type": "rectangle",
                "frame": task_frame["frame"],
                "label_id": label_ids[str(classes[class_id])],
                "points": [x1, y1, x2, y2],
                "occluded": False,
                "outside": False,
                "z_order": 0,
                "rotation": 0.0,
                "attributes": [],
                "source": "auto",
            })
    if missing_frames:
        raise ValueError(f"CVAT task is missing package frame: {missing_frames[0]}")
    replaced = session.put(
        f"{base_url}/api/tasks/{task_id}/annotations/",
        json={"version": 0, "tags": [], "shapes": shapes, "tracks": []},
        timeout=120,
    )
    _raise(replaced)
    return {
        "taskId": task_id, "frameCount": len(task_frames), "proposalCount": len(shapes),
        "minimumConfidence": minimum_confidence if proposal_details is not None else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--task-id", type=int, required=True)
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--minimum-confidence", type=float, default=0.15)
    args = parser.parse_args()
    username = os.environ.get("CVAT_USERNAME", "")
    password = os.environ.get("CVAT_PASSWORD", "")
    if not username or not password:
        raise SystemExit("CVAT_USERNAME and CVAT_PASSWORD are required")
    result = run(
        args.package, task_id=args.task_id, base_url=args.base_url,
        username=username, password=password, minimum_confidence=args.minimum_confidence,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
