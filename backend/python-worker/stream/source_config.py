"""Portable camera-source configuration and lightweight ``.env`` watching."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Optional

from dotenv import dotenv_values

logger = logging.getLogger("sentriai.stream.source_config")

CAMERA_SOURCE_KEYS = {
    "GATE_CAMERA_URL": "GATE-01",
    "AREA_CAMERA_URL": "BAI-KIEM",
}
NETWORK_SCHEMES = ("rtsp://", "http://", "https://")
VIDEO_SUFFIXES = {
    ".asf",
    ".avi",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".wmv",
}


@dataclass(frozen=True)
class ConfiguredSource:
    env_key: str
    camera_id: str
    raw_value: str
    resolved_value: str
    source_kind: str


class SourceConfigError(ValueError):
    """A redacted source error safe to expose in operational logs."""

    def __init__(self, env_key: str, camera_id: str, reason: str) -> None:
        super().__init__(reason)
        self.env_key = env_key
        self.camera_id = camera_id
        self.reason = reason


SourceChangeHandler = Callable[[ConfiguredSource], Awaitable[bool]]
SourceErrorHandler = Callable[[SourceConfigError], Awaitable[None]]


def _resolved_path(value: str, repo_root: Path) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = repo_root / candidate
    return candidate.resolve()


def configured_source_roots(raw_roots: str, repo_root: Path) -> tuple[Path, ...]:
    """Resolve the configured source allowlist independently of process CWD."""
    roots: list[Path] = []
    for raw_value in str(raw_roots or "").split(os.pathsep):
        value = raw_value.strip()
        if not value:
            continue
        resolved = _resolved_path(value, repo_root)
        if resolved not in roots:
            roots.append(resolved)
    return tuple(roots)


def load_allowed_source_roots(env_path: Path, repo_root: Path) -> tuple[Path, ...]:
    """Load the stable local-source allowlist used for one worker lifetime."""
    try:
        values = dotenv_values(env_path)
    except (OSError, UnicodeError):
        values = {}
    raw_roots = str(values.get("CLIP_SOURCE_ROOTS") or os.getenv("CLIP_SOURCE_ROOTS") or "")
    roots = list(configured_source_roots(raw_roots, repo_root))
    internal_data_root = (repo_root / "backend" / "data").resolve()
    if internal_data_root not in roots:
        roots.append(internal_data_root)
    return tuple(roots)


def resolve_configured_source(
    env_key: str,
    raw_value: str,
    *,
    repo_root: Path,
    allowed_roots: tuple[Path, ...],
) -> ConfiguredSource:
    """Validate one configured source without leaking its value in errors."""
    camera_id = CAMERA_SOURCE_KEYS[env_key]
    value = str(raw_value or "").strip()
    if not value:
        raise SourceConfigError(env_key, camera_id, "camera source is empty")

    if value.lower().startswith(NETWORK_SCHEMES):
        return ConfiguredSource(env_key, camera_id, value, value, "LIVE")

    candidate = _resolved_path(value, repo_root)
    if not candidate.is_file():
        raise SourceConfigError(env_key, camera_id, "local video does not exist")
    if candidate.suffix.casefold() not in VIDEO_SUFFIXES:
        raise SourceConfigError(env_key, camera_id, "local source is not a supported video file")
    if not any(candidate == root or root in candidate.parents for root in allowed_roots):
        raise SourceConfigError(env_key, camera_id, "local video is outside CLIP_SOURCE_ROOTS")

    return ConfiguredSource(env_key, camera_id, value, str(candidate), "LOCAL_FILE")


def load_source_snapshot(
    env_path: Path,
    *,
    repo_root: Path,
    allowed_roots: Optional[tuple[Path, ...]] = None,
) -> dict[str, ConfiguredSource | SourceConfigError]:
    """Parse and validate both camera sources from one complete env snapshot."""
    try:
        values = dotenv_values(env_path)
    except (OSError, UnicodeError) as exc:
        return {
            env_key: SourceConfigError(env_key, camera_id, f"cannot read backend/.env ({type(exc).__name__})")
            for env_key, camera_id in CAMERA_SOURCE_KEYS.items()
        }

    stable_roots = allowed_roots or load_allowed_source_roots(env_path, repo_root)

    snapshot: dict[str, ConfiguredSource | SourceConfigError] = {}
    for env_key, camera_id in CAMERA_SOURCE_KEYS.items():
        raw_value = str(values.get(env_key) or os.getenv(env_key) or "")
        try:
            snapshot[env_key] = resolve_configured_source(
                env_key,
                raw_value,
                repo_root=repo_root,
                allowed_roots=stable_roots,
            )
        except SourceConfigError as exc:
            snapshot[env_key] = exc
    return snapshot


class SourceConfigWatcher:
    """Poll one env file without adding work to either inference loop."""

    def __init__(
        self,
        env_path: Path,
        repo_root: Path,
        poll_seconds: float = 1.0,
        debounce_seconds: float = 0.35,
    ) -> None:
        self.env_path = env_path.resolve()
        self.repo_root = repo_root.resolve()
        self.poll_seconds = max(0.25, float(poll_seconds))
        self.debounce_seconds = max(0.05, float(debounce_seconds))
        self._stopped = asyncio.Event()
        self._file_signature: Optional[tuple[int, int, str]] = None
        self._accepted_values: dict[str, str] = {}
        self._allowed_roots = load_allowed_source_roots(self.env_path, self.repo_root)

    def stop(self) -> None:
        self._stopped.set()

    def _signature(self) -> Optional[tuple[int, int, str]]:
        try:
            stat = self.env_path.stat()
            digest = hashlib.blake2b(self.env_path.read_bytes(), digest_size=8).hexdigest()
        except OSError:
            return None
        return stat.st_mtime_ns, stat.st_size, digest

    async def _wait(self, seconds: float) -> bool:
        try:
            await asyncio.wait_for(self._stopped.wait(), timeout=seconds)
            return True
        except asyncio.TimeoutError:
            return False

    async def run(
        self,
        on_change: SourceChangeHandler,
        on_error: Optional[SourceErrorHandler] = None,
    ) -> None:
        initial = load_source_snapshot(
            self.env_path,
            repo_root=self.repo_root,
            allowed_roots=self._allowed_roots,
        )
        for env_key, result in initial.items():
            if isinstance(result, ConfiguredSource):
                self._accepted_values[env_key] = result.resolved_value
        self._file_signature = self._signature()

        while not self._stopped.is_set():
            if await self._wait(self.poll_seconds):
                return
            signature = self._signature()
            if signature == self._file_signature:
                continue
            self._file_signature = signature
            if await self._wait(self.debounce_seconds):
                return

            snapshot = load_source_snapshot(
                self.env_path,
                repo_root=self.repo_root,
                allowed_roots=self._allowed_roots,
            )
            for env_key, result in snapshot.items():
                if isinstance(result, SourceConfigError):
                    logger.warning(
                        "[%s] %s changed but is invalid: %s; keeping current source.",
                        result.camera_id,
                        result.env_key,
                        result.reason,
                    )
                    if on_error is not None:
                        await on_error(result)
                    continue
                if self._accepted_values.get(env_key) == result.resolved_value:
                    continue

                logger.info("[%s] Detected %s change.", result.camera_id, result.env_key)
                try:
                    accepted = await on_change(result)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.error(
                        "[%s] Source switch failed (%s); keeping current source.",
                        result.camera_id,
                        type(exc).__name__,
                    )
                    accepted = False
                if accepted:
                    self._accepted_values[env_key] = result.resolved_value
