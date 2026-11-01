"""Account-wide observed facts, strict scope/freshness and non-mutating comparison.

Never imports an OAuth client, reads a token, adopts a manual trade or changes
cash/holdings. A partial observation is never an empty account.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal, Self, cast

from pydantic import AwareDatetime, BeforeValidator, Field, model_validator
from sqlalchemy.engine import Connection

from ..supervised.contracts import Digest, Identifier, Record, digest
from .journal import record


def exact(value: object) -> Decimal:
    if not isinstance(value, (str, Decimal)):
        raise ValueError("exact decimal string required")
    try:
        amount = Decimal(value)
    except InvalidOperation:
        raise ValueError("invalid financial amount") from None
    if not amount.is_finite():
        raise ValueError("nonfinite financial value")
    return amount


Number = Annotated[Decimal, BeforeValidator(exact), Field(max_digits=32, decimal_places=18)]
Nonnegative = Annotated[Number, Field(ge=0)]


class Position(Record):
    asset_class: Literal["equity", "option", "crypto", "other"]
    instrument: Identifier
    quantity: Number


class OpenOrder(Record):
    order_key: Digest
    instrument: Identifier
    side: Literal["buy", "sell"]
    remaining: Nonnegative | None
    status: Literal["working", "cancel_pending", "unknown", "approval_required"]


class Inventory(Record):
    account_key: Digest
    run_id: Identifier
    mode: Literal["simulation", "shadow"]
    currency: Literal["USD"]
    schema_hash: Digest
    started_at: AwareDatetime
    completed_at: AwareDatetime
    source: Literal["FIXTURE", "OWNER_RUNTIME_OBSERVATION"]
    complete: bool
    corrects_snapshot_hash: Digest | None = None
    cash: Number | None
    unleveraged_buying_power: Number | None
    settled_cash: Number | None = None
    positions: tuple[Position, ...]
    orders: tuple[OpenOrder, ...]
    pending_approvals: tuple[Digest, ...] = ()
    # One independently completed page sequence for each account-wide collection.
    collections: tuple[Identifier, ...]

    @model_validator(mode="after")
    def valid(self) -> Self:
        if self.completed_at < self.started_at:
            raise ValueError("observation interval reversed")
        identities = [(p.asset_class, p.instrument) for p in self.positions]
        if len(identities) != len(set(identities)) or len(
            {o.order_key for o in self.orders}
        ) != len(self.orders):
            raise ValueError("duplicate position/order evidence")
        if len(self.pending_approvals) != len(set(self.pending_approvals)):
            raise ValueError("duplicate approval evidence")
        return self


COLLECTIONS = frozenset(
    {
        "portfolio",
        "equity_positions",
        "option_positions",
        "crypto_positions",
        "equity_orders",
        "option_orders",
        "crypto_orders",
        "advanced_orders",
        "approvals",
    }
)


class LedgerView(Record):
    account_key: Digest
    run_id: Identifier
    mode: Literal["simulation", "shadow"]
    currency: Literal["USD"] = "USD"
    cash: Number
    positions: tuple[Position, ...]
    orders: tuple[OpenOrder, ...]
    audit_healthy: bool
    unresolved_events: tuple[Identifier, ...] = ()

    @model_validator(mode="after")
    def unique(self) -> Self:
        if len({(p.asset_class, p.instrument) for p in self.positions}) != len(
            self.positions
        ) or len({o.order_key for o in self.orders}) != len(self.orders):
            raise ValueError("duplicate local accounting evidence")
        return self


class Comparison(Record):
    account_key: Digest
    run_id: Identifier
    mode: Literal["simulation", "shadow"]
    as_of: AwareDatetime
    source: Literal["FIXTURE", "OWNER_RUNTIME_OBSERVATION"]
    snapshot_hash: Digest
    inventory_record_id: Digest
    ledger_record_id: Digest
    approved_schema_hash: Digest
    max_age_seconds: int = Field(ge=0)
    max_snapshot_span_seconds: int = Field(ge=0)
    ledger_hash: Digest
    differences: tuple[Identifier, ...]
    consistent: bool
    settled_funds_verified: bool
    actual_dispatch_allowed: Literal[False] = False


def compare(
    observed: Inventory,
    ledger: LedgerView,
    *,
    now: datetime,
    approved_schema: str,
    max_age_seconds: int = 10,
    max_snapshot_span_seconds: int = 5,
) -> Comparison:
    if now.tzinfo is None or max_age_seconds < 0 or max_snapshot_span_seconds < 0:
        raise ValueError("invalid comparison clock/budget")
    issues = []
    if (observed.account_key, observed.run_id, observed.mode, observed.currency) != (
        ledger.account_key,
        ledger.run_id,
        ledger.mode,
        ledger.currency,
    ):
        issues.append("scope_mismatch")
    if (observed.mode == "simulation") != (observed.source == "FIXTURE"):
        issues.append("source_mode_mismatch")
    if observed.schema_hash != approved_schema:
        issues.append("schema_drift")
    if (
        not observed.complete
        or set(observed.collections) != COLLECTIONS
        or len(observed.collections) != len(COLLECTIONS)
    ):
        issues.append("incomplete_observation")
    if not 0 <= (now - observed.completed_at).total_seconds() <= max_age_seconds:
        issues.append("stale_or_future_observation")
    if (observed.completed_at - observed.started_at).total_seconds() > max_snapshot_span_seconds:
        issues.append("inconsistent_snapshot_window")
    if observed.unleveraged_buying_power is None or observed.unleveraged_buying_power < 0:
        issues.append("buying_power_unknown_or_negative")
    if observed.cash is not None and observed.cash < 0:
        issues.append("cash_deficit")
    if observed.cash is None:
        issues.append("cash_unknown")
    elif observed.cash != ledger.cash:
        issues.append("cash_difference")

    def positions(rows: tuple[Position, ...]) -> dict[tuple[str, str], Decimal]:
        return {(p.asset_class, p.instrument): p.quantity for p in rows if p.quantity}

    if positions(observed.positions) != positions(ledger.positions):
        issues.append("position_difference")
    if {o.order_key: o for o in observed.orders} != {o.order_key: o for o in ledger.orders}:
        issues.append("order_difference")
    if any(o.status != "working" or o.remaining is None for o in observed.orders):
        issues.append("unresolved_order_state")
    if observed.pending_approvals:
        issues.append("pending_broker_approval")
    if not ledger.audit_healthy:
        issues.append("audit_unhealthy")
    if ledger.unresolved_events:
        issues.append("unresolved_ledger_events")
    return Comparison(
        account_key=ledger.account_key,
        run_id=ledger.run_id,
        mode=ledger.mode,
        as_of=now,
        source=observed.source,
        snapshot_hash=observed.digest(),
        inventory_record_id=digest(
            {
                "scope": ledger.account_key,
                "kind": "inventory",
                "document": observed.model_dump(mode="json"),
            }
        ),
        ledger_record_id=digest(
            {
                "scope": ledger.account_key,
                "kind": "ledger_reference",
                "document": ledger.model_dump(mode="json"),
            }
        ),
        approved_schema_hash=approved_schema,
        max_age_seconds=max_age_seconds,
        max_snapshot_span_seconds=max_snapshot_span_seconds,
        ledger_hash=ledger.digest(),
        differences=tuple(issues),
        consistent=not issues,
        settled_funds_verified=observed.settled_cash is not None and observed.settled_cash >= 0,
    )


def persist(conn: Connection, observed: Inventory, ledger: LedgerView, result: Comparison) -> str:
    if (result.snapshot_hash, result.ledger_hash) != (observed.digest(), ledger.digest()):
        raise ValueError("comparison evidence binding mismatch")
    if (
        compare(
            observed,
            ledger,
            now=result.as_of,
            approved_schema=result.approved_schema_hash,
            max_age_seconds=result.max_age_seconds,
            max_snapshot_span_seconds=result.max_snapshot_span_seconds,
        )
        != result
    ):
        raise ValueError("forged comparison result")
    # Preserve failed snapshots and corrections as new records, never rewrite the ledger.
    record(conn, ledger.account_key, "inventory", observed.model_dump(mode="json"))
    record(conn, ledger.account_key, "ledger_reference", ledger.model_dump(mode="json"))
    return record(conn, ledger.account_key, "reconciliation", result.model_dump(mode="json"))


def persisted_ledger_view(
    session: object,
    *,
    run_id: str,
    account_key: str,
    expected_account_alias: str,
    audit_healthy: bool = False,
) -> LedgerView:
    """Adapt the existing authoritative ledger; never seed an empty book or flush it."""
    from sqlalchemy import func, select
    from sqlalchemy.orm import Session as DbSession

    from ..db.schema import broker_orders, instruments, ledger_events, runs
    from ..ledger.ledger import Ledger

    if not isinstance(session, DbSession):
        raise TypeError("existing financial database session required")
    run = session.execute(select(runs).where(runs.c.run_id == run_id)).one()
    if run.account_alias != expected_account_alias or run.mode not in {"simulation", "shadow"}:
        raise ValueError("ledger read scope mismatch")
    count = session.execute(
        select(func.count())
        .select_from(ledger_events)
        .where(ledger_events.c.run_id == run_id, ledger_events.c.portfolio_key == "strategy")
    ).scalar_one()
    if not count:
        raise ValueError("missing ledger history cannot be seeded by reconciliation")
    # The run is the ledger account boundary; ledger_events has no account column.
    if session.execute(
        select(func.count())
        .select_from(broker_orders)
        .where(
            broker_orders.c.run_id == run_id,
            broker_orders.c.account_alias != expected_account_alias,
        )
    ).scalar_one():
        raise ValueError("cross-account order evidence")
    ledger = Ledger(
        session,
        run_id=run_id,
        portfolio_key="strategy",
        account_alias=expected_account_alias,
        initial_cash=run.initial_cash,
        initial_ts=run.created_at,
        fencing_token=run.fencing_token,
    )
    asset_classes = {
        row.instrument_id: (
            "equity"
            if row.asset_class == "synthetic-equity"
            and row.is_synthetic
            and run.mode == "simulation"
            else row.asset_class
        )
        for row in session.execute(select(instruments).where(instruments.c.run_id == run_id))
    }
    positions = tuple(
        Position(
            asset_class=cast(
                Literal["equity", "option", "crypto", "other"], asset_classes.get(symbol)
            )
            if asset_classes.get(symbol) in {"equity", "option", "crypto"}
            else "other",
            instrument=symbol,
            quantity=position.quantity,
        )
        for symbol, position in sorted(ledger.positions.items())
        if position.quantity
    )
    open_orders = []
    for order in session.execute(
        select(broker_orders).where(
            broker_orders.c.run_id == run_id,
            broker_orders.c.account_alias == expected_account_alias,
        )
    ):
        if order.status in {"filled", "cancelled", "expired", "rejected"}:
            continue
        status = (
            "working"
            if order.status in {"acknowledged", "partially_filled"}
            else "cancel_pending"
            if order.status == "cancel_pending"
            else "unknown"
        )
        open_orders.append(
            OpenOrder(
                order_key=digest(order.order_id),
                instrument=order.instrument_id,
                side=order.side,
                remaining=order.quantity - order.filled_quantity,
                status=cast(
                    Literal["working", "cancel_pending", "unknown", "approval_required"], status
                ),
            )
        )
    return LedgerView(
        account_key=account_key,
        run_id=run_id,
        mode=run.mode,
        cash=ledger.cash,
        positions=positions,
        orders=tuple(open_orders),
        audit_healthy=audit_healthy,
    )
