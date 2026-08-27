from __future__ import annotations

import asyncio
import subprocess
import tempfile
import unittest
import uuid
import sys
from pathlib import Path
from unittest.mock import patch

import cv2
import imageio_ffmpeg

WORKER_DIR = Path(__file__).resolve().parent.parent
if str(WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(WORKER_DIR))

from detection.event_clip_service import EventClipGenerator, EventClipResult, EventClipService


class TestLocalEventClipGenerator(unittest.TestCase):
    @staticmethod
    def _source(directory: str) -> Path:
        source = Path(directory) / "source.mp4"
        subprocess.run(
            [
                imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "testsrc=size=160x90:rate=10", "-t", "2",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return source

    def _violation(self, source: Path) -> dict[str, object]:
        return {
            "id": str(uuid.uuid4()),
            "source_ref": str(source),
            "source_position_seconds": 0.0,
        }

    def test_local_clip_is_not_created_until_generate_is_called(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self._source(directory)
            clips = Path(directory) / "clips"
            EventClipGenerator(clips, [directory])
            self.assertEqual(list(clips.glob("area_*.mp4")), [])
            self.assertTrue(source.exists())

    def test_local_generate_writes_one_browser_mp4_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self._source(directory)
            clips = Path(directory) / "clips"
            generator = EventClipGenerator(clips, [directory], duration_seconds=1.0)
            result = asyncio.run(generator.generate_local(self._violation(source)))
            self.assertEqual(result.status, "READY")
            output = clips / str(result.clip_path)
            self.assertTrue(output.exists())
            capture = cv2.VideoCapture(str(output))
            self.assertTrue(capture.isOpened())
            ok, _frame = capture.read()
            capture.release()
            self.assertTrue(ok)
            self.assertEqual(list(clips.glob("*.tmp.mp4")), [])


class TestEventClipCoordinator(unittest.TestCase):
    _source = staticmethod(TestLocalEventClipGenerator._source)

    def _violation(self, source: Path) -> dict[str, object]:
        return {
            "id": str(uuid.uuid4()),
            "source_ref": str(source),
            "source_position_seconds": 0.0,
        }

    def test_double_click_shares_one_generation_job(self):
        async def scenario():
            violation_id = str(uuid.uuid4())
            record: dict[str, object] = {
                "id": violation_id,
                "camera_id": "BAI-KIEM",
                "source_kind": "LOCAL_FILE",
                "clip_status": "NOT_REQUESTED",
                "clip_path": None,
                "clip_error": None,
            }
            generation_started = asyncio.Event()
            release_generation = asyncio.Event()

            class SlowGenerator:
                def __init__(self, clips_dir: Path):
                    self.clips_dir = clips_dir
                    self.calls = 0

                async def generate_local(self, _record):
                    self.calls += 1
                    generation_started.set()
                    await release_generation.wait()
                    return EventClipResult("READY", clip_path=f"area_{violation_id}.mp4")

            async def get_record(_violation_id):
                return dict(record)

            async def claim(_violation_id):
                if record["clip_status"] not in {"NOT_REQUESTED", "FAILED"}:
                    return None
                record["clip_status"] = "QUEUED"
                return dict(record)

            async def generating(_violation_id):
                record["clip_status"] = "GENERATING"
                return dict(record)

            async def ready(_violation_id, clip_path):
                record["clip_status"] = "READY"
                record["clip_path"] = clip_path
                return dict(record)

            async def failed(_violation_id, status, error):
                record["clip_status"] = status
                record["clip_error"] = error
                return dict(record)

            with tempfile.TemporaryDirectory() as directory:
                generator = SlowGenerator(Path(directory))
                service = EventClipService("BAI-KIEM", generator)  # type: ignore[arg-type]
                with (
                    patch("detection.event_clip_service.get_zone_violation", side_effect=get_record),
                    patch("detection.event_clip_service.claim_violation_clip", side_effect=claim),
                    patch("detection.event_clip_service.mark_violation_clip_generating", side_effect=generating),
                    patch("detection.event_clip_service.mark_violation_clip_ready", side_effect=ready),
                    patch("detection.event_clip_service.mark_violation_clip_failed", side_effect=failed),
                ):
                    first, second = await asyncio.gather(
                        service.request(violation_id),
                        service.request(violation_id),
                    )
                    await asyncio.wait_for(generation_started.wait(), timeout=1)
                    self.assertIn(first["status"], {"QUEUED", "GENERATING"})
                    self.assertIn(second["status"], {"QUEUED", "GENERATING"})
                    self.assertEqual(generator.calls, 1)
                    release_generation.set()
                    await asyncio.wait_for(service._queue.join(), timeout=1)
                    self.assertEqual(record["clip_status"], "READY")
                    await service.stop()

        asyncio.run(scenario())

    def test_repeat_generate_reuses_existing_clip(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self._source(directory)
            clips = Path(directory) / "clips"
            generator = EventClipGenerator(clips, [directory], duration_seconds=1.0)
            violation = self._violation(source)
            first = asyncio.run(generator.generate_local(violation))
            with patch.object(generator, "_encode_local", wraps=generator._encode_local) as encode:
                second = asyncio.run(generator.generate_local(violation))
            self.assertEqual(first, second)
            encode.assert_not_called()

    def test_source_outside_allowed_roots_is_rejected(self):
        with tempfile.TemporaryDirectory() as source_directory, tempfile.TemporaryDirectory() as allowed_directory:
            source = self._source(source_directory)
            generator = EventClipGenerator(Path(allowed_directory) / "clips", [allowed_directory])
            result = asyncio.run(generator.generate_local(self._violation(source)))
            self.assertEqual(result.status, "FAILED")
            self.assertIn("allowed roots", result.error or "")

    def test_missing_source_returns_unavailable_without_partial_file(self):
        with tempfile.TemporaryDirectory() as directory:
            clips = Path(directory) / "clips"
            generator = EventClipGenerator(clips, [directory])
            result = asyncio.run(generator.generate_local(self._violation(Path(directory) / "missing.mp4")))
            self.assertEqual(result.status, "FAILED")
            self.assertEqual(list(clips.glob("*.tmp.mp4")), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
