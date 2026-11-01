"""Data gateway contract (plan section 7).

All market data access goes through this interface. v1 ships exactly one
implementation, the offline synthetic fixture (plan section 6). A live or
vendor gateway implements the same interface and is selected by config, with
the synthetic source remaining the default.
"""

from __future__ import annotations

import abc
from datetime import date, datetime
from decimal import Decimal

from ..contracts.market import Instrument, MarketBar, Quote
from ..data.provider import SessionClose
from ..exceptions import TradingAgentError


class MarketDataGateway(abc.ABC):
    """The single market data entry point for the whole system."""

    @abc.abstractmethod
    def instrument_ids(self) -> tuple[str, ...]: ...

    @abc.abstractmethod
    def instruments(self) -> tuple[Instrument, ...]: ...

    @abc.abstractmethod
    def data_snapshot_id(self) -> str:
        """Stable identifier of the exact data source and cut.

        Persisted with every research record and web quote so any displayed
        value can be traced to the snapshot it came from.
        """

    @abc.abstractmethod
    def sessions(self) -> tuple[date, ...]: ...

    @abc.abstractmethod
    def bars(self, instrument_id: str, start: datetime, end: datetime) -> tuple[MarketBar, ...]: ...

    @abc.abstractmethod
    def quote(self, instrument_id: str, as_of: datetime) -> Quote | None: ...

    @abc.abstractmethod
    def sessions_since_observation(self, instrument_id: str, as_of: datetime) -> int: ...

    @abc.abstractmethod
    def recent_session_closes(
        self, instrument_id: str, as_of_session: date, count: int
    ) -> tuple[SessionClose, ...]: ...

    @abc.abstractmethod
    def session_volume(self, instrument_id: str, as_of: datetime) -> Decimal | None: ...


class GatewayNotAvailableError(TradingAgentError):
    """Raised when a gateway is requested but none is configured/ready."""
