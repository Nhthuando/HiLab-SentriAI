import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

WORKER_DIR = Path(__file__).resolve().parent.parent
if str(WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(WORKER_DIR))

from zone.coverage_tracker import ActivityCoverageTracker


class ActivityCoverageTrackerTests(unittest.TestCase):
    def test_local_coverage_merges_intervals_and_keeps_seek_gap_partial(self):
        tracker = ActivityCoverageTracker(max_contiguous_gap_seconds=1.5)
        tracker.reset_source("LOCAL_FILE", "source-a", 100.0)
        for position in (0.0, 1.0, 2.0, 50.0, 51.0, 99.0, 100.0):
            tracker.observe(position_seconds=position)
        snapshot = tracker.snapshot()
        self.assertEqual(snapshot.coverage_status, "PARTIAL")
        self.assertLess(snapshot.coverage_percent, 10.0)
        self.assertEqual(len(snapshot.covered_intervals), 3)

    def test_local_coverage_becomes_complete_only_after_full_union(self):
        tracker = ActivityCoverageTracker(max_contiguous_gap_seconds=2.0)
        tracker.reset_source("LOCAL_FILE", "source-a", 10.0)
        for position in range(11):
            tracker.observe(position_seconds=float(position))
        snapshot = tracker.snapshot()
        self.assertEqual(snapshot.coverage_status, "COMPLETE")
        self.assertEqual(snapshot.coverage_percent, 100.0)
        self.assertIsNotNone(snapshot.completed_at)

    def test_source_change_resets_coverage_without_reusing_old_intervals(self):
        tracker = ActivityCoverageTracker()
        tracker.reset_source("LOCAL_FILE", "source-a", 10.0)
        tracker.observe(position_seconds=0.0)
        tracker.observe(position_seconds=5.0)
        tracker.reset_source("LOCAL_FILE", "source-b", 20.0)
        snapshot = tracker.snapshot()
        self.assertEqual(snapshot.source_fingerprint, "source-b")
        self.assertEqual(snapshot.covered_intervals, [])
        self.assertEqual(snapshot.coverage_status, "NOT_STARTED")

    def test_live_coverage_records_wall_clock_gaps(self):
        tracker = ActivityCoverageTracker(max_contiguous_gap_seconds=2.0)
        tracker.reset_source("LIVE", "BAI-KIEM", None)
        start = datetime(2026, 8, 28, 1, 0, tzinfo=timezone.utc)
        tracker.observe(observed_at=start)
        tracker.observe(observed_at=start + timedelta(seconds=1))
        tracker.observe(observed_at=start + timedelta(seconds=10))
        snapshot = tracker.snapshot()
        self.assertEqual(snapshot.coverage_status, "PARTIAL")
        self.assertEqual(len(snapshot.covered_intervals), 1)
        self.assertEqual(snapshot.last_observed_at, start + timedelta(seconds=10))

    def test_restore_resumes_same_source_intervals(self):
        tracker = ActivityCoverageTracker()
        completed = datetime(2026, 8, 28, 2, 0, tzinfo=timezone.utc)
        tracker.restore(
            source_kind="LOCAL_FILE",
            source_fingerprint="source-a",
            source_duration_seconds=10.0,
            covered_intervals=[[0.0, 4.0], [4.0, 8.0]],
            last_observed_at=completed,
            completed_at=None,
        )
        tracker.observe(position_seconds=8.0)
        tracker.observe(position_seconds=10.0)
        snapshot = tracker.snapshot()
        self.assertEqual(snapshot.coverage_status, "COMPLETE")
        self.assertEqual(snapshot.coverage_percent, 100.0)

    def test_explicit_clear_forgets_current_source_progress(self):
        tracker = ActivityCoverageTracker(max_contiguous_gap_seconds=2.0)
        tracker.reset_source("LOCAL_FILE", "source-a", 10.0)
        for position in range(11):
            tracker.observe(position_seconds=float(position))
        self.assertEqual(tracker.snapshot().coverage_status, "COMPLETE")

        tracker.clear_progress()

        snapshot = tracker.snapshot()
        self.assertEqual(snapshot.coverage_status, "NOT_STARTED")
        self.assertEqual(snapshot.covered_intervals, [])


if __name__ == "__main__":
    unittest.main()
