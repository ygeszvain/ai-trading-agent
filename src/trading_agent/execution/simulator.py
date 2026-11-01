"""Internal simulated execution venue (plan sections 14 and 17).

The simulator is a *real* (local, deterministic) venue for SIMULATION and
PAPER modes: it owns the order book, runs the state machine of plan section
14, and produces fills. It never touches a real broker.

State machine (normalized statuses):
    SUBMISSION_PENDING -> ACKNOWLEDGED | UNKNOWN
    SUBMISSION_PENDING -> REJECTED            (pre-venue rejection)
    ACKNOWLEDGED       -> PARTIALLY_FILLED | FILLED | CANCEL_PENDING | EXPIRED
    PARTIALLY_FILLED   -> FILLED | CANCEL_PENDING | EXPIRED
    CANCEL_PENDING     -> CANCELLED | FILLED | PARTIALLY_FILLED   (fill wins races)
    UNKNOWN            -> (reconciliation) -> ACKNOWLEDGED | ...

Per-tick processing order (documented in docs/fill_simulation.md):
    1. evaluate fills for every open order against the bar (fill beats a
       pending cancel request on the same bar),
    2. confirm cancel requests that did not fill on that bar,
    3. at session end: DAY expiry for the rest.

A cancellation request is not a cancellation confirmation; a canceled order
may retain fills. A timed-out (UNKNOWN) submission keeps its reservations and
trades nothing until reconciliation resolves it.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import cast

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from ..config.models import TradingConfig, is_live_mode
from ..contracts.broker import (
    AccountSnapshot,
    BrokerCapabilities,
    BrokerError,
    BrokerExecutionDenied,
    BrokerExecutionNotAvailable,
    BrokerStateNotAvailable,
    NormalizedOrderStatus,
    OrderRequest,
    OrderResult,
)
from ..contracts.market import MarketBar
from ..contracts.orders import (
    AttemptOutcome,
    Fill,
    Order,
    OrderSide,
    SubmissionAttempt,
)
from ..db.schema import broker_orders, fills, order_events, submission_attempts
from ..money import round_money, round_qty
from .broker_interface import BrokerAdapter

_OPEN_STATUSES = frozenset(
    {
        NormalizedOrderStatus.SUBMISSION_PENDING,
        NormalizedOrderStatus.ACKNOWLEDGED,
        NormalizedOrderStatus.PARTIALLY_FILLED,
        NormalizedOrderStatus.CANCEL_PENDING,
        NormalizedOrderStatus.UNKNOWN,
    }
)


@dataclass
class VenueState:
    """The venue's authoritative view of its own books (for snapshot/reconciliation)."""

    cash: Decimal
    positions: dict[str, Decimal]
    open_orders: int
    as_of: datetime | None = None


class SimulatorBrokerAdapter(BrokerAdapter):
    """The local simulated venue. Binds to a run for the duration of a demo."""

    provider = "simulator"

    def __init__(
        self,
        config: TradingConfig,
        *,
        run_id: str | None = None,
        session: Session | None = None,
        account_alias: str | None = None,
        initial_cash: Decimal | None = None,
    ) -> None:
        self._config = config
        self._run_id = run_id
        self._session = session
        self._account_alias = account_alias
        self._initial_cash = (
            initial_cash if initial_cash is not None else config.paper.initial_cash_usd
        )
        self._orders: dict[str, Order] = {}
        self._order_seq: dict[str, int] = {}
        self._submissions_made = 0
        self._lost_ack_used = False
        self._now_fn = _wall_clock
        self._loads_open_orders()
        self._seed_submission_counter()

    def set_now(self, instant: datetime) -> None:
        """Bind the simulated clock (exchange session time) for this adapter.

        Every timestamp the venue records (submission attempts, state
        transitions it initiates itself) uses this clock, so a ``--reset``
        re-run of the deterministic demo produces byte-identical rows instead
        of wall-clock values. Bars and explicitly-passed instants always win.
        """
        self._now_fn = lambda: instant

    # ------------------------------------------------------------ binding

    @property
    def bound(self) -> bool:
        return self._run_id is not None and self._session is not None

    def capabilities(self) -> BrokerCapabilities:
        live = is_live_mode(self._config.app.mode)
        if self.bound and not live:
            return BrokerCapabilities(
                provider=self.provider,
                connected=True,
                reads_enabled=True,
                execution_enabled=True,
                verified_capability_digest=None,
                notes=(
                    "local simulated venue (no external connection; M1)",
                    "simulation/paper only; no live account, no real money",
                    "official Robinhood gateway is a separate, unimplemented adapter",
                ),
            )
        if self.bound and live:
            return BrokerCapabilities(
                provider=self.provider,
                connected=True,
                reads_enabled=True,
                execution_enabled=False,
                verified_capability_digest=None,
                notes=(
                    "simulated venue refuses execution in live modes; "
                    "live trading requires the official Robinhood gateway (M4)",
                ),
            )
        return BrokerCapabilities(
            provider=self.provider,
            connected=False,
            reads_enabled=False,
            execution_enabled=False,
            verified_capability_digest=None,
            notes=(
                "simulator engine is implemented (M1) but not bound to a run here; "
                "no state exists to report",
                "no live account, no external network, no real money",
            ),
        )

    def account_snapshot(self) -> AccountSnapshot:
        if not self.bound:
            raise BrokerStateNotAvailable(
                "simulator has no run context bound; no persisted state exists "
                "(refusing to fabricate a snapshot)"
            )
        state = self.venue_state()
        return AccountSnapshot(
            available=True,
            reason="simulated venue state (deterministic fixture run)",
            as_of=state.as_of,
        )

    # ------------------------------------------------- broker write calls

    def submit_order(self, request: OrderRequest) -> OrderResult:
        if not self.bound:
            raise BrokerExecutionNotAvailable(
                "simulator order submission rejected: no run context bound; "
                "(not executed, no effect)"
            )
        if is_live_mode(self._config.app.mode):
            raise BrokerExecutionDenied(
                "simulated venue refuses execution in a live mode; "
                "live trading requires the official Robinhood gateway (M4). "
                "(not executed, no effect)"
            )
        assert self._run_id is not None
        order = self._orders.get(request.client_order_id)
        if order is None or order.status is not NormalizedOrderStatus.SUBMISSION_PENDING:
            raise BrokerError(
                f"submit_order: {request.client_order_id!r} is not a pending submission "
                "(already submitted or unknown); refusing a duplicate submission"
            )
        self._submissions_made += 1
        lost_ack = (
            self._config.data.scenarios
            and "lost_ack" in self._config.data.scenarios
            and self._submissions_made == 1
            and not self._lost_ack_used
        )
        if lost_ack:
            self._lost_ack_used = True
            outcome = AttemptOutcome.UNKNOWN
            raw = "response-lost"
            error_class = "acknowledgment_timeout"
        else:
            outcome = AttemptOutcome.ACKNOWLEDGED
            raw = "accepted"
            error_class = None
        now = self._now_fn()
        attempt = SubmissionAttempt(
            attempt_id=_hash_id(
                "attempt", self._run_id, order.order_id, str(self._submissions_made)
            ),
            run_id=self._run_id,
            order_id=order.order_id,
            request_digest=_hash_id(
                "req",
                request.instrument,
                request.side,
                str(request.quantity),
                str(request.limit_price),
            ),
            submitted_at=now,
            outcome=outcome,
            raw_status=raw,
            error_class=error_class,
        )
        self._persist_attempt(attempt)
        self._transition(order, outcome.to_status(), now, f"submission {raw}")
        if outcome is AttemptOutcome.UNKNOWN:
            return OrderResult(
                accepted=True,
                status=NormalizedOrderStatus.UNKNOWN,
                rejection_reason="acknowledgment lost; order left UNKNOWN until reconciliation",
                broker_order_id=order.order_id,
                error_class=error_class,
            )
        return OrderResult(
            accepted=True,
            status=NormalizedOrderStatus.ACKNOWLEDGED,
            broker_order_id=order.order_id,
        )

    def _find(self, order_ref: str) -> Order | None:
        """Resolve an order by broker order id or client order id."""
        direct = self._orders.get(order_ref)
        if direct is not None:
            return direct
        for order in self._orders.values():
            if order.order_id == order_ref:
                return order
        return None

    def cancel_order(self, broker_order_id: str) -> OrderResult:
        if not self.bound:
            raise BrokerExecutionNotAvailable(
                f"simulator cancellation rejected: no run context bound; "
                f"order {broker_order_id!r} left untouched (not executed, no effect)"
            )
        order = self._find(broker_order_id)
        if order is None:
            raise BrokerError(f"cancel_order: unknown order {broker_order_id!r}")
        if order.status in (
            NormalizedOrderStatus.ACKNOWLEDGED,
            NormalizedOrderStatus.PARTIALLY_FILLED,
            NormalizedOrderStatus.CANCEL_PENDING,
            NormalizedOrderStatus.UNKNOWN,
        ):
            now = self._now_fn()
            order.cancel_requested_at = now
            self._transition(
                order,
                NormalizedOrderStatus.CANCEL_PENDING,
                now,
                "cancel request accepted (not a confirmation)",
            )
            return OrderResult(
                accepted=True,
                status=NormalizedOrderStatus.CANCEL_PENDING,
                broker_order_id=order.order_id,
            )
        raise BrokerError(
            f"cancel_order: order {broker_order_id!r} is {order.status.value}; "
            "no cancellation to request"
        )

    # ------------------------------------------------------ venue engine

    def register_order(self, order: Order) -> None:
        """Adopt an order created by the application (persist it in this tx)."""
        if not self.bound:
            raise BrokerExecutionNotAvailable("simulator is not bound to a run")
        if order.client_order_id in self._orders:
            raise BrokerError(
                f"register_order: client order id {order.client_order_id!r} already known "
                "(idempotency keys must be unique)"
            )
        self._orders[order.client_order_id] = order
        self._order_seq[order.order_id] = 0
        self._persist_order(order)
        self._transition(
            order, NormalizedOrderStatus.SUBMISSION_PENDING, order.created_at, "order created"
        )

    def on_bar(self, bar: MarketBar) -> tuple[list[Fill], list[str]]:
        """Process every open order against one bar; returns (new fills, changed order ids)."""
        fills_out: list[Fill] = []
        changed: list[str] = []
        for order in self._orders.values():
            if order.instrument_id != bar.instrument_id:
                continue
            if order.status is NormalizedOrderStatus.UNKNOWN:
                continue  # no trading until reconciliation
            if order.status not in _OPEN_STATUSES:
                continue
            before = order.status
            fill = self._try_fill(order, bar)
            if fill is not None:
                fills_out.append(fill)
            if (
                order.cancel_requested_at is not None
                and (fill is None or order.status is not NormalizedOrderStatus.FILLED)
                and order.status
                in (
                    NormalizedOrderStatus.ACKNOWLEDGED,
                    NormalizedOrderStatus.PARTIALLY_FILLED,
                    NormalizedOrderStatus.CANCEL_PENDING,
                )
            ):
                self._transition(
                    order,
                    NormalizedOrderStatus.CANCELLED,
                    bar.ts,
                    "cancel confirmed (after bar); fills retained"
                    if fill is not None
                    else "cancel confirmed",
                )
            if order.status is not before:
                changed.append(order.order_id)
        return fills_out, changed

    def end_of_session(self, at: datetime) -> list[str]:
        """Session-end settlement: confirm pending cancels, then DAY-expire the rest.

        Returns the ids of every order whose status changed. A cancellation
        request issued at the close is confirmed at the close (a request is
        not a confirmation until this step); partially filled orders may
        retain their fills when confirmed or expired.
        """
        changed: list[str] = []
        for order in self._orders.values():
            if order.time_in_force.value != "day":
                continue
            if order.status is NormalizedOrderStatus.CANCEL_PENDING:
                self._transition(
                    order,
                    NormalizedOrderStatus.CANCELLED,
                    at,
                    "cancel confirmed at session close; fills retained",
                )
                changed.append(order.order_id)
            elif order.status in (
                NormalizedOrderStatus.ACKNOWLEDGED,
                NormalizedOrderStatus.PARTIALLY_FILLED,
            ):
                self._transition(
                    order,
                    NormalizedOrderStatus.EXPIRED,
                    at,
                    "DAY time-in-force expired; reservation must be released",
                )
                changed.append(order.order_id)
        return changed

    def reconcile_unknown(self, at: datetime) -> list[str]:
        """Reconcile UNKNOWN orders against the venue's authoritative state.

        The local venue is always authoritative for itself: it knows whether
        the order was received. (For a real broker this step is a read query
        with backoff; it is never a blind resubmission.)
        """
        resolved: list[str] = []
        for order in self._orders.values():
            if order.status is not NormalizedOrderStatus.UNKNOWN:
                continue
            self._transition(
                order,
                NormalizedOrderStatus.ACKNOWLEDGED,
                at,
                "reconciliation: venue confirms the order was accepted; reservations retained",
            )
            resolved.append(order.order_id)
        return resolved

    # ------------------------------------------------------------- fills

    def _try_fill(self, order: Order, bar: MarketBar) -> Fill | None:
        remaining = order.remaining_quantity()
        if remaining <= 0:
            return None
        volume_cap = round_qty(bar.volume * self._config.risk.max_participation_fraction, 0)
        fill_qty = min(remaining, volume_cap)
        if fill_qty <= 0:
            return None
        if order.side is OrderSide.BUY:
            if bar.low > order.limit_price:
                return None
            price = min(order.limit_price, bar.low)
        else:
            if bar.high < order.limit_price:
                return None
            price = max(order.limit_price, bar.high)
        fee = round_money(fill_qty * price * self._config.engine.commission_bps / Decimal(10_000))
        self._order_seq[order.order_id] = self._order_seq.get(order.order_id, 0) + 1
        seq = self._order_seq[order.order_id]
        fill = Fill(
            fill_id=_hash_id("fill", self._run_id or "", order.order_id, str(seq)),
            run_id=self._run_id or "",
            order_id=order.order_id,
            instrument_id=order.instrument_id,
            side=order.side,
            ts=bar.ts,
            quantity=round_money(fill_qty),
            price=round_money(price),
            fee=fee,
            raw_fill_id=_hash_id("rawfill", self._run_id or "", order.order_id, str(seq)),
            source="simulator",
        )
        self._persist_fill(fill)
        order.filled_quantity = round_money(order.filled_quantity + fill_qty)
        order.last_fill_price = round_money(price)
        new_status = (
            NormalizedOrderStatus.FILLED
            if order.filled_quantity >= order.quantity
            else NormalizedOrderStatus.PARTIALLY_FILLED
        )
        self._transition(order, new_status, bar.ts, f"fill {fill_qty} @ {price}")
        return fill

    # ------------------------------------------------------- persistence

    def _persist_order(self, order: Order) -> None:
        assert self._session is not None
        self._session.execute(
            broker_orders.insert().values(
                order_id=order.order_id,
                run_id=order.run_id,
                intent_id=order.intent_id,
                client_order_id=order.client_order_id,
                account_alias=order.account_alias,
                instrument_id=order.instrument_id,
                side=order.side.value,
                order_type=order.order_type.value,
                limit_price=order.limit_price,
                quantity=order.quantity,
                time_in_force=order.time_in_force.value,
                status=order.status.value,
                raw_status=order.raw_status,
                filled_quantity=order.filled_quantity,
                created_at=order.created_at,
                updated_at=order.updated_at or order.created_at,
                expires_at=order.expires_at,
                cancel_requested_at=order.cancel_requested_at,
            )
        )

    def _persist_attempt(self, attempt: SubmissionAttempt) -> None:
        assert self._session is not None
        self._session.execute(
            submission_attempts.insert().values(
                attempt_id=attempt.attempt_id,
                run_id=attempt.run_id,
                order_id=attempt.order_id,
                request_digest=attempt.request_digest,
                submitted_at=attempt.submitted_at,
                outcome=attempt.outcome.value,
                raw_status=attempt.raw_status,
                error_class=attempt.error_class,
            )
        )

    def _persist_fill(self, fill: Fill) -> None:
        assert self._session is not None
        existing = self._session.execute(
            select(fills.c.fill_id).where(
                fills.c.run_id == fill.run_id, fills.c.raw_fill_id == fill.raw_fill_id
            )
        ).first()
        if existing is None:
            self._session.execute(
                fills.insert().values(
                    fill_id=fill.fill_id,
                    run_id=fill.run_id,
                    order_id=fill.order_id,
                    instrument_id=fill.instrument_id,
                    side=fill.side.value,
                    ts=fill.ts,
                    quantity=fill.quantity,
                    price=fill.price,
                    fee=fill.fee,
                    raw_fill_id=fill.raw_fill_id,
                    source=fill.source,
                    corrected_by=fill.corrected_by,
                )
            )

    def _transition(
        self, order: Order, to: NormalizedOrderStatus, at: datetime, reason: str
    ) -> None:
        from_status = order.status
        order.raw_status = to.value
        order.transition(to, at, reason)
        assert self._session is not None
        self._session.execute(
            broker_orders.update()
            .where(broker_orders.c.order_id == order.order_id)
            .values(
                status=order.status.value,
                raw_status=order.raw_status,
                filled_quantity=order.filled_quantity,
                updated_at=at,
                cancel_requested_at=order.cancel_requested_at,
            )
        )
        self._session.execute(
            order_events.insert().values(
                run_id=order.run_id,
                order_id=order.order_id,
                seq=len(order.events),
                ts=at,
                from_status=from_status.value,
                to_status=to.value,
                reason=reason,
            )
        )

    # -------------------------------------------------------------- state

    def _seed_submission_counter(self) -> None:
        if not self.bound:
            return
        assert self._session is not None
        row = self._session.execute(
            select(func.count())
            .select_from(submission_attempts)
            .where(submission_attempts.c.run_id == self._run_id)
        ).first()
        self._submissions_made = row[0] if row else 0

    def _loads_open_orders(self) -> None:
        if not self.bound:
            return
        assert self._session is not None
        rows = self._session.execute(
            select(broker_orders).where(
                broker_orders.c.run_id == self._run_id,
                broker_orders.c.status.in_([s.value for s in _OPEN_STATUSES]),
            )
        ).all()
        for row in rows:
            from ..contracts.orders import OrderType, TimeInForce

            order = Order(
                order_id=row.order_id,
                run_id=row.run_id,
                intent_id=row.intent_id,
                client_order_id=row.client_order_id,
                account_alias=row.account_alias,
                instrument_id=row.instrument_id,
                side=OrderSide(row.side),
                order_type=OrderType(row.order_type),
                limit_price=row.limit_price,
                quantity=row.quantity,
                time_in_force=TimeInForce(row.time_in_force),
                created_at=row.created_at,
                status=NormalizedOrderStatus(row.status),
                raw_status=row.raw_status,
                filled_quantity=row.filled_quantity,
                expires_at=row.expires_at,
                cancel_requested_at=row.cancel_requested_at,
            )
            order.events.append(
                (row.created_at, order.status, "loaded from database (restart safety)")
            )
            self._orders[row.client_order_id] = order
            # Continue the per-order fill sequence after any fills already
            # persisted for this order, so a resumed run never reuses a fill id.
            fill_count = self._session.execute(
                select(func.count()).select_from(fills).where(fills.c.order_id == row.order_id)
            ).scalar_one()
            self._order_seq[row.order_id] = fill_count

    def venue_state(self, as_of: datetime | None = None) -> VenueState:
        """The venue's own books, derived from its authoritative records.

        Cash is the modeled account balance (initial capital + fills + the
        documented daily cash-yield credits, sequenced session by session);
        positions come from the fill record. This is the independent view
        the reconciliation service compares against the application ledger.
        """
        assert self._session is not None and self._run_id is not None
        instant = as_of if as_of is not None else self._now_fn()
        positions: dict[str, Decimal] = {}
        last_ts: datetime | None = None
        rows = cast(
            "list[tuple[str, str, Decimal, datetime]]",
            self._session.execute(
                select(fills.c.side, fills.c.instrument_id, fills.c.quantity, fills.c.ts)
                .where(
                    fills.c.run_id == self._run_id,
                    fills.c.ts <= instant,
                    exists(
                        select(1)
                        .select_from(broker_orders)
                        .where(
                            broker_orders.c.order_id == fills.c.order_id,
                            broker_orders.c.run_id == fills.c.run_id,
                        )
                    ),
                )
                .order_by(fills.c.ts, fills.c.fill_id)
            ).all(),
        )
        for side, instrument_id, quantity, ts in rows:
            last_ts = ts if (last_ts is None or ts > last_ts) else last_ts
            positions[instrument_id] = positions.get(instrument_id, Decimal("0")) + (
                quantity if side == "buy" else -quantity
            )
        return VenueState(
            cash=self.account_cash(instant),
            positions={k: round_money(v) for k, v in sorted(positions.items()) if v != 0},
            open_orders=sum(1 for o in self._orders.values() if o.status in _OPEN_STATUSES),
            as_of=last_ts,
        )

    # ------------------------------------------------- documented cash yield

    def _session_ends(self) -> list[tuple[date, datetime]]:
        from ..engine.clock import ExchangeClock
        from ..fixtures.synthetic import business_sessions

        sessions = business_sessions(self._config.data.start_session, self._config.data.sessions)
        clock = ExchangeClock(self._config.app.exchange_timezone, sessions)
        return [(s, clock.ticks(s)[2]) for s in sessions]

    def _model_sequence(self, as_of: datetime) -> tuple[Decimal, list[Decimal]]:
        """Replay the account: initial cash, fills in chronological order, and
        one documented daily-yield credit per session end at or before ``as_of``.

        Mirrors the application ledger's exact operation order and rounding so
        that an honest reconciliation compares like with like. Returns the
        final cash and the per-session-end yield credits.
        """
        assert self._session is not None
        from ..strategies.baselines import daily_yield_factor

        factor = daily_yield_factor(self._config.engine.cash_yield_annual)
        rows = cast(
            "list[tuple[str, Decimal, Decimal, Decimal, datetime]]",
            self._session.execute(
                select(fills.c.side, fills.c.quantity, fills.c.price, fills.c.fee, fills.c.ts)
                .where(
                    fills.c.run_id == self._run_id,
                    exists(
                        select(1)
                        .select_from(broker_orders)
                        .where(
                            broker_orders.c.order_id == fills.c.order_id,
                            broker_orders.c.run_id == fills.c.run_id,
                        )
                    ),
                )
                .order_by(fills.c.ts, fills.c.fill_id)
            ).all(),
        )
        cash = self._initial_cash
        credits: list[Decimal] = []
        index = 0
        total = len(rows)
        for _, end in self._session_ends():
            if end > as_of:
                break
            # A cursor walks the sorted rows: apply every row at or before
            # this session's close, leaving the cursor on the first later row
            # for the next sweep. A session with no fills simply advances the
            # sweep without touching a row, so a row is never dropped.
            while index < total and rows[index][4] <= end:
                side, quantity, price, fee, _ = rows[index]
                index += 1
                if side == "buy":
                    cash = round_money(cash - round_money(quantity * price) - fee)
                else:
                    cash = round_money(cash + round_money(quantity * price) - fee)
            credit = round_money(cash * factor)
            credits.append(credit)
            cash = round_money(cash + credit)
        return cash, credits

    def account_cash(self, as_of: datetime) -> Decimal:
        """The venue's modeled account cash at ``as_of`` (see _model_sequence)."""
        if not self.bound:
            raise BrokerStateNotAvailable(
                "simulator has no run context bound; no account state to report"
            )
        cash, _ = self._model_sequence(as_of)
        return cash

    def cash_yield_credit(self, at: datetime) -> Decimal:
        """The single documented daily-yield credit due at the session end at/after ``at``.

        The pipeline applies this to the strategy ledger (the venue is the
        source of account-level yield events, exactly as a real broker would
        credit interest); the baselines accrue the same convention on their
        own books.
        """
        if not self.bound:
            return Decimal("0")
        _, credits = self._model_sequence(at)
        return credits[-1] if credits else Decimal("0")

    def open_order_ids(self) -> list[str]:
        return [order.order_id for order in self._orders.values() if order.status in _OPEN_STATUSES]

    def order(self, order_id: str) -> Order | None:
        for candidate in self._orders.values():
            if candidate.order_id == order_id:
                return candidate
        return None

    def order_status(self, order_id: str) -> NormalizedOrderStatus | None:
        order = self.order(order_id)
        return order.status if order is not None else None

    def terminal_order_ids(self, statuses: tuple[NormalizedOrderStatus, ...]) -> list[str]:
        return [order.order_id for order in self._orders.values() if order.status in statuses]

    def terminal_order_ids_any(self) -> list[str]:
        """Every in-memory order in a terminal state (fills, cancels, expiries)."""
        terminal = frozenset(
            {
                NormalizedOrderStatus.FILLED,
                NormalizedOrderStatus.CANCELLED,
                NormalizedOrderStatus.EXPIRED,
                NormalizedOrderStatus.REJECTED,
            }
        )
        return [order.order_id for order in self._orders.values() if order.status in terminal]


def _wall_clock() -> datetime:
    return datetime.now(UTC)


def _hash_id(prefix: str, *parts: str) -> str:
    return f"{prefix}-{hashlib.sha256('|'.join(parts).encode('utf-8')).hexdigest()[:32]}"
