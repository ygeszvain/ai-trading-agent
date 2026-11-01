"""Conservative accounting for a backtest under evaluation.

Reconciles fills against a cash/position ledger and produces the NAV curve
and trade-level records the metrics layer consumes. Cost handling follows
plan section 15:

- Transaction costs (fee, half-spread, slippage, volume impact) are **real
  costs**: they reduce cash and the cost basis of the position. Slippage is
  applied exactly once (in the fill price, via the execution model) and is
  never re-charged at exit.
- Positions use FIFO lots so realized P&L and holding periods are exact.
- NAV is marked to the session close; uninvested cash earns 0% (the
  conservative baseline for a long-only equity system).
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from trading_agent.evaluation.execution_model import Fill, OrderSide, SessionObservation

_QUANT = Decimal("0.01")
_EPS = Decimal("0.01")


@dataclass(frozen=True)
class Lot:
    instrument: str
    entry_session: date
    quantity: Decimal
    unit_cost: Decimal  # fill price (costs included)


@dataclass(frozen=True)
class ClosedTrade:
    """A fully realized round trip assembled from FIFO lots."""

    instrument: str
    entry_session: date
    exit_session: date
    quantity: Decimal
    entry_price: Decimal
    exit_price: Decimal
    gross_pnl: Decimal
    costs: Decimal
    net_pnl: Decimal
    holding_sessions: int
    return_pct: Decimal


@dataclass(frozen=True)
class NavPoint:
    session: date
    cash: Decimal
    position_value: Decimal
    nav: Decimal
    daily_return: Decimal  # vs the previous mark; 0 for the first point


class AccountingEngine:
    """A cash/position ledger driven by fills, marked against observations."""

    def __init__(
        self,
        observations: Mapping[str, Mapping[date, SessionObservation]],
        initial_capital: Decimal,
        starting_session: date | None = None,
    ) -> None:
        self._observations = observations
        self._cash = initial_capital
        self._initial_capital = initial_capital
        self._starting_session = starting_session
        self._lots: dict[str, deque[Lot]] = {}
        self._costs_by_category: dict[str, Decimal] = {}
        self._closed_trades: list[ClosedTrade] = []
        self._pending_entry: dict[tuple[str, date], tuple[Decimal, Decimal]] = {}
        self._nav_points: list[NavPoint] = []
        self._last_nav: Decimal | None = None

    # ------------------------------------------------------------------ #
    @property
    def initial_capital(self) -> Decimal:
        return self._initial_capital

    def apply_fill(self, fill: Fill) -> None:
        """Apply a (partial or full) fill to the ledger."""
        notional = fill.price * fill.quantity
        cash_flow = notional + fill.total_cost
        if fill.side is OrderSide.BUY:
            self._cash -= cash_flow
            lots = self._lots.setdefault(fill.instrument, deque())
            lots.append(
                Lot(
                    instrument=fill.instrument,
                    entry_session=fill.session,
                    quantity=fill.quantity,
                    unit_cost=fill.price,
                )
            )
        else:
            self._cash += notional - fill.total_cost
            self._close_lots(fill)
        for category in ("fee", "spread", "slippage", "impact"):
            amount = getattr(fill, f"{category}_cost" if category != "fee" else "fee")
            self._costs_by_category[category] = (
                self._costs_by_category.get(category, Decimal(0)) + amount
            )

    def _close_lots(self, fill: Fill) -> None:
        lots = self._lots.setdefault(fill.instrument, deque())
        remaining = fill.quantity
        while remaining > _EPS and lots:
            lot = lots[0]
            taken = min(lot.quantity, remaining)
            proceeds = fill.price * taken
            cost_basis = lot.unit_cost * taken
            costs = (
                fill.total_cost * (taken / fill.quantity) if fill.quantity > 0 else fill.total_cost
            )
            gross = proceeds - cost_basis
            self._closed_trades.append(
                ClosedTrade(
                    instrument=fill.instrument,
                    entry_session=lot.entry_session,
                    exit_session=fill.session,
                    quantity=taken,
                    entry_price=lot.unit_cost,
                    exit_price=fill.price,
                    gross_pnl=gross,
                    costs=costs,
                    net_pnl=gross - costs,
                    holding_sessions=self._sessions_between(
                        fill.instrument, lot.entry_session, fill.session
                    ),
                    return_pct=(gross / cost_basis) if cost_basis > 0 else Decimal(0),
                )
            )
            if taken >= lot.quantity - _EPS:
                lots.popleft()
            else:
                lot = Lot(lot.instrument, lot.entry_session, lot.quantity - taken, lot.unit_cost)
                lots[0] = lot
            remaining -= taken
        if remaining > _EPS:
            raise ValueError(
                f"sell of {fill.quantity} {fill.instrument} exceeds long position by {remaining}"
            )

    def _sessions_between(self, instrument: str, start: date, end: date) -> int:
        sessions = sorted(self._observations.get(instrument, ()))
        # observation sessions spanned, inclusive of entry and exit
        return sum(1 for s in sessions if start <= s <= end)

    # ------------------------------------------------------------------ #
    def mark(self, session: date) -> NavPoint:
        """Mark the portfolio to the session close and record a NAV point.

        Instruments with no close on this session (halted) keep their last
        known value — the conservative reading is a *frozen* value, not a
        phantom gain, because no fill can occur on a halted session either.
        """
        position_value = Decimal(0)
        for instrument, lots in self._lots.items():
            quantity = sum((lot.quantity for lot in lots), Decimal(0))
            if quantity <= 0:
                continue
            bar = self._observations.get(instrument, {}).get(session)
            if bar is not None:
                last_price = bar.close
            else:
                sessions = sorted(self._observations.get(instrument, ()))
                known = [s for s in sessions if s <= session]
                if not known:
                    last_price = Decimal(0)
                else:
                    last_price = self._observations[instrument][known[-1]].close
            position_value += quantity * last_price
        nav = self._cash + position_value
        if self._last_nav is None or self._last_nav == 0:
            daily_return = Decimal(0)
        else:
            daily_return = (nav / self._last_nav) - 1
        self._last_nav = nav
        point = NavPoint(session, self._cash, position_value, nav, daily_return)
        self._nav_points.append(point)
        return point

    # ------------------------------------------------------------------ #
    def nav_series(self) -> list[NavPoint]:
        return list(self._nav_points)

    def daily_returns(self) -> list[Decimal]:
        return [point.daily_return for point in self._nav_points[1:]]

    def total_return(self) -> Decimal:
        if not self._nav_points:
            return Decimal(0)
        return (self._nav_points[-1].nav / self._initial_capital) - 1

    def max_drawdown(self) -> Decimal:
        peak = None
        worst = Decimal(0)
        for point in self._nav_points:
            if peak is None or point.nav > peak:
                peak = point.nav
            if peak:
                drawdown = Decimal(1) - (point.nav / peak)
                if drawdown > worst:
                    worst = drawdown
        return worst

    @property
    def closed_trades(self) -> list[ClosedTrade]:
        return list(self._closed_trades)

    @property
    def open_positions(self) -> dict[str, Decimal]:
        return {
            instrument: sum((lot.quantity for lot in lots), Decimal(0))
            for instrument, lots in self._lots.items()
            if sum((lot.quantity for lot in lots), Decimal(0)) > _EPS
        }

    def costs_summary(self) -> dict[str, Decimal]:
        total = sum(self._costs_by_category.values(), Decimal(0))
        return {**self._costs_by_category, "total": total}

    def cost_ratio(self) -> Decimal:
        """Total costs as a fraction of average NAV — the headline number
        that tells whether slippage kills the strategy."""
        if not self._nav_points:
            return Decimal(0)
        average_nav = sum((p.nav for p in self._nav_points), Decimal(0)) / len(self._nav_points)
        if average_nav <= 0:
            return Decimal(0)
        return self.costs_summary()["total"] / average_nav
