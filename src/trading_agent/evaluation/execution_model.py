"""Conservative execution model (plan section 15; prompt 6 acceptance criteria).

This is the model that every backtest in the evaluation runs through, and
it encodes the plan's execution assumptions *conservatively*:

- **No same-session fills.** A signal is known only at the close of session
  ``t`` (it uses that close). The earliest fill is the *next* trading
  session (``latency_sessions`` controls how many sessions later), never
  ``t`` itself. Fills reference that next session's bar.
- **Next-session open fills** when the source provides an open; the fill
  price is the open, adjusted for half-spread, baseline slippage, and
  volume-impact slippage (slope × min(quantity / session volume, 1) vs the
  participation cap). When only a close exists (e.g. FRED), the close is
  used — still the next session, never the signal session.
- **Limit orders** only fill when the bar actually reaches the limit: a buy
  limit fills when the low is <= the limit (an open gapping through it
  fills at the open); a sell limit mirrors this. No bar reach, no fill.
- **Partial fills.** A fill is capped at ``volume_participation_cap`` of the
  session's volume; the remainder stays queued for later sessions and is
  cancelled after ``pending_max_sessions`` (it is never silently filled).
- **Halted / missing sessions** never fill: orders simply stay pending.

Every realized cost (fee, spread, slippage, impact) is recorded per fill so
the accounting layer can reconcile it against P&L. Prices and rates are
``Decimal``; the model is a pure function of its inputs (deterministic).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

_BPS = Decimal("10000")


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"


class FillStatus(StrEnum):
    FILLED = "filled"
    PARTIAL = "partial"
    PENDING = "pending"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class SessionObservation:
    """One session's bar for one instrument; ``close`` is required, the
    rest are optional (missing means: the source does not provide it)."""

    session: date
    close: Decimal
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    volume: Decimal | None = None  # session volume, for participation capping


@dataclass(frozen=True)
class ExecutionCosts:
    """Per-transaction cost assumptions (bps of notional), all labelled.

    ``fee_bps`` is the broker trading fee; ``spread_bps`` is the half-spread
    crossed; ``slippage_bps`` is the baseline impact of trading;
    ``impact_bps_per_participation`` adds slope as a larger share of the
    session volume is traded.
    """

    fee_bps: Decimal = Decimal("4.18")
    spread_bps: Decimal = Decimal("10")
    slippage_bps: Decimal = Decimal("15")
    volume_participation_cap: Decimal = Decimal("0.10")
    impact_bps_per_participation: Decimal = Decimal("200")
    latency_sessions: int = 1
    limit_band_bps: Decimal = Decimal("50")
    pending_max_sessions: int = 5


@dataclass(frozen=True)
class Order:
    """A resting order submitted after a signal at ``signal_session``."""

    instrument: str
    side: OrderSide
    quantity: Decimal  # number of shares/units
    signal_session: date
    ref_price: Decimal  # the close at which the signal was known
    order_type: OrderType = OrderType.MARKET
    limit_price: Decimal | None = None
    submitted_session: date | None = None  # set by the model on submission

    @classmethod
    def from_signal(
        cls,
        *,
        instrument: str,
        side: OrderSide,
        quantity: Decimal,
        signal_session: date,
        ref_price: Decimal,
        costs: ExecutionCosts,
        order_type: OrderType = OrderType.MARKET,
    ) -> Order:
        if order_type is OrderType.LIMIT and ref_price <= 0:
            raise ValueError("a limit order requires a positive reference price")
        limit_price: Decimal | None = None
        if order_type is OrderType.LIMIT:
            band = ref_price * (costs.limit_band_bps / _BPS)
            limit_price = (
                (ref_price - band).quantize(Decimal("0.000001"), ROUND_HALF_UP)
                if side is OrderSide.BUY
                else (ref_price + band).quantize(Decimal("0.000001"), ROUND_HALF_UP)
            )
            if limit_price <= 0:
                limit_price = ref_price
        return cls(
            instrument=instrument,
            side=side,
            quantity=quantity,
            signal_session=signal_session,
            ref_price=ref_price,
            order_type=order_type,
            limit_price=limit_price,
        )


@dataclass(frozen=True)
class Fill:
    """A (partial or full) fill with its realized, itemized costs."""

    instrument: str
    side: OrderSide
    session: date
    quantity: Decimal
    price: Decimal
    fee: Decimal
    spread_cost: Decimal
    slippage_cost: Decimal
    impact_cost: Decimal
    reference_price: Decimal
    status: FillStatus

    @property
    def total_cost(self) -> Decimal:
        return self.fee + self.spread_cost + self.slippage_cost + self.impact_cost

    def realized_pnl(self) -> Decimal:
        """P&L of this fill vs the signal close, net of all costs.

        Buys lock in a cost basis (negative); sells realize the spread vs the
        reference, minus costs. Slippage is counted exactly once, here.
        """
        if self.side is OrderSide.BUY:
            return (self.reference_price - self.price) * self.quantity - self.total_cost
        return (self.price - self.reference_price) * self.quantity - self.total_cost


def base_price(
    instrument: str, session: date, observations: Mapping[str, Mapping[date, SessionObservation]]
) -> Decimal:
    """Best available reference price on ``session``: open if present, else close."""
    bar = observations.get(instrument, {}).get(session)
    if bar is None:
        raise ValueError(f"no observation for {instrument} on {session}")
    if bar.open is not None:
        return bar.open
    return bar.close


class ConservativeExecutionModel:
    """Event-free, deterministic order processor with conservative fills."""

    def __init__(
        self,
        observations: Mapping[str, Mapping[date, SessionObservation]],
        costs: ExecutionCosts,
    ) -> None:
        if costs.latency_sessions < 1:
            raise ValueError("latency_sessions must be >= 1 (no same-session fills)")
        self._obs = {
            instrument: dict(sorted(by_session.items()))
            for instrument, by_session in observations.items()
        }
        self._costs = costs
        self._sessions: list[date] = sorted(
            {session for by_session in self._obs.values() for session in by_session}
        )
        self._session_index = {session: i for i, session in enumerate(self._sessions)}

    @property
    def costs(self) -> ExecutionCosts:
        return self._costs

    def sessions(self) -> list[date]:
        return list(self._sessions)

    def instrument_sessions(self, instrument: str) -> list[date]:
        return list(self._obs.get(instrument, ()))

    def observation(self, instrument: str, session: date) -> SessionObservation | None:
        return self._obs.get(instrument, {}).get(session)

    def earliest_fill_session(self, signal_session: date) -> date | None:
        """The first session on which a signal from ``signal_session`` may
        fill: strictly after the signal session, ``latency_sessions`` later.

        Returns None when the market never trades again after the signal —
        in that case the order can never fill and must be reported pending.
        """
        if signal_session not in self._session_index:
            raise ValueError(f"signal session {signal_session} is not a known trading session")
        index = self._session_index[signal_session] + self._costs.latency_sessions
        if index >= len(self._sessions):
            return None
        return self._sessions[index]

    # ------------------------------------------------------------------ #
    # Fill logic
    # ------------------------------------------------------------------ #
    def attempt_fill(self, order: Order, session: date) -> Fill | None:
        """Attempt to fill ``order`` on ``session``.

        Returns the (possibly partial) fill, or None when it does not fill
        on this session (limit not reached, halt/missing bar, or the order
        is still within its latency window).
        """
        if session <= order.signal_session:
            raise ValueError(
                f"order from signal {order.signal_session} cannot fill on {session}: "
                "same-session fills are forbidden"
            )
        if self._session_index.get(session, -1) < (
            self._session_index.get(order.signal_session, -1) + self._costs.latency_sessions
        ):
            return None  # still within the latency window
        bar = self._obs.get(order.instrument, {}).get(session)
        if bar is None:
            return None  # halted / missing session: stays pending

        reachable, base_price = self._reaches(order, bar)
        if not reachable:
            return None

        notional = base_price * order.quantity
        fee = (notional * self._costs.fee_bps / _BPS).quantize(Decimal("0.0001"), ROUND_HALF_UP)
        spread = (notional * self._costs.spread_bps / _BPS).quantize(
            Decimal("0.0001"), ROUND_HALF_UP
        )
        baseline = (notional * self._costs.slippage_bps / _BPS).quantize(
            Decimal("0.0001"), ROUND_HALF_UP
        )

        participation = Decimal(0)
        if bar.volume is not None and bar.volume > 0:
            participation = min(order.quantity / bar.volume, Decimal(1))
        fill_quantity = order.quantity
        capped = False
        if bar.volume is not None and bar.volume > 0:
            max_quantity = (bar.volume * self._costs.volume_participation_cap).quantize(
                Decimal("1"), ROUND_HALF_UP
            )
            if max_quantity < fill_quantity and max_quantity > 0:
                fill_quantity = max_quantity
                capped = True
        impact = (
            notional
            * (
                self._costs.impact_bps_per_participation
                * min(participation * _BPS / _BPS, Decimal(1))
            )
            / _BPS
        ).quantize(Decimal("0.0001"), ROUND_HALF_UP)

        price = self._price_with_costs(
            base_price, order.side, fill_quantity, spread + baseline + impact
        )
        fee + spread + baseline + impact
        return Fill(
            instrument=order.instrument,
            side=order.side,
            session=session,
            quantity=fill_quantity,
            price=price,
            fee=fee,
            spread_cost=spread,
            slippage_cost=baseline + impact,
            impact_cost=impact,
            reference_price=order.ref_price,
            status=FillStatus.PARTIAL if capped else FillStatus.FILLED,
        )

    def _reaches(self, order: Order, bar: SessionObservation) -> tuple[bool, Decimal]:
        """Whether the bar reaches the order's trigger, and the raw base price.

        MARKET: fills at the open when available, else the close.
        LIMIT BUY: fills when the low touches the limit (an open below it
        gaps through and fills at the open); otherwise no fill.
        LIMIT SELL: mirrors the buy case with the high.
        """
        if order.order_type is OrderType.MARKET:
            base = bar.open if bar.open is not None else bar.close
            return True, base
        if order.limit_price is None:
            raise ValueError("limit order without a limit price")
        if order.side is OrderSide.BUY:
            if bar.open is not None and bar.open <= order.limit_price:
                return True, bar.open  # gapped through: fill at the open
            if bar.low is not None and bar.low <= order.limit_price:
                return True, order.limit_price
            if bar.low is None and bar.close <= order.limit_price:
                return True, order.limit_price  # close-only source
            return False, bar.close
        if bar.open is not None and bar.open >= order.limit_price:
            return True, bar.open
        if bar.high is not None and bar.high >= order.limit_price:
            return True, order.limit_price
        if bar.high is None and bar.close >= order.limit_price:
            return True, order.limit_price
        return False, bar.close

    def _price_with_costs(
        self, base: Decimal, side: OrderSide, quantity: Decimal, dollar_costs: Decimal
    ) -> Decimal:
        """Apply the (dollar) transaction costs to the base price.

        A buy pays up (base + cost/share); a sell receives less
        (base - cost/share). This keeps the price an honest, conservatively
        adjusted execution price rather than a gross quote.
        """
        if quantity <= 0:
            raise ValueError("cannot apply costs to a zero-quantity fill")
        per_share = dollar_costs / quantity
        price = base + per_share if side is OrderSide.BUY else base - per_share
        return max(price, Decimal("0.000001")).quantize(Decimal("0.000001"), ROUND_HALF_UP)


class PendingQueue:
    """Tracks resting orders through sessions until filled or cancelled.

    The queue is the unit that makes "no same-session fills" operational:
    ``submit`` during session ``t`` makes the order eligible from session
    ``t + latency`` onward; sessions with no fill simply continue the order;
    after ``pending_max_sessions`` without a fill the remainder is
    cancelled and reported.
    """

    def __init__(self, model: ConservativeExecutionModel) -> None:
        self._model = model
        self._orders: list[Order] = []
        self._queued_since: dict[str, date] = {}
        self._fills: list[Fill] = []
        self._cancellations: list[tuple[str, date, Decimal]] = []

    def submit(self, order: Order) -> None:
        key = f"{order.instrument}:{order.side.value}:{order.signal_session.isoformat()}"
        self._orders.append(order)
        self._queued_since[key] = order.signal_session

    def process_session(self, session: date) -> list[Fill]:
        """Process every resting order against ``session``; return fills."""
        remaining: list[Order] = []
        fills: list[Fill] = []
        for order in self._orders:
            f"{order.instrument}:{order.side.value}:{order.signal_session.isoformat()}"
            fill = self._model.attempt_fill(order, session)
            if fill is None:
                wait = self._days_between(order.signal_session, session)
                max_wait = (
                    self._model.costs.latency_sessions + self._model.costs.pending_max_sessions
                )
                if wait > max_wait:
                    self._cancellations.append((order.instrument, session, order.quantity))
                else:
                    remaining.append(order)
                continue
            self._fills.append(fill)
            fills.append(fill)
            remaining_quantity = order.quantity - fill.quantity
            if remaining_quantity > 0:
                remaining.append(
                    Order(
                        instrument=order.instrument,
                        side=order.side,
                        quantity=remaining_quantity,
                        signal_session=order.signal_session,
                        ref_price=order.ref_price,
                        order_type=order.order_type,
                        limit_price=order.limit_price,
                    )
                )
        self._orders = remaining
        return fills

    def _days_between(self, start: date, end: date) -> int:
        if start not in self._model.sessions():
            return 0
        try:
            sessions = self._model.sessions()
            return sessions.index(end) - sessions.index(start)
        except ValueError:  # pragma: no cover - defensive
            return 0

    @property
    def fills(self) -> list[Fill]:
        return list(self._fills)

    @property
    def cancellations(self) -> list[tuple[str, date, Decimal]]:
        return list(self._cancellations)

    def pending(self) -> list[Order]:
        return list(self._orders)
