"""Market data provider interface and the synthetic fixture implementation.

Every accessor is point-in-time: an observation is usable only if its
timestamp is at or before the requested instant (plan section 8 cutoff
rules). Staleness is reported explicitly (``sessions_since_observation``)
and never interpolated.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from ..contracts.market import Instrument, MarketBar, QualityFlag, Quote
from ..fixtures.synthetic import SyntheticMarket


@dataclass(frozen=True)
class SessionClose:
    """One session's final closing price (the 16:00 observation)."""

    session: date
    close: Decimal


class MarketDataProvider(abc.ABC):
    """Point-in-time market data access (plan section 7 interface)."""

    @abc.abstractmethod
    def instruments(self) -> tuple[Instrument, ...]: ...

    @abc.abstractmethod
    def sessions(self) -> tuple[date, ...]:
        """Open sessions covered by the data, chronological."""

    @abc.abstractmethod
    def data_snapshot_id(self) -> str: ...

    @abc.abstractmethod
    def bars(self, instrument_id: str, start: datetime, end: datetime) -> tuple[MarketBar, ...]: ...

    @abc.abstractmethod
    def quote(self, instrument_id: str, as_of: datetime) -> Quote | None:
        """The most recent observation at or before ``as_of``, or None if none."""

    @abc.abstractmethod
    def sessions_since_observation(self, instrument_id: str, as_of: datetime) -> int:
        """Completed sessions elapsed since the latest observation at or before ``as_of``.

        0 means the instrument was observed in the as-of session. -1 means no
        usable observation exists point-in-time. Staleness is derived from this
        count; the website and risk engine never guess.
        """

    @abc.abstractmethod
    def recent_session_closes(
        self, instrument_id: str, as_of_session: date, count: int
    ) -> tuple[SessionClose, ...]:
        """Session closes for the trailing window (oldest first).

        A session with missing data is simply absent, so a data gap shortens
        the window and callers must treat that as insufficient history.
        """

    @abc.abstractmethod
    def session_volume(self, instrument_id: str, as_of: datetime) -> Decimal | None:
        """Total traded volume of the most recent *completed* session before ``as_of``.

        Point-in-time safe: only a fully past session is used, never the one in
        progress. ``None`` when no completed session has data (warm-up). The
        risk engine's participation check applies the participation fraction
        to this session-level volume (the venue itself caps *per bar*).
        """


class SyntheticMarketProvider(MarketDataProvider):
    """Read-only point-in-time view over the generated fixture market."""

    def __init__(
        self,
        market: SyntheticMarket,
        exchange_timezone: str,
        stale_after_sessions: int = 1,
    ) -> None:
        self._market = market
        self._tz = ZoneInfo(exchange_timezone)
        self._stale_after_sessions = stale_after_sessions
        self._by_session: dict[str, dict[date, tuple[MarketBar, ...]]] = {}
        for instrument_id, bars in market.bars.items():
            grouped: dict[date, list[MarketBar]] = {}
            for bar in bars:
                grouped.setdefault(_local_date(bar, self._tz), []).append(bar)
            self._by_session[instrument_id] = {day: tuple(v) for day, v in sorted(grouped.items())}
        self._session_index = {session: i for i, session in enumerate(market.sessions)}

    @property
    def source_id(self) -> str:
        return "synthetic"

    def instruments(self) -> tuple[Instrument, ...]:
        return tuple(self._market.instruments.values())

    def sessions(self) -> tuple[date, ...]:
        return self._market.sessions

    def data_snapshot_id(self) -> str:
        return self._market.data_snapshot_id

    def bars(self, instrument_id: str, start: datetime, end: datetime) -> tuple[MarketBar, ...]:
        bars = self._market.bars.get(instrument_id, ())
        return tuple(bar for bar in bars if start <= bar.ts <= end)

    def quote(self, instrument_id: str, as_of: datetime) -> Quote | None:
        available = [bar for bar in self._market.bars.get(instrument_id, ()) if bar.ts <= as_of]
        if not available:
            return None
        latest = available[-1]
        stale = self.sessions_since_observation(instrument_id, as_of)
        quality = (
            QualityFlag.STALE
            if stale >= self._stale_after_sessions
            else QualityFlag.VALID
        )
        return Quote(
            instrument_id=instrument_id,
            price=latest.close,
            as_of=latest.ts,
            source_id=latest.source_id,
            quality=quality,
        )

    def sessions_since_observation(self, instrument_id: str, as_of: datetime) -> int:
        available = [bar for bar in self._market.bars.get(instrument_id, ()) if bar.ts <= as_of]
        if not available:
            return -1
        last = max(_local_date(bar, self._tz) for bar in available)
        as_of_session = as_of.astimezone(self._tz).date()
        if as_of_session not in self._session_index:
            # The as-of instant falls on a non-session day (holiday/weekend).
            prior = [session for session in self._session_index if session <= as_of_session]
            if not prior:
                return -1
            as_of_session = max(prior)
        if last not in self._session_index:
            return -1
        return self._session_index[as_of_session] - self._session_index[last]

    def recent_session_closes(
        self, instrument_id: str, as_of_session: date, count: int
    ) -> tuple[SessionClose, ...]:
        grouped = self._by_session.get(instrument_id, {})
        closes = [
            SessionClose(session=day, close=bars[-1].close)
            for day, bars in sorted(grouped.items())
            if day <= as_of_session
        ]
        return tuple(closes[-count:])

    def session_volume(self, instrument_id: str, as_of: datetime) -> Decimal | None:
        as_of_session = as_of.astimezone(self._tz).date()
        prior = [session for session in self._session_index if session < as_of_session]
        if not prior:
            return None
        last = max(prior)
        bars = self._by_session.get(instrument_id, {}).get(last)
        if not bars:
            return None
        return sum((bar.volume for bar in bars), Decimal("0"))


def _local_date(bar: MarketBar, tz: ZoneInfo) -> date:
    instant = bar.exchange_time if bar.exchange_time is not None else bar.ts
    return instant.astimezone(tz).date()
