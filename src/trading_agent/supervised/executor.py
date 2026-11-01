"""Privileged role and narrow command boundary, executable ONLY with exact FakeTransport.

A separate worker process hosts this verifier in the demo. It has no real broker
adapter, secret injection or network implementation. That deployment remains blocked.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Connection

from .contracts import (
    Approval,
    Fill,
    Holding,
    Intent,
    Order,
    Permit,
    Resume,
    Signed,
    State,
    digest,
    money_context,
    verify,
)
from .fake import FakeTransport, Observation
from .journal import Denied, Journal
from .readiness import evaluate

TERMINAL = {"filled", "cancelled", "rejected"}
UNCERTAIN = {"submission_pending", "unknown", "manual_review"}


class LiveExecutor:
    """Deliberately has no transport/factory argument and no dispatch implementation."""

    def dispatch(self, *_args: Any, **_kwargs: Any) -> None:
        raise Denied("LIVE_NOT_AUTHORIZED: real dispatch unavailable in this build")

    cancel = dispatch
    resume = dispatch


class MockControls:
    def __init__(self, journal: Journal) -> None:
        self.journal = journal

    @money_context
    def approve(self, intent: Intent, proof: Signed, *, now: datetime) -> None:
        approval = verify(proof, Approval)
        with self.journal.transaction() as conn:
            state = self.journal.state(conn, intent.account_key)
            report = evaluate(state, now=now, intent=intent, approval=approval)
            if not report.mock_controls_satisfied:
                raise Denied("approval prerequisites not met")
            conn.execute(
                self.journal.approvals.insert().values(
                    approval_id=approval.approval_id,
                    account_key=state.account_key,
                    intent_hash=intent.digest(),
                    document=proof.model_dump_json(),
                    consumed=False,
                    revoked=False,
                )
            )
            self.journal.event(
                conn,
                state,
                now,
                "mock_owner_approved",
                {
                    "approval": approval.model_dump(mode="json"),
                    "intent": intent.model_dump(mode="json"),
                },
            )

    def revoke(self, key: str, *, now: datetime, approval_id: str | None = None) -> None:
        with self.journal.transaction() as conn:
            state = self.journal.state(conn, key)
            if state.domain != "M6_MOCK_ONLY":
                raise Denied("M6 controls cannot address another authority domain")
            before = state
            if approval_id is not None:
                self.journal.approval(conn, key, approval_id)
                conn.execute(
                    self.journal.approvals.update()
                    .where(
                        self.journal.approvals.c.account_key == key,
                        self.journal.approvals.c.approval_id == approval_id,
                    )
                    .values(revoked=True)
                )
            else:
                state = state.changed(
                    epoch=state.epoch + 1, revoked=True, paused=True, resumed=False
                )
            state = self.journal.save(conn, state)
            self.journal.event(
                conn,
                state,
                now,
                "mock_approval_revoked" if approval_id else "mock_authority_revoked",
                {
                    "approval_id": approval_id,
                    "before": before.model_dump(mode="json"),
                    "after": state.model_dump(mode="json"),
                    "outstanding_orders_not_cancelled": True,
                },
            )

    def pause(self, key: str, *, now: datetime, shutdown: bool = False) -> None:
        with self.journal.transaction() as conn:
            state = self.journal.state(conn, key)
            if state.domain != "M6_MOCK_ONLY":
                raise Denied("M6 controls cannot address another authority domain")
            state = self.journal.save(conn, state.changed(paused=True, resumed=False))
            self.journal.event(
                conn,
                state,
                now,
                "mock_shutdown" if shutdown else "mock_paused",
                {"outstanding_orders_not_cancelled": True},
            )

    @money_context
    def resume(self, proof: Signed, *, now: datetime) -> None:
        request = verify(proof, Resume)
        with self.journal.transaction() as conn:
            state = self.journal.state(conn, request.account_key)
            if (
                request.state_revision != state.revision
                or request.boot_id != state.boot_id
                or request.epoch != state.epoch
                or not request.issued_at <= now < request.expires_at
                or any(
                    o.status in UNCERTAIN
                    for o in self.journal.account_orders(conn, state.account_key)
                )
            ):
                raise Denied("resume requires current boot, epoch, consent and resolved orders")
            report = evaluate(state, now=now, require_resume=False)
            skip = {
                "intent_bindings",
                "current_risk",
                "per_intent_owner_approval",
                "build_live_dispatch_disabled",
            }
            if any(not c.satisfied for c in report.checks if c.name not in skip):
                raise Denied("resume prerequisites not met")
            conn.execute(
                self.journal.approvals.insert().values(
                    approval_id=request.resume_id,
                    account_key=state.account_key,
                    intent_hash=request.digest(),
                    document=proof.model_dump_json(),
                    consumed=True,
                    revoked=False,
                )
            )
            state = self.journal.save(conn, state.changed(paused=False, resumed=True))
            self.journal.event(
                conn, state, now, "mock_explicit_resume", request.model_dump(mode="json")
            )


class MockExecutor:
    def __init__(
        self,
        journal: Journal,
        transport: FakeTransport,
        *,
        boot_id: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if type(transport) is not FakeTransport:
            raise Denied("only the exact injected offline FakeTransport is supported")
        self.journal = journal
        self.transport = transport
        self.boot_id = boot_id
        self.clock = clock or (lambda: datetime.now(UTC))
        self._failed = False
        self._generation: int | None = None

    def startup(self, key: str, *, now: datetime) -> None:
        with self.journal.transaction() as conn:
            state = self.journal.state(conn, key)
            if key != self.transport.account_key or not state.quote.instrument.startswith("MOCK_"):
                raise Denied("executor is restricted to fictional account/instruments")
            state = self.journal.save(
                conn,
                state.changed(
                    boot_id=self.boot_id,
                    executor_generation=state.executor_generation + 1,
                    resumed=False,
                    paused=True,
                ),
            )
            self._generation = state.executor_generation
            for order in self.journal.account_orders(conn, key):
                if order.status == "submission_pending":
                    self.journal.save_order(conn, order.changed(status="unknown"))
                    self.journal.event(
                        conn,
                        state,
                        now,
                        "mock_restart_unknown",
                        {"intent_id": order.intent.intent_id, "reserves_retained": True},
                    )
            self.journal.event(
                conn, state, now, "mock_startup_resume_required", {"boot_id": self.boot_id}
            )

    def _assert_fence(self, state: State) -> None:
        if (
            self._generation is None
            or self._generation != state.executor_generation
            or state.boot_id != self.boot_id
        ):
            raise Denied("stale executor generation; startup and new owner resume required")

    def _check_instance(self) -> None:
        if self._failed:
            raise Denied("executor audit/state failed; restart and reconcile before reuse")

    def _authorize(
        self,
        conn: Connection,
        state: State,
        intent: Intent,
        reference: str,
        *,
        now: datetime,
        consumed: bool,
        excluding_cash: Decimal = Decimal(0),
        excluding_entry: int = 0,
        excluding_turnover: Decimal = Decimal(0),
    ) -> Permit:
        proof, was_consumed, revoked = self.journal.approval(conn, state.account_key, reference)
        approval = verify(proof, Approval)
        report = evaluate(
            state,
            now=now,
            intent=intent,
            approval=approval,
            excluding_cash=excluding_cash,
            excluding_entry=excluding_entry,
            excluding_turnover=excluding_turnover,
        )
        if was_consumed != consumed or revoked or not report.mock_controls_satisfied:
            raise Denied("dispatch consent, replay or readiness check denied")
        return Permit(authorization_hash=approval.authorization_hash, report=report)

    def _consume(self, conn: Connection, state: State, reference: str) -> None:
        conn.execute(
            self.journal.approvals.update()
            .where(self.journal.approvals.c.approval_id == reference)
            .values(consumed=True)
        )

    @money_context
    def reserve(self, intent: Intent, approval_id: str, *, now: datetime) -> Order:
        self._check_instance()
        with self.journal.transaction() as conn:
            state = self.journal.state(conn, intent.account_key)
            self._assert_fence(state)
            if state.boot_id != self.boot_id or intent.account_key != self.transport.account_key:
                raise Denied("stale executor or account mismatch")
            permit = self._authorize(conn, state, intent, approval_id, now=now, consumed=False)
            report = permit.report
            other = self.journal.account_orders(conn, state.account_key)
            if any(o.status in UNCERTAIN for o in other):
                raise Denied("reconciliation blocker")
            if any(o.intent.intent_id == intent.intent_id for o in other):
                raise Denied("local intent already attempted; never automatically retry")
            if intent.side == "sell":
                held = sum(
                    (p.quantity for p in state.holdings if p.instrument == intent.instrument),
                    Decimal(0),
                )
                pending = sum(
                    (
                        o.remaining_quantity
                        for o in other
                        if o.intent.side == "sell"
                        and o.intent.instrument == intent.instrument
                        and o.status not in TERMINAL
                    ),
                    Decimal(0),
                )
                if held - pending < intent.quantity:
                    raise Denied("inventory already reserved")
            before = state
            cash = (
                intent.quantity * intent.price_upper + intent.max_fee
                if intent.side == "buy"
                else Decimal(0)
            )
            if cash > state.cash - state.reserved_cash:
                raise Denied("insufficient unreserved cash")
            state = self.journal.save(
                conn,
                state.changed(
                    reserved_cash=state.reserved_cash + cash,
                    entry_attempts=state.entry_attempts + (1 if intent.side == "buy" else 0),
                    daily_turnover=state.daily_turnover + intent.quantity * intent.price_upper,
                ),
            )
            order = Order(
                intent=intent,
                approval_id=approval_id,
                authorization_hash=permit.authorization_hash,
                epoch=state.epoch,
                boot_id=self.boot_id,
                status="submission_pending",
                reserved_cash=cash,
                remaining_quantity=intent.quantity,
                before_hash=before.digest(),
                executor_generation=state.executor_generation,
            )
            conn.execute(
                self.journal.orders.insert().values(
                    intent_id=intent.intent_id,
                    account_key=state.account_key,
                    approval_id=approval_id,
                    document=order.model_dump_json(),
                )
            )
            self._consume(conn, state, approval_id)
            self.journal.event(
                conn,
                state,
                now,
                "mock_reserved_before_submission",
                {
                    "intent": intent.model_dump(mode="json"),
                    "approval_id": approval_id,
                    "before": before.model_dump(mode="json"),
                    "after": state.model_dump(mode="json"),
                    "readiness": report.model_dump(mode="json"),
                    "attempt_id": intent.intent_id,
                },
            )
            return order

    @money_context
    def dispatch_reserved(self, key: str, intent_id: str, *, now: datetime) -> Order:
        self._check_instance()
        try:
            with self.journal.transaction() as conn:
                state = self.journal.state(conn, key)
                self._assert_fence(state)
                order = self.journal.order(conn, intent_id, key)
                permit = self._authorize(
                    conn,
                    state,
                    order.intent,
                    order.approval_id,
                    now=now,
                    consumed=True,
                    excluding_cash=order.reserved_cash,
                    excluding_entry=1 if order.intent.side == "buy" else 0,
                    excluding_turnover=order.intent.quantity * order.intent.price_upper,
                )
                report = permit.report
                if (
                    order.authorization_hash != permit.authorization_hash
                    or order.dispatch_started
                    or order.status != "submission_pending"
                    or order.boot_id != self.boot_id
                    or state.boot_id != self.boot_id
                    or order.epoch != state.epoch
                ):
                    raise Denied("immediate pre-dispatch validation denied")
                order = order.changed(dispatch_started=True)
                self.journal.save_order(conn, order)
                self.journal.event(
                    conn,
                    state,
                    now,
                    "mock_dispatch_started",
                    {"intent_id": intent_id, "readiness": report.model_dump(mode="json")},
                )
        except Denied:
            raise
        except Exception:
            self._failed = True
            raise
        # Attempt is already durable. Hold the account lock from the final clock/
        # authority check through the bounded fake call, serializing startup/revoke.
        try:
            with self.journal.transaction() as conn:
                current = self.journal.state(conn, key)
                self._assert_fence(current)
                clock_now = self.clock()
                permit = self._authorize(
                    conn,
                    current,
                    order.intent,
                    order.approval_id,
                    now=clock_now,
                    consumed=True,
                    excluding_cash=order.reserved_cash,
                    excluding_entry=1 if order.intent.side == "buy" else 0,
                    excluding_turnover=order.intent.quantity * order.intent.price_upper,
                )
                report = permit.report
                if (
                    current.epoch != order.epoch
                    or permit.authorization_hash != order.authorization_hash
                ):
                    raise Denied("final locked wire check denied")
                self.journal.event(
                    conn,
                    current,
                    clock_now,
                    "mock_final_wire_check",
                    {"intent_id": intent_id, "readiness": report.model_dump(mode="json")},
                )
                try:
                    response = self.transport.submit(order.intent)
                except Exception:
                    response = Observation(status="unknown")
            return self._observe(key, intent_id, response, now=self.clock())
        except Exception:
            self._failed = True
            raise

    def dispatch(self, intent: Intent, approval_id: str, *, now: datetime) -> Order:
        self.reserve(intent, approval_id, now=now)
        return self.dispatch_reserved(intent.account_key, intent.intent_id, now=now)

    @money_context
    def _apply_fill(
        self, conn: Connection, state: State, order: Order, fill: Fill, now: datetime
    ) -> tuple[State, Order]:
        previous = conn.execute(
            select(self.journal.fills.c.document).where(
                self.journal.fills.c.fill_id == fill.fill_id
            )
        ).scalar_one_or_none()
        if previous is not None:
            if Fill.model_validate_json(previous) != fill:
                raise Denied("conflicting fill correction requires review")
            return state, order
        intent = order.intent
        if (
            fill.order_id != intent.intent_id
            or fill.account_key != state.account_key
            or fill.instrument != intent.instrument
            or fill.side != intent.side
            or fill.quantity > order.remaining_quantity
            or not intent.price_lower <= fill.price <= intent.price_upper
            or order.fees + fill.fee > intent.max_fee
            or fill.at < intent.created_at
            or fill.at > now
            or fill.quantity != fill.quantity.to_integral_value()
        ):
            raise Denied("fill binding, bounds or cumulative amount invalid")
        position = next(
            (p for p in state.holdings if p.instrument == intent.instrument),
            Holding(instrument=intent.instrument, quantity=Decimal(0), average_cost=Decimal(0)),
        )
        cash = state.cash
        remaining = order.remaining_quantity - fill.quantity
        fee_total = order.fees + fill.fee
        with localcontext() as context:
            context.prec = 28
            if intent.side == "buy":
                cost = fill.quantity * fill.price + fill.fee
                if cash < cost:
                    raise Denied("fill would overspend")
                qty = position.quantity + fill.quantity
                avg = ((position.quantity * position.average_cost + cost) / qty).quantize(
                    Decimal("0.00000001")
                )
                position = position.changed(quantity=qty, average_cost=avg)
                cash -= cost
            else:
                if fill.quantity > position.quantity:
                    raise Denied("fill would create short")
                proceeds = fill.quantity * fill.price - fill.fee
                if cash + proceeds < 0:
                    raise Denied("fee would overspend")
                qty = position.quantity - fill.quantity
                position = position.changed(
                    quantity=qty,
                    average_cost=position.average_cost if qty else Decimal(0),
                    realized_pnl=position.realized_pnl
                    + proceeds
                    - fill.quantity * position.average_cost,
                )
                cash += proceeds
        reserve = (
            remaining * intent.price_upper + (intent.max_fee - fee_total)
            if intent.side == "buy" and remaining and order.status not in TERMINAL
            else Decimal(0)
        )
        updated = order.changed(
            remaining_quantity=remaining,
            filled_quantity=order.filled_quantity + fill.quantity,
            fees=fee_total,
            reserved_cash=reserve,
            status="filled"
            if remaining == 0
            else ("cancelled" if order.status == "cancelled" else "partially_filled"),
        )
        holdings = tuple(p for p in state.holdings if p.instrument != intent.instrument) + (
            position,
        )
        state = state.changed(
            cash=cash,
            holdings=holdings,
            reserved_cash=state.reserved_cash - order.reserved_cash + reserve,
            reconciliation=state.reconciliation.changed(status="unknown"),
            paused=True,
            resumed=False,
        )
        conn.execute(
            self.journal.fills.insert().values(
                fill_id=fill.fill_id,
                account_key=state.account_key,
                order_id=intent.intent_id,
                document=fill.model_dump_json(),
            )
        )
        self.journal.event(
            conn, state, now, "mock_fill_applied", {"fill": fill.model_dump(mode="json")}
        )
        return state, updated

    @money_context
    def _observe(self, key: str, intent_id: str, response: Observation, *, now: datetime) -> Order:
        with self.journal.transaction() as conn:
            state = self.journal.state(conn, key)
            self._assert_fence(state)
            before = state
            order = self.journal.order(conn, intent_id, key)
            if (
                response.status not in {"unknown", "rejected"}
                and response.broker_order_id is None
                or response.status == "broker_approval_required"
                and response.broker_approval_ref is None
                or order.broker_order_id is not None
                and response.broker_order_id is not None
                and order.broker_order_id != response.broker_order_id
            ):
                raise Denied("broker observation identity or approval requirement invalid")
            for fill in response.fills:
                state, order = self._apply_fill(conn, state, order, fill, now)
            if response.status == "filled" and order.remaining_quantity:
                raise Denied("filled status without complete fill evidence")
            if order.status == "filled" and response.status in {
                "rejected",
                "broker_approval_required",
            }:
                raise Denied("contradictory terminal observation")
            if response.status == "unknown":
                state = state.changed(
                    paused=True,
                    resumed=False,
                    reconciliation=state.reconciliation.changed(status="unknown"),
                )
            if order.status not in TERMINAL:
                status: str = response.status
                if status == "acknowledged" and order.filled_quantity:
                    status = "partially_filled"
                reserve = order.reserved_cash
                if status in {"cancelled", "rejected"}:
                    state = state.changed(reserved_cash=state.reserved_cash - reserve)
                    reserve = Decimal(0)
                if status == "unknown":
                    state = state.changed(
                        paused=True,
                        resumed=False,
                        reconciliation=state.reconciliation.changed(status="unknown"),
                    )
                order = order.changed(
                    status=status,
                    reserved_cash=reserve,
                    broker_order_id=response.broker_order_id or order.broker_order_id,
                    broker_approval_ref=response.broker_approval_ref or order.broker_approval_ref,
                )
            state = self.journal.save(conn, state)
            self.journal.save_order(conn, order)
            self.journal.event(
                conn,
                state,
                now,
                "mock_broker_observed",
                {
                    "intent_id": intent_id,
                    "observation": response.model_dump(mode="json"),
                    "before": before.model_dump(mode="json"),
                    "after": state.model_dump(mode="json"),
                    "order": order.model_dump(mode="json"),
                },
            )
            return order

    def reconcile_order(self, key: str, intent_id: str, *, now: datetime) -> Order:
        self._check_instance()
        with self.journal.transaction() as conn:
            self._assert_fence(self.journal.state(conn, key))
        response = self.transport.observe(intent_id)
        try:
            return self._observe(key, intent_id, response, now=now)
        except Exception:
            self._failed = True
            with self.journal.transaction() as conn:
                state = self.journal.state(conn, key)
                self._assert_fence(state)
                order = self.journal.order(conn, intent_id, key)
                state = self.journal.save(
                    conn,
                    state.changed(
                        paused=True,
                        resumed=False,
                        reconciliation=state.reconciliation.changed(status="failed", as_of=now),
                    ),
                )
                self.journal.save_order(conn, order.changed(status="manual_review"))
                self.journal.event(
                    conn,
                    state,
                    now,
                    "mock_observation_rejected",
                    {
                        "intent_id": intent_id,
                        "observation": response.model_dump(mode="json"),
                        "local_order_before_rejection": order.model_dump(mode="json"),
                        "reserves_retained": True,
                    },
                )
            raise

    @money_context
    def reconcile_account(
        self, key: str, *, cash: Decimal, holdings: tuple[Holding, ...], now: datetime
    ) -> bool:
        """Fixture broker facts only. Differences are preserved, never auto-reversed."""
        with self.journal.transaction() as conn:
            state = self.journal.state(conn, key)
            self._assert_fence(state)
            match = state.cash == cash and {
                p.instrument: p.quantity for p in state.holdings if p.quantity > 0
            } == {p.instrument: p.quantity for p in holdings if p.quantity > 0}
            known = not any(o.status in UNCERTAIN for o in self.journal.account_orders(conn, key))
            ok = match and known
            state = self.journal.save(
                conn,
                state.changed(
                    reconciliation=state.reconciliation.changed(
                        status="healthy" if ok else "failed", as_of=now
                    ),
                    account_as_of=now,
                    paused=True,
                    resumed=False,
                ),
            )
            self.journal.event(
                conn,
                state,
                now,
                "mock_reconciled" if ok else "mock_reconciliation_difference",
                {
                    "broker_cash": str(cash),
                    "broker_holdings": [p.model_dump(mode="json") for p in holdings],
                    "local_hash": state.digest(),
                    "explicit_resume_required": True,
                },
            )
            return ok

    @money_context
    def cancel(self, key: str, intent_id: str, approval: Signed, *, now: datetime) -> Order:
        """Separate exact signed MOCK cancellation intent; never auto-cancel on pause."""
        self._check_instance()
        request = verify(approval, Approval)
        with self.journal.transaction() as conn:
            state = self.journal.state(conn, key)
            self._assert_fence(state)
            order = self.journal.order(conn, intent_id, key)
            expected = digest(
                {"cancel": order.intent.digest(), "account_key": key, "epoch": state.epoch}
            )
            if (
                request.intent_hash != expected
                or request.epoch != state.epoch
                or request.authorization_hash != order.authorization_hash
                or not request.issued_at <= now < request.expires_at
                or order.status in TERMINAL
                or order.status in UNCERTAIN
                or key != self.transport.account_key
                or state.boot_id != self.boot_id
            ):
                raise Denied("cancellation scope, consent or state invalid")
            # unique approval id makes cancel replay fail before another transport call
            conn.execute(
                self.journal.approvals.insert().values(
                    approval_id=request.approval_id,
                    account_key=key,
                    intent_hash=expected,
                    document=approval.model_dump_json(),
                    consumed=True,
                    revoked=False,
                )
            )
            self.journal.save_order(conn, order.changed(status="cancel_pending"))
            self.journal.event(
                conn,
                state,
                now,
                "mock_cancel_requested",
                {
                    "intent_id": intent_id,
                    "approval": request.model_dump(mode="json"),
                    "reserves_retained": True,
                },
            )
        with self.journal.transaction() as conn:
            current = self.journal.state(conn, key)
            self._assert_fence(current)
            if (
                current.epoch != request.epoch
                or current.boot_id != self.boot_id
                or not request.issued_at <= self.clock() < request.expires_at
            ):
                raise Denied("final cancellation clock/epoch check denied")
            self.journal.event(
                conn, current, self.clock(), "mock_final_cancel_check", {"intent_id": intent_id}
            )
            try:
                result = self.transport.cancel(intent_id)
            except Exception:
                result = Observation(status="unknown")
        try:
            return self._observe(key, intent_id, result, now=now)
        except Exception:
            self._failed = True
            raise
