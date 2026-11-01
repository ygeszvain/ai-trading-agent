"""Portfolio state contracts.

Positions are always *derived from the ledger*; these dataclasses are the
computed views used by the strategy, risk engine, and website read models.
There is no second money ledger (plan section 16: dashboard projections).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class Position:
    """One held position with its average-cost method fields.

    ``mark`` is the latest available price and ``mark_as_of`` is when it was
    observed; stale marks carry the flag rather than being treated as fresh.
    """

    instrument_id: str
    quantity: Decimal
    average_cost: Decimal
    mark: Decimal | None
    mark_as_of: datetime | None
    mark_stale: bool = False

    @property
    def market_value(self) -> Decimal | None:
        if self.mark is None:
            return None
        return self.quantity * self.mark


@dataclass(frozen=True)
class PortfolioSnapshot:
    """A point-in-time portfolio view for one book (strategy or baseline)."""

    portfolio_key: str  # "strategy" | "cash-baseline" | "passive-baseline"
    run_id: str
    as_of: datetime
    cash: Decimal
    positions: tuple[Position, ...]
    gross_exposure: Decimal  # sum of position market values (Decimal; stale marks flagged)
    equity: Decimal
    reconciliation_status: str = "unverified"  # consistent | needs-review | unverified

    @property
    def cash_value(self) -> Decimal:
        return self.cash
