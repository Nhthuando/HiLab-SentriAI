"""Verify the two uploaded V9 review tasks and write a portable receipt."""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path

import requests

from training.v9_profile import EXPECTED_V9_CLASSES


def _raise(response: requests.Response) -> None:
    if not response.ok:
        raise RuntimeError(f"CVAT HTTP {response.status_code}: {response.text[:1000]}")


def verify(
    *, project_id: int, train_val_task_id: int, locked_task_id: int,
    base_url: str, username: str, password: str,
) -> dict:
    base_url = base_url.rstrip("/")
    session = requests.Session()
    login = session.post(
        f"{base_url}/api/auth/login",
        json={"username": username, "password": password}, timeout=30,
    )
    _raise(login)
    session.headers.update({"Authorization": f"Token {login.json()['key']}"})
    labels_response = session.get(
        f"{base_url}/api/labels", params={"project_id": project_id, "page_size": 100}, timeout=30,
    )
    _raise(labels_response)
    labels = labels_response.json().get("results", [])
    label_names = {int(item["id"]): str(item["name"]) for item in labels}
    if set(label_names.values()) != set(EXPECTED_V9_CLASSES) or len(label_names) != len(EXPECTED_V9_CLASSES):
        raise ValueError("CVAT V9 project label contract mismatch")

    tasks = []
    for task_id, expected_name, expected_size, locked in (
        (train_val_task_id, "BAI-KIEM-V9-TRAIN-VAL-REVIEW", 1000, False),
        (locked_task_id, "BAI-KIEM-V9-LOCKED-BLIND", 200, True),
    ):
        task_response = session.get(f"{base_url}/api/tasks/{task_id}", timeout=30)
        annotation_response = session.get(f"{base_url}/api/tasks/{task_id}/annotations", timeout=120)
        meta_response = session.get(f"{base_url}/api/tasks/{task_id}/data/meta", timeout=120)
        jobs_response = session.get(
            f"{base_url}/api/jobs", params={"task_id": task_id, "page_size": 100}, timeout=30,
        )
        for response in (task_response, annotation_response, meta_response, jobs_response):
            _raise(response)
        task = task_response.json()
        annotations = annotation_response.json()
        meta = meta_response.json()
        jobs = jobs_response.json().get("results", [])
        if task.get("name") != expected_name or int(task.get("size") or 0) != expected_size:
            raise ValueError(f"CVAT task {task_id} name/size mismatch")
        if annotations.get("tags") or annotations.get("tracks"):
            raise ValueError(f"CVAT task {task_id} contains unsupported tags/tracks")
        shapes = annotations.get("shapes", [])
        if locked and shapes:
            raise ValueError("Locked-blind CVAT task must contain zero shapes")
        class_counts = Counter(label_names[int(shape["label_id"])] for shape in shapes)
        frames = meta.get("frames", [])
        if len(frames) != expected_size:
            raise ValueError(f"CVAT task {task_id} metadata frame count mismatch")
        resolutions = Counter(f"{int(frame['width'])}x{int(frame['height'])}" for frame in frames)
        tasks.append({
            "taskId": task_id, "taskName": expected_name, "frameCount": expected_size,
            "lockedBlind": locked, "proposalCount": len(shapes),
            "proposalClassCounts": dict(sorted(class_counts.items())),
            "resolutions": dict(sorted(resolutions.items())),
            "taskUrl": f"{base_url}/tasks/{task_id}",
            "jobs": [
                {
                    "jobId": int(job["id"]), "state": str(job["state"]), "stage": str(job["stage"]),
                    "jobUrl": f"{base_url}/tasks/{task_id}/jobs/{int(job['id'])}",
                }
                for job in jobs
            ],
        })
    return {
        "schemaVersion": 1, "profile": "BAIKIEM_V9_UNIFIED", "projectId": project_id,
        "projectUrl": f"{base_url}/projects/{project_id}",
        "classes": list(EXPECTED_V9_CLASSES), "tasks": tasks,
        "reviewStatus": "PENDING_REVIEW", "trainingStarted": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--train-val-task-id", type=int, required=True)
    parser.add_argument("--locked-task-id", type=int, required=True)
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    username = os.environ.get("CVAT_USERNAME", "")
    password = os.environ.get("CVAT_PASSWORD", "")
    if not username or not password:
        raise SystemExit("CVAT_USERNAME and CVAT_PASSWORD are required")
    result = verify(
        project_id=args.project_id, train_val_task_id=args.train_val_task_id,
        locked_task_id=args.locked_task_id, base_url=args.base_url,
        username=username, password=password,
    )
    if args.receipt is not None:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
