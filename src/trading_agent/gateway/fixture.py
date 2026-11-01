"""The v1 data gateway: the deterministic synthetic market fixture.

Offline and reproducible (seeded). Point-in-time semantics come from the
underlying provider; this adapter exposes the gateway contract and tags every
value with the fixture's data snapshot id (plan sections 6 and 8).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from ..config.models import TradingConfig
from ..contracts.market import Instrument, MarketBar, Quote
from ..data.provider import SessionClose, SyntheticMarketProvider
from .contracts import MarketDataGateway


class SyntheticGateway(MarketDataGateway):
    """Read-only adapter over the seeded synthetic fixture market."""

    def __init__(self, config: TradingConfig, provider: SyntheticMarketProvider) -> None:
        self._config = config
        self._provider = provider
        self._instruments = {i.instrument_id: i for i in provider.instruments()}

    @property
    def provider(self) -> SyntheticMarketProvider:
        return self._provider

    def instrument_ids(self) -> tuple[str, ...]:
        return tuple(self._config.paper.synthetic_fixture_universe.split())

    def instruments(self) -> tuple[Instrument, ...]:
        return tuple(self._instruments.values())

    def data_snapshot_id(self) -> str:
        return self._provider.data_snapshot_id

    def sessions(self) -> tuple[date, ...]:
        return self._provider.sessions()

    def bars(self, instrument_id: str, start: datetime, end: datetime) -> tuple[MarketBar, ...]:
        return self._provider.bars(instrument_id, start, end)

    def quote(self, instrument_id: str, as_of: datetime) -> Quote | None:
        return self._provider.quote(instrument_id, as_of)

    def sessions_since_observation(self, instrument_id: str, as_of: datetime) -> int:
        return self._provider.sessions_since_observation(instrument_id, as_of)

    def recent_session_closes(
        self, instrument_id: str, as_of_session: date, count: int
    ) -> tuple[SessionClose, ...]:
        return self._provider.recent_session_closes(instrument_id, as_of_session, count)

    def session_volume(self, instrument_id: str, as_of: datetime) -> Decimal | None:
        return self._provider.session_volume(instrument_id, as_of)


def build_gateway(config: TradingConfig) -> MarketDataGateway:
    """Construct the gateway selected by config (v1: always the fixture)."""
    from ..fixtures.synthetic import build_synthetic_market

    market = build_synthetic_market(
        config.paper.synthetic_fixture_seed,
        config.paper.synthetic_fixture_sessions,
        config.paper.synthetic_fixture_universe,
    )
    provider = SyntheticMarketProvider(
        market, exchange_timezone=config.paper.exchange_timezone
    )
    return SyntheticGateway(config, provider)
