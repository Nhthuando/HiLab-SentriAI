"""Unit tests for the all-label Area activity lifecycle."""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

WORKER_DIR = Path(__file__).resolve().parent.parent
if str(WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(WORKER_DIR))

from zone.activity_tracker import ActivityTracker

NOW = datetime(2026, 8, 27, tzinfo=timezone.utc)


def detection(track_id=7, status="ALLOWED", zones=None, canonical="forklift", x=0.2):
    matches = zones or [{"zoneId": "zone-1", "zoneName": "Khu nâng hạ", "status": status}]
    return {
        "trackId": track_id,
        "canonicalClass": canonical,
        "class": canonical,
        "label": "Xe nâng",
        "normalized_bbox": [x, 0.2, x + 0.2, 0.7],
        "canInitiate": True,
        "zoneMatches": matches,
    }


class TestActivityTracker(unittest.TestCase):
    def test_allowed_track_opens_once_and_closes_at_last_seen(self):
        tracker = ActivityTracker(confirmation_seconds=1, missing_grace_seconds=12)
        self.assertEqual(tracker.check_detections([detection()], NOW), [])
        started = tracker.check_detections([detection()], NOW + timedelta(seconds=1))
        self.assertEqual([(item.action, item.policy_result) for item in started], [("STARTED", "ALLOWED")])
        self.assertEqual(tracker.check_detections([], NOW + timedelta(seconds=5)), [])
        ended = tracker.check_detections([], NOW + timedelta(seconds=14))
        self.assertEqual(ended[0].exited_at, NOW + timedelta(seconds=1))
        self.assertEqual(ended[0].duration_seconds, 1)

    def test_overlapping_zones_create_independent_sessions(self):
        tracker = ActivityTracker(confirmation_seconds=0)
        zones = [
            {"zoneId": "zone-1", "zoneName": "A", "status": "ALLOWED"},
            {"zoneId": "zone-2", "zoneName": "B", "status": "VIOLATION"},
        ]
        started = tracker.check_detections([detection(zones=zones)], NOW)
        self.assertEqual({item.zone_id for item in started}, {"zone-1", "zone-2"})
        self.assertEqual({item.policy_result for item in started}, {"ALLOWED", "VIOLATION"})

    def test_short_occlusion_reidentifies_same_session(self):
        tracker = ActivityTracker(confirmation_seconds=0, missing_grace_seconds=12)
        started = tracker.check_detections([detection(track_id=7)], NOW)
        session_id = started[0].session_id
        tracker.check_detections([], NOW + timedelta(seconds=1))
        self.assertEqual(
            tracker.check_detections([detection(track_id=19, x=0.21)], NOW + timedelta(seconds=2)),
            [],
        )
        self.assertEqual(next(iter(tracker.active_sessions.values())).session_id, session_id)

    def test_reentry_after_close_creates_new_session(self):
        tracker = ActivityTracker(confirmation_seconds=0, grace_frames=1)
        first = tracker.check_detections([detection()], NOW)[0]
        tracker.check_detections([dict(detection(), zoneMatches=[])], NOW + timedelta(seconds=1))
        second = tracker.check_detections([detection()], NOW + timedelta(seconds=2))[0]
        self.assertNotEqual(first.session_id, second.session_id)

    def test_weak_detection_cannot_open_session(self):
        tracker = ActivityTracker(confirmation_seconds=0)
        weak = detection()
        weak["canInitiate"] = False
        self.assertEqual(tracker.check_detections([weak], NOW), [])
        self.assertEqual(tracker.active_sessions, {})


if __name__ == "__main__":
    unittest.main()
