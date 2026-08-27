"""Create a CVAT review task from a portable local-video annotation package."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
import zipfile
from pathlib import Path, PurePosixPath

import requests

from training.v9_profile import EXPECTED_V9_CLASSES


def _raise(response: requests.Response) -> None:
    if response.ok:
        return
    detail = response.text[:1000]
    raise RuntimeError(f"CVAT HTTP {response.status_code}: {detail}")


def _wait(session: requests.Session, base_url: str, request_id: str, timeout_seconds: int) -> dict:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        response = session.get(f"{base_url}/api/requests/{request_id}", timeout=30)
        _raise(response)
        payload = response.json()
        state = str(payload.get("status") or payload.get("state") or "").casefold()
        if state in {"finished", "completed"}:
            return payload
        if state in {"failed", "canceled", "cancelled"}:
            raise RuntimeError(f"CVAT request {request_id} failed: {json.dumps(payload, ensure_ascii=False)}")
        time.sleep(2)
    raise TimeoutError(f"CVAT request {request_id} did not finish within {timeout_seconds}s")


def _authenticated_session(base_url: str, username: str, password: str) -> requests.Session:
    session = requests.Session()
    login = session.post(
        f"{base_url.rstrip('/')}/api/auth/login",
        json={"username": username, "password": password},
        timeout=30,
    )
    _raise(login)
    token = login.json().get("key")
    if not isinstance(token, str) or not token:
        raise RuntimeError("CVAT login did not return a token")
    session.headers.update({"Authorization": f"Token {token}"})
    return session


def _project_label_names(session: requests.Session, base_url: str, project_id: int) -> tuple[str, ...]:
    response = session.get(
        f"{base_url.rstrip('/')}/api/labels",
        params={"project_id": project_id, "page_size": 100}, timeout=30,
    )
    _raise(response)
    return tuple(str(item["name"]) for item in response.json().get("results", []))


def ensure_v9_project(
    *, base_url: str, username: str, password: str,
    project_name: str = "BAI-KIEM V9 Unified Multi-Class",
) -> dict:
    """Create or reuse one project whose labels exactly match V9 canonical names."""
    base_url = base_url.rstrip("/")
    session = _authenticated_session(base_url, username, password)
    response = session.get(f"{base_url}/api/projects", params={"page_size": 100}, timeout=30)
    _raise(response)
    matching = [item for item in response.json().get("results", []) if item.get("name") == project_name]
    if len(matching) > 1:
        raise RuntimeError(f"Multiple CVAT projects share the name {project_name!r}")
    created = False
    if matching:
        project_id = int(matching[0]["id"])
    else:
        palette = ["#33B5E5", "#AA66CC", "#FFBB33", "#00C851", "#FF8800",
                   "#2BBBAD", "#4285F4", "#9C27B0", "#009688", "#795548"]
        created_response = session.post(
            f"{base_url}/api/projects",
            json={
                "name": project_name,
                "labels": [
                    {"name": name, "color": palette[index], "type": "rectangle", "attributes": []}
                    for index, name in enumerate(EXPECTED_V9_CLASSES)
                ],
            }, timeout=30,
        )
        _raise(created_response)
        project_id = int(created_response.json()["id"])
        created = True
    actual = _project_label_names(session, base_url, project_id)
    if set(actual) != set(EXPECTED_V9_CLASSES) or len(actual) != len(EXPECTED_V9_CLASSES):
        raise ValueError(
            f"CVAT project labels differ from V9 contract; expected={list(EXPECTED_V9_CLASSES)} actual={list(actual)}"
        )
    return {
        "projectId": project_id, "projectName": project_name,
        "created": created, "classes": list(EXPECTED_V9_CLASSES),
        "url": f"{base_url}/projects/{project_id}",
    }


def _image_archive(package: Path, destination: Path) -> None:
    image_root = package / "images"
    paths = sorted(path for path in image_root.rglob("*") if path.is_file())
    if not paths:
        raise ValueError("Annotation package contains no images")
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_STORED) as archive:
        for path in paths:
            relative = path.relative_to(package).as_posix()
            if PurePosixPath(relative).is_absolute() or ".." in PurePosixPath(relative).parts:
                raise ValueError("Annotation package contains an unsafe image path")
            archive.write(path, relative)


def run(
    package: Path,
    annotation_archive: Path,
    *,
    task_name: str,
    project_id: int,
    base_url: str,
    username: str,
    password: str,
    timeout_seconds: int,
    import_annotations: bool = True,
) -> dict:
    package = package.resolve()
    annotation_archive = annotation_archive.resolve()
    if not (package / "annotation-manifest.json").is_file() or not annotation_archive.is_file():
        raise FileNotFoundError("CVAT package/archive is missing")
    base_url = base_url.rstrip("/")
    session = _authenticated_session(base_url, username, password)

    created = session.post(
        f"{base_url}/api/tasks",
        json={"name": task_name, "project_id": project_id},
        timeout=30,
    )
    _raise(created)
    task = created.json()
    task_id = int(task["id"])
    try:
        with tempfile.TemporaryDirectory() as directory:
            data_archive = Path(directory) / "images.zip"
            _image_archive(package, data_archive)
            with data_archive.open("rb") as source:
                uploaded = session.post(
                    f"{base_url}/api/tasks/{task_id}/data/",
                    headers={
                        "Upload-Start": "true",
                        "Upload-Finish": "true",
                        "Upload-Multiple": "true",
                    },
                    data={"image_quality": "90", "sorting_method": "lexicographical"},
                    files={"client_files[0]": (data_archive.name, source, "application/zip")},
                    timeout=120,
                )
            _raise(uploaded)
            upload_payload = uploaded.json()
            upload_request_id = upload_payload.get("rq_id")
            if isinstance(upload_request_id, str) and upload_request_id:
                _wait(session, base_url, upload_request_id, timeout_seconds)

        if import_annotations:
            with annotation_archive.open("rb") as source:
                imported = session.post(
                    f"{base_url}/api/tasks/{task_id}/annotations/",
                    params={
                        "format": "Ultralytics YOLO Detection 1.0",
                        "location": "local",
                        "import_mode": "replace",
                    },
                    files={"annotation_file": (annotation_archive.name, source, "application/zip")},
                    timeout=120,
                )
            _raise(imported)
            import_request_id = None
            if imported.content:
                import_request_id = imported.json().get("rq_id")
            if isinstance(import_request_id, str) and import_request_id:
                _wait(session, base_url, import_request_id, timeout_seconds)
    except Exception:
        # Keep the task for forensic inspection. Automatic deletion could hide
        # a partially uploaded review set and is intentionally avoided.
        raise

    task_response = session.get(f"{base_url}/api/tasks/{task_id}", timeout=30)
    _raise(task_response)
    final = task_response.json()
    return {
        "taskId": task_id,
        "taskName": final.get("name"),
        "size": final.get("size"),
        "projectId": project_id,
        "url": f"{base_url}/tasks/{task_id}",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path)
    parser.add_argument("--annotations", type=Path)
    parser.add_argument("--task-name")
    parser.add_argument("--project-id", type=int)
    parser.add_argument("--project-name", default="BAI-KIEM V9 Unified Multi-Class")
    parser.add_argument("--ensure-project-only", action="store_true")
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument(
        "--skip-annotation-import",
        action="store_true",
        help="Upload only images; use cvat_apply_yolo_proposals.py for path-safe direct proposal loading.",
    )
    args = parser.parse_args()
    username = os.environ.get("CVAT_USERNAME", "")
    password = os.environ.get("CVAT_PASSWORD", "")
    if not username or not password:
        raise SystemExit("CVAT_USERNAME and CVAT_PASSWORD are required")
    project_id = args.project_id
    if project_id is None:
        project = ensure_v9_project(
            base_url=args.base_url, username=username, password=password,
            project_name=args.project_name,
        )
        if args.ensure_project_only:
            print(json.dumps(project, ensure_ascii=False, indent=2))
            return 0
        project_id = int(project["projectId"])
    if args.package is None or args.annotations is None or not args.task_name:
        raise SystemExit("--package, --annotations, and --task-name are required when uploading a task")
    result = run(
        args.package, args.annotations, task_name=args.task_name,
        project_id=project_id, base_url=args.base_url,
        username=username, password=password, timeout_seconds=args.timeout_seconds,
        import_annotations=not args.skip_annotation_import,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
