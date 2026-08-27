from __future__ import annotations

import asyncio
import logging
import tempfile
import unittest
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

WORKER_DIR = Path(__file__).resolve().parent.parent
if str(WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(WORKER_DIR))

from stream.rolling_archive import RollingArchive


class TestRollingArchive(unittest.TestCase):
    def _archive(self, directory: str, now: datetime) -> RollingArchive:
        return RollingArchive(
            camera_id="BAI-KIEM",
            source_url="rtsp://secret-user:secret-pass@example.test/live",
            archive_dir=directory,
            retention_seconds=7200,
            segment_seconds=2,
            clock=lambda: now,
        )

    @staticmethod
    def _segment(directory: str, timestamp: datetime) -> Path:
        path = Path(directory) / f"{timestamp.strftime('%Y%m%dT%H%M%S')}.ts"
        path.write_bytes(b"segment")
        return path

    def test_cleanup_removes_only_segments_older_than_7200_seconds(self):
        now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            archive = self._archive(directory, now)
            old = self._segment(directory, now - timedelta(seconds=7205))
            retained = self._segment(directory, now - timedelta(seconds=7199))
            self.assertEqual(archive.cleanup(), 1)
            self.assertFalse(old.exists())
            self.assertTrue(retained.exists())

    def test_cleanup_preserves_segments_leased_by_generation(self):
        now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            archive = self._archive(directory, now)
            leased = self._segment(directory, now - timedelta(seconds=8000))
            archive.acquire([leased])
            self.assertEqual(archive.cleanup(), 0)
            self.assertTrue(leased.exists())
            archive.release([leased])
            self.assertEqual(archive.cleanup(), 1)

    def test_segments_for_returns_ordered_covering_window(self):
        start = datetime(2026, 8, 26, 10, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            archive = self._archive(directory, start + timedelta(minutes=1))
            expected = [self._segment(directory, start + timedelta(seconds=value)) for value in (0, 2, 4, 6, 8)]
            selected = archive.segments_for(start, start + timedelta(seconds=10))
            self.assertEqual(selected, expected)

    def test_missing_window_reports_no_segments(self):
        start = datetime(2026, 8, 26, 10, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            archive = self._archive(directory, start + timedelta(minutes=1))
            self._segment(directory, start + timedelta(seconds=20))
            self.assertEqual(archive.segments_for(start, start + timedelta(seconds=10)), [])

    def test_live_url_is_redacted_from_logs_and_status(self):
        now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            archive = self._archive(directory, now)
            with self.assertLogs("sentriai.stream.rolling_archive", level=logging.INFO) as captured:
                async def scenario():
                    async def fake_run():
                        logging.getLogger("sentriai.stream.rolling_archive").info(
                            "[%s] Starting compressed rolling archive (source URL redacted).",
                            archive.camera_id,
                        )
                    archive._run = fake_run  # type: ignore[method-assign]
                    archive.start()
                    await asyncio.sleep(0)
                    await archive.stop()

                asyncio.run(scenario())
            rendered = " ".join(captured.output) + repr(archive.status())
            self.assertNotIn("secret-user", rendered)
            self.assertNotIn("secret-pass", rendered)


if __name__ == "__main__":
    unittest.main(verbosity=2)
