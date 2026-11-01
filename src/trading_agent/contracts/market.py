"""Market data contracts (build plan section 8 data contract, section 7 interfaces).

All timestamps are timezone-aware UTC. Source timezones are retained in the
persisted form (plan section 16). Quality flags are explicit: a bar or quote
is either valid, stale, or missing — never silently interpolated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class QualityFlag(StrEnum):
    """Data quality states shown verbatim by the website (unavailable is not zero)."""

    VALID = "valid"
    STALE = "stale"
    MISSING = "missing"
    CORRECTED = "corrected"


@dataclass(frozen=True)
class Instrument:
    """Stable instrument identity (plan section 16: instruments)."""

    instrument_id: str
    symbol: str
    asset_class: str  # "synthetic-equity" in the fixture universe
    price_decimals: int = 2
    quantity_precision: int = 0
    is_synthetic: bool = True
    eligible: bool = True
    notes: tuple[str, ...] = field(default=())


@dataclass(frozen=True)
class MarketBar:
    """One timestamped observation. Prices are unadjusted (execution basis)."""

    instrument_id: str
    ts: datetime  # observation time, UTC
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    source_id: str = "synthetic-fixture"
    quality: QualityFlag = QualityFlag.VALID
    exchange_time: datetime | None = None  # same instant, exchange tz (for display)


@dataclass(frozen=True)
class Quote:
    """A price observation with explicit age semantics for freshness checks."""

    instrument_id: str
    price: Decimal
    as_of: datetime  # when the observation was made, UTC
    source_id: str = "synthetic-fixture"
    quality: QualityFlag = QualityFlag.VALID
