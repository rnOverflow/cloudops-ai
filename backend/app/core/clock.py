from __future__ import annotations

from datetime import UTC, datetime, timedelta


class Clock:
    """Wall clock. Every timestamp in the platform goes through a Clock so that tests
    can drive the control loop deterministically with :class:`ManualClock`."""

    def now(self) -> datetime:
        return datetime.now(UTC)

    def advance(self, seconds: float) -> None:  # real time advances by itself
        return None


class ManualClock(Clock):
    def __init__(self, start: datetime | None = None):
        self._now = start or datetime(2026, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)
