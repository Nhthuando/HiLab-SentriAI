"""Pure coverage accounting for BAI-KIEM activity analytics."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional, Tuple


Interval = Tuple[float, float]


@dataclass(frozen=True)
class CoverageSnapshot:
    source_kind: str
    source_fingerprint: Optional[str]
    source_duration_seconds: Optional[float]
    covered_intervals: List[Interval]
    coverage_percent: float
    coverage_status: str
    last_observed_at: Optional[datetime]
    completed_at: Optional[datetime]


class ActivityCoverageTracker:
    """Merge observed source-time intervals without treating seeks as coverage."""

    def __init__(
        self,
        max_contiguous_gap_seconds: float = 2.0,
        complete_threshold: float = 0.99,
    ) -> None:
        self.max_contiguous_gap_seconds = max(0.01, float(max_contiguous_gap_seconds))
        self.complete_threshold = min(1.0, max(0.5, float(complete_threshold)))
        self.source_kind = "UNAVAILABLE"
        self.source_fingerprint: Optional[str] = None
        self.source_duration_seconds: Optional[float] = None
        self.covered_intervals: List[Interval] = []
        self.last_observed_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None
        self._previous_position: Optional[float] = None

    def reset_source(
        self,
        source_kind: str,
        source_fingerprint: Optional[str],
        source_duration_seconds: Optional[float],
    ) -> None:
        duration = float(source_duration_seconds) if source_duration_seconds else None
        identity = (source_kind, source_fingerprint, duration)
        current = (self.source_kind, self.source_fingerprint, self.source_duration_seconds)
        if identity == current:
            return
        self.source_kind = source_kind
        self.source_fingerprint = source_fingerprint
        self.source_duration_seconds = duration
        self.covered_intervals = []
        self.last_observed_at = None
        self.completed_at = None
        self._previous_position = None

    def break_continuity(self) -> None:
        """Prevent a seek/jump from filling an unobserved interval."""
        self._previous_position = None

    def clear_progress(self) -> None:
        """Forget coverage for the current source after an explicit data reset."""
        self.covered_intervals = []
        self.last_observed_at = None
        self.completed_at = None
        self._previous_position = None

    def restore(
        self,
        source_kind: str,
        source_fingerprint: Optional[str],
        source_duration_seconds: Optional[float],
        covered_intervals: List[List[float]],
        last_observed_at: Optional[datetime],
        completed_at: Optional[datetime],
    ) -> None:
        """Restore a persisted snapshot before processing resumes."""
        self.reset_source(source_kind, source_fingerprint, source_duration_seconds)
        restored: List[Interval] = []
        for item in covered_intervals:
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                continue
            try:
                incoming = (float(item[0]), float(item[1]))
            except (TypeError, ValueError):
                continue
            restored = self._merge(restored, incoming)
        self.covered_intervals = restored
        self.last_observed_at = last_observed_at
        self.completed_at = completed_at
        self._previous_position = None

    @staticmethod
    def _merge(intervals: List[Interval], incoming: Interval) -> List[Interval]:
        start, end = sorted(incoming)
        if end <= start:
            return intervals
        merged: List[Interval] = []
        for left, right in sorted([*intervals, (start, end)]):
            if not merged or left > merged[-1][1] + 1e-6:
                merged.append((left, right))
            else:
                merged[-1] = (merged[-1][0], max(merged[-1][1], right))
        return merged

    def observe(
        self,
        position_seconds: Optional[float] = None,
        observed_at: Optional[datetime] = None,
    ) -> None:
        now = observed_at or datetime.now(timezone.utc)
        position = (
            float(position_seconds)
            if position_seconds is not None
            else now.timestamp()
        )
        if self._previous_position is not None:
            delta = position - self._previous_position
            if 0 < delta <= self.max_contiguous_gap_seconds:
                self.covered_intervals = self._merge(
                    self.covered_intervals,
                    (self._previous_position, position),
                )
        self._previous_position = position
        self.last_observed_at = now
        if self._is_complete() and self.completed_at is None:
            self.completed_at = now

    def _coverage_percent(self) -> float:
        if not self.source_duration_seconds:
            return 0.0
        observed = sum(max(0.0, right - left) for left, right in self.covered_intervals)
        return round(min(100.0, observed / self.source_duration_seconds * 100.0), 2)

    def _is_complete(self) -> bool:
        duration = self.source_duration_seconds
        if not duration or not self.covered_intervals:
            return False
        percent = self._coverage_percent() / 100.0
        first, last = self.covered_intervals[0], self.covered_intervals[-1]
        tolerance = max(self.max_contiguous_gap_seconds, duration * (1.0 - self.complete_threshold))
        return percent >= self.complete_threshold and first[0] <= tolerance and last[1] >= duration - tolerance

    def snapshot(self) -> CoverageSnapshot:
        if self.source_kind == "UNAVAILABLE":
            status = "UNAVAILABLE"
        elif self.completed_at is not None or self._is_complete():
            status = "COMPLETE"
        elif self.last_observed_at is None:
            status = "NOT_STARTED"
        else:
            status = "PARTIAL"
        return CoverageSnapshot(
            source_kind=self.source_kind,
            source_fingerprint=self.source_fingerprint,
            source_duration_seconds=self.source_duration_seconds,
            covered_intervals=list(self.covered_intervals),
            coverage_percent=100.0 if status == "COMPLETE" else self._coverage_percent(),
            coverage_status=status,
            last_observed_at=self.last_observed_at,
            completed_at=self.completed_at,
        )
