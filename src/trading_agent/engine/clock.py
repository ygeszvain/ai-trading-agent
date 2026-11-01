"""Exchange session clock (plan section 17: use exchange calendars and the
configured exchange timezone; never fixed UTC offsets).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

# Three observation ticks per session: open, decision point, close.
TICK_OPEN = time(9, 30)
TICK_DECISION = time(10, 0)
TICK_CLOSE = time(16, 0)

TICKS: tuple[time, ...] = (TICK_OPEN, TICK_DECISION, TICK_CLOSE)


class ExchangeClock:
    """Session -> UTC tick instants for the configured exchange timezone."""

    def __init__(self, timezone_name: str, sessions: tuple[date, ...] | list[date]) -> None:
        self._tz = ZoneInfo(timezone_name)
        self._sessions = tuple(sessions)
        self._tick_cache: dict[date, tuple[datetime, ...]] = {}

    @property
    def sessions(self) -> tuple[date, ...]:
        return self._sessions

    def ticks(self, session: date) -> tuple[datetime, ...]:
        if session not in self._tick_cache:
            self._tick_cache[session] = tuple(
                datetime.combine(session, t).replace(tzinfo=self._tz).astimezone(UTC) for t in TICKS
            )
        return self._tick_cache[session]

    def tick(self, session: date, index: int) -> datetime:
        return self.ticks(session)[index]

    def session_of(self, instant: datetime) -> date:
        return instant.astimezone(self._tz).date()

    def session_bounds(self, session: date) -> tuple[datetime, datetime]:
        """Session open/close as UTC instants (start of the 09:30 tick, end of the 16:00 tick)."""
        start = datetime.combine(session, TICK_OPEN).replace(tzinfo=self._tz).astimezone(UTC)
        end = datetime.combine(session, TICK_CLOSE).replace(tzinfo=self._tz).astimezone(UTC)
        return start, end
