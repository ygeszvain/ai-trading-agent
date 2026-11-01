"""Scoped, read-only queries backing the website (docs/website.md section 4).

Every function:

- opens nothing and writes nothing (the caller passes a read-only session);
- scopes by account alias / mode / run id / strategy version, enforced here,
  never in the templates;
- serializes money as exact decimal strings and timestamps as ISO-8601;
- reports stale / missing data truthfully (a gap is a gap; no fabricated
  prices);
- wraps results in the documented envelope: scope, as_of/watermark,
  provenance, quality_flags, pagination, payload.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config.models import TradingConfig
from ..db.schema import (
    broker_orders,
    decisions,
    fills,
    instruments,
    ledger_events,
    market_bars,
    order_events,
    order_intents,
    portfolio_snapshots,
    reconciliation_runs,
    reservations,
    risk_evaluations,
    runs,
    submission_attempts,
)
from ..engine.pipeline import CASH_BOOK, PASSIVE_BOOK, STRATEGY_BOOK
from ..engine.report import _session_gap
from ..money import round_money

BOOK_LABELS = {
    STRATEGY_BOOK: "Strategy (trend-momentum)",
    CASH_BOOK: "Cash baseline",
    PASSIVE_BOOK: "Passive basket baseline",
}


def _money(value: Any) -> str | None:
    if value is None:
        return None
    return str(value.normalize()) if isinstance(value, Decimal) else str(value)


def _iso(value: Any) -> str | None:
    if value is None or not hasattr(value, "isoformat"):
        return None
    return value.isoformat()


def _scope(config: TradingConfig, run: Any | None) -> dict[str, str | None]:
    return {
        "account_alias": run.account_alias if run is not None else None,
        "mode": (run.mode if run is not None else None) and str(run.mode).upper(),
        "run_id": run.run_id if run is not None else None,
        "strategy_version": run.strategy_version if run is not None else None,
    }


def _run_watermark(session: Session, run_id: str) -> datetime | None:
    return session.execute(
        select(func.max(market_bars.c.ts)).where(market_bars.c.run_id == run_id)
    ).scalar_one()


def _envelope(
    *,
    session: Session,
    config: TradingConfig,
    run: Any | None,
    as_of: datetime | None,
    quality_flags: list[str] | None = None,
    pagination: dict[str, Any] | None = None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    watermark = _run_watermark(session, run.run_id) if run is not None else None
    return {
        "scope": _scope(config, run),
        "as_of": _iso(as_of),
        "watermark": _iso(watermark),
        "provenance": {
            "data_source": run.data_source if run is not None else None,
            "data_snapshot_id": run.data_snapshot_id if run is not None else None,
            "ledger": "persisted ledger_events (authoritative)",
        },
        "quality_flags": quality_flags or [],
        "pagination": pagination or {},
        "payload": payload,
    }


def resolve_run(session: Session, run_id: str | None) -> Any | None:
    if run_id is None:
        return session.execute(
            select(runs).order_by(runs.c.created_at.desc()).limit(1)
        ).scalar_one_or_none()
    return session.execute(select(runs).where(runs.c.run_id == run_id)).scalar_one_or_none()


def list_runs(session: Session, config: TradingConfig) -> dict[str, Any]:
    rows = session.execute(select(runs).order_by(runs.c.created_at.desc())).scalars()
    items = [
        {
            "run_id": row.run_id,
            "status": row.status,
            "mode": str(row.mode).upper(),
            "account_alias": row.account_alias,
            "strategy_version": row.strategy_version,
            "data_source": row.data_source,
            "created_at": _iso(row.created_at),
            "completed_at": _iso(row.completed_at),
            "initial_cash": _money(row.initial_cash),
        }
        for row in rows
    ]
    return _envelope(session=session, config=config, run=None, as_of=None, payload={"runs": items})


def get_overview(session: Session, config: TradingConfig, run_id: str | None) -> dict[str, Any]:
    run = resolve_run(session, run_id)
    if run is None:
        return _envelope(
            session=session,
            config=config,
            run=None,
            as_of=None,
            quality_flags=["no-runs"],
            payload={
                "note": "no completed or running executions recorded yet",
                "books": [],
            },
        )
    books: list[dict[str, Any]] = []
    for key in (STRATEGY_BOOK, CASH_BOOK, PASSIVE_BOOK):
        row = (
            session.execute(
                select(portfolio_snapshots)
                .where(
                    portfolio_snapshots.c.run_id == run.run_id,
                    portfolio_snapshots.c.portfolio_key == key,
                )
                .order_by(portfolio_snapshots.c.ts.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if row is None:
            continue
        books.append(
            {
                "key": key,
                "label": BOOK_LABELS.get(key, key),
                "equity": _money(row.equity),
                "cash": _money(row.cash),
                "gross_exposure": _money(row.gross_exposure),
                "reconciliation_status": row.reconciliation_status,
                "as_of": _iso(row.ts),
            }
        )
    counts = {
        "decisions": session.execute(
            select(func.count()).select_from(decisions).where(decisions.c.run_id == run.run_id)
        ).scalar_one(),
        "orders": session.execute(
            select(func.count())
            .select_from(broker_orders)
            .where(broker_orders.c.run_id == run.run_id)
        ).scalar_one(),
        "fills": session.execute(
            select(func.count()).select_from(fills).where(fills.c.run_id == run.run_id)
        ).scalar_one(),
    }
    instruments = get_instrument_quality(session, run.run_id)
    flags: list[str] = []
    for status in instruments:
        if status["quality"] in ("stale", "missing"):
            flags.append("stale-or-missing-data")
    recon = session.execute(
        select(reconciliation_runs.c.status, func.count())
        .where(reconciliation_runs.c.run_id == run.run_id)
        .group_by(reconciliation_runs.c.status)
    ).all()
    last_recon = session.execute(
        select(reconciliation_runs.c.status, reconciliation_runs.c.completed_at)
        .where(reconciliation_runs.c.run_id == run.run_id)
        .order_by(reconciliation_runs.c.completed_at.desc())
        .limit(1)
    ).first()
    return _envelope(
        session=session,
        config=config,
        run=run,
        as_of=last_recon[1] if last_recon else None,
        quality_flags=flags,
        payload={
            "label": "SIMULATION",
            "run_status": run.status,
            "initial_cash": _money(run.initial_cash),
            "books": books,
            "counts": counts,
            "data_status": instruments,
            "reconciliation": {
                "last_status": last_recon[0] if last_recon else "unverified",
                "sessions": {status: count for status, count in recon},
            },
            "authority": config.authority(),
        },
    )


def get_equity_curve(session: Session, config: TradingConfig, run_id: str | None) -> dict[str, Any]:
    run = resolve_run(session, run_id)
    if run is None:
        return _envelope(
            session=session, config=config, run=None, as_of=None, payload={"series": []}
        )
    rows = (
        session.execute(
            select(
                portfolio_snapshots.c.portfolio_key,
                portfolio_snapshots.c.ts,
                portfolio_snapshots.c.equity,
                portfolio_snapshots.c.cash,
            )
            .where(portfolio_snapshots.c.run_id == run.run_id)
            .order_by(portfolio_snapshots.c.ts)
        )
    ).all()
    series = [
        {
            "book": row.portfolio_key,
            "label": BOOK_LABELS.get(row.portfolio_key, row.portfolio_key),
            "ts": _iso(row.ts),
            "equity": _money(row.equity),
            "cash": _money(row.cash),
        }
        for row in rows
    ]
    return _envelope(
        session=session,
        config=config,
        run=run,
        as_of=rows[-1].ts if rows else None,
        payload={
            "series": series,
            "note": (
                "chart coordinates are display approximations; amounts are exact decimal strings"
            ),
        },
    )


def get_health(session: Session, config: TradingConfig, run_id: str | None) -> dict[str, Any]:
    run = resolve_run(session, run_id)
    watermark = _run_watermark(session, run.run_id) if run is not None else None
    last_recon = (
        session.execute(
            select(reconciliation_runs.c.status)
            .where(reconciliation_runs.c.run_id == run.run_id)
            .order_by(reconciliation_runs.c.completed_at.desc())
            .limit(1)
        ).first()
        if run is not None
        else None
    )
    return _envelope(
        session=session,
        config=config,
        run=run,
        as_of=watermark,
        quality_flags=[flag for flag in ("stale-or-missing-data",) if run is None],
        payload={
            "database": "ok",
            "web": "ok",
            "run": (
                {"run_id": run.run_id, "status": run.status}
                if run is not None
                else {"run_id": None, "status": "no-runs"}
            ),
            "last_reconciliation": last_recon[0] if last_recon else "unverified",
            "model_inference": "disabled (M1 reads never invoke model inference)",
            "broker_access": "none (no broker connection in simulation)",
            "authority": config.authority(),
        },
    )


def get_activity(
    session: Session,
    config: TradingConfig,
    run_id: str | None,
    cursor: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    limit = max(1, min(int(limit), 100))
    run = resolve_run(session, run_id)
    if run is None:
        return _envelope(
            session=session,
            config=config,
            run=None,
            as_of=None,
            payload={"events": [], "next_cursor": None},
        )
    from ..db.schema import activity_events

    query = select(activity_events).where(activity_events.c.run_id == run.run_id)
    if cursor is not None:
        query = query.where(activity_events.c.cursor < int(cursor))
    rows = (
        session.execute(query.order_by(activity_events.c.cursor.desc()).limit(limit + 1))
    ).scalars()
    items = list(rows)
    has_more = len(items) > limit
    events = [
        {
            "event_id": row.event_id,
            "cursor": row.cursor,
            "ts": _iso(row.ts),
            "origin": row.origin,
            "event_type": row.event_type,
            "correlation": row.correlation,
            "payload": row.payload,
            "corrected_by": row.corrected_by,
        }
        for row in items[:limit]
    ]
    next_cursor = str(items[limit - 1].cursor) if has_more and items else None
    return _envelope(
        session=session,
        config=config,
        run=run,
        as_of=events[0]["ts"] if events else None,
        pagination={"limit": limit, "next_cursor": next_cursor},
        payload={"events": events},
    )


def get_orders(
    session: Session, config: TradingConfig, run_id: str | None, status: str | None = None
) -> dict[str, Any]:
    run = resolve_run(session, run_id)
    if run is None:
        return _envelope(
            session=session, config=config, run=None, as_of=None, payload={"orders": []}
        )
    query = select(broker_orders).where(broker_orders.c.run_id == run.run_id)
    if status is not None:
        query = query.where(broker_orders.c.status == status)
    rows = session.execute(query.order_by(broker_orders.c.created_at)).scalars()
    orders = [
        {
            "order_id": row.order_id,
            "client_order_id": row.client_order_id,
            "instrument_id": row.instrument_id,
            "side": row.side,
            "limit_price": _money(row.limit_price),
            "quantity": _money(row.quantity),
            "filled_quantity": _money(row.filled_quantity),
            "status": row.status,
            "created_at": _iso(row.created_at),
            "updated_at": _iso(row.updated_at),
        }
        for row in rows
    ]
    return _envelope(
        session=session, config=config, run=run, as_of=None, payload={"orders": orders}
    )


def get_fills(
    session: Session,
    config: TradingConfig,
    run_id: str | None,
    order_id: str | None = None,
) -> dict[str, Any]:
    run = resolve_run(session, run_id)
    if run is None:
        return _envelope(
            session=session, config=config, run=None, as_of=None, payload={"fills": []}
        )
    query = select(fills).where(fills.c.run_id == run.run_id)
    if order_id is not None:
        query = query.where(fills.c.order_id == order_id)
    rows = session.execute(query.order_by(fills.c.ts)).scalars()
    fills_list = [
        {
            "fill_id": row.fill_id,
            "order_id": row.order_id,
            "instrument_id": row.instrument_id,
            "side": row.side,
            "ts": _iso(row.ts),
            "quantity": _money(row.quantity),
            "price": _money(row.price),
            "fee": _money(row.fee),
            "source": row.source,
            "corrected_by": row.corrected_by,
        }
        for row in rows
    ]
    return _envelope(
        session=session, config=config, run=run, as_of=None, payload={"fills": fills_list}
    )


def get_order_detail(
    session: Session, config: TradingConfig, run_id: str | None, order_id: str
) -> dict[str, Any]:
    """Full trace: decision -> risk -> intent -> attempts -> order -> fills
    -> reservations -> ledger events, exactly as persisted."""
    run = resolve_run(session, run_id)
    if run is None:
        return _envelope(
            session=session, config=config, run=None, as_of=None, payload={"error": "no-run"}
        )
    order = (
        session.execute(
            select(broker_orders).where(
                broker_orders.c.run_id == run.run_id,
                broker_orders.c.order_id == order_id,
            )
        )
        .scalars()
        .first()
    )
    if order is None:
        return _envelope(
            session=session,
            config=config,
            run=run,
            as_of=None,
            quality_flags=["not-found"],
            payload={"error": f"order {order_id} not found for this run"},
        )
    intent = (
        session.execute(
            select(order_intents).where(
                order_intents.c.run_id == run.run_id, order_intents.c.intent_id == order.intent_id
            )
        )
        .scalars()
        .first()
    )
    decision = None
    if intent is not None:
        decision = (
            session.execute(
                select(decisions).where(
                    decisions.c.run_id == run.run_id,
                    decisions.c.decision_id == intent.decision_id,
                )
            )
            .scalars()
            .first()
        )
    risk = None
    if decision is not None:
        risk = (
            session.execute(
                select(risk_evaluations).where(
                    risk_evaluations.c.run_id == run.run_id,
                    risk_evaluations.c.decision_id == decision.decision_id,
                )
            )
            .scalars()
            .first()
        )
    attempts = [
        {
            "attempt_id": row.attempt_id,
            "submitted_at": _iso(row.submitted_at),
            "outcome": row.outcome,
            "raw_status": row.raw_status,
            "error_class": row.error_class,
        }
        for row in session.execute(
            select(submission_attempts)
            .where(
                submission_attempts.c.run_id == run.run_id,
                submission_attempts.c.order_id == order_id,
            )
            .order_by(submission_attempts.c.submitted_at)
        ).scalars()
    ]
    events = [
        {
            "seq": row.seq,
            "ts": _iso(row.ts),
            "from_status": row.from_status,
            "to_status": row.to_status,
            "reason": row.reason,
        }
        for row in session.execute(
            select(order_events)
            .where(order_events.c.run_id == run.run_id, order_events.c.order_id == order_id)
            .order_by(order_events.c.seq)
        ).scalars()
    ]
    fills_list = [
        {
            "fill_id": row.fill_id,
            "ts": _iso(row.ts),
            "side": row.side,
            "quantity": _money(row.quantity),
            "price": _money(row.price),
            "fee": _money(row.fee),
        }
        for row in session.execute(
            select(fills)
            .where(fills.c.run_id == run.run_id, fills.c.order_id == order_id)
            .order_by(fills.c.ts)
        ).scalars()
    ]
    fill_ids = [fill["fill_id"] for fill in fills_list]
    vwap: dict[str, Any] = {}
    for side in ("buy", "sell"):
        parts = [
            (Decimal(fill["quantity"]), Decimal(fill["price"]))
            for fill in fills_list
            if fill["side"] == side and fill["quantity"] is not None and fill["price"] is not None
        ]
        if parts:
            total_qty = sum(qty for qty, _ in parts)
            if total_qty > 0:
                vwap[side] = str(round_money(sum(qty * price for qty, price in parts) / total_qty))
    reservation_rows = session.execute(
        select(reservations).where(
            reservations.c.run_id == run.run_id,
            reservations.c.order_id == order_id,
        )
    ).scalars()
    reservation_list = [
        {
            "reservation_id": row.reservation_id,
            "kind": row.kind,
            "amount": _money(row.amount),
            "status": row.status,
            "reserved_at": _iso(row.reserved_at),
            "resolved_at": _iso(row.resolved_at),
        }
        for row in reservation_rows
    ]
    ledger = [
        {
            "event_id": row.event_id,
            "ts": _iso(row.ts),
            "kind": row.kind,
            "quantity": _money(row.quantity),
            "price": _money(row.price),
            "fee": _money(row.fee),
            "cash_after": _money(row.cash_after),
            "position_after": _money(row.position_after),
            "note": row.note,
        }
        for row in session.execute(
            select(ledger_events)
            .where(
                ledger_events.c.run_id == run.run_id,
                ledger_events.c.ref_id.in_(fill_ids)
                if fill_ids
                else ledger_events.c.ref_id.is_(None),
            )
            .order_by(ledger_events.c.ts)
        ).scalars()
        if not (fill_ids and row.ref_id not in fill_ids)
    ]
    return _envelope(
        session=session,
        config=config,
        run=run,
        as_of=order.updated_at,
        payload={
            "order": {
                "order_id": order.order_id,
                "client_order_id": order.client_order_id,
                "instrument_id": order.instrument_id,
                "side": order.side,
                "limit_price": _money(order.limit_price),
                "quantity": _money(order.quantity),
                "filled_quantity": _money(order.filled_quantity),
                "time_in_force": order.time_in_force,
                "status": order.status,
                "raw_status": order.raw_status,
                "created_at": _iso(order.created_at),
                "updated_at": _iso(order.updated_at),
                "cancel_requested_at": _iso(order.cancel_requested_at),
            },
            "intent": (
                {
                    "intent_id": intent.intent_id,
                    "client_order_id": intent.client_order_id,
                    "side": intent.side,
                    "quantity": _money(intent.quantity),
                    "limit_price": _money(intent.limit_price),
                    "created_at": _iso(intent.created_at),
                }
                if intent is not None
                else None
            ),
            "decision": (
                {
                    "decision_id": decision.decision_id,
                    "action": decision.action,
                    "target_weight": _money(decision.target_weight),
                    "rationale": decision.rationale,
                    "invalidation": decision.invalidation,
                    "decision_at": _iso(decision.decision_at),
                    "strategy_version": decision.strategy_version,
                }
                if decision is not None
                else None
            ),
            "risk_evaluation": (
                {
                    "outcome": risk.outcome,
                    "reasons": risk.reasons,
                    "limits": risk.limits,
                    "evaluated_at": _iso(risk.evaluated_at),
                }
                if risk is not None
                else None
            ),
            "attempts": attempts,
            "events": events,
            "fills": fills_list,
            "vwap": vwap,
            "reservations": reservation_list,
            "ledger_events": ledger,
        },
    )


def get_positions(session: Session, config: TradingConfig, run_id: str | None) -> dict[str, Any]:
    run = resolve_run(session, run_id)
    if run is None:
        return _envelope(
            session=session, config=config, run=None, as_of=None, payload={"positions": []}
        )
    row = (
        session.execute(
            select(portfolio_snapshots)
            .where(
                portfolio_snapshots.c.run_id == run.run_id,
                portfolio_snapshots.c.portfolio_key == STRATEGY_BOOK,
            )
            .order_by(portfolio_snapshots.c.ts.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return _envelope(
            session=session,
            config=config,
            run=run,
            as_of=None,
            quality_flags=["no-snapshot"],
            payload={"positions": [], "cash": None},
        )
    positions = []
    for raw in row.positions or []:
        quantity = Decimal(str(raw.get("quantity", "0")))
        if quantity <= 0:
            continue
        mark = raw.get("mark")
        market_value = None
        if mark is not None:
            market_value = str(round_money(quantity * Decimal(str(mark))))
        positions.append(
            {
                "instrument_id": raw.get("instrument_id"),
                "quantity": str(quantity.normalize()),
                "average_cost": raw.get("average_cost"),
                "mark": mark,
                "mark_as_of": raw.get("mark_as_of"),
                "mark_stale": bool(raw.get("mark_stale", False)),
                "market_value": market_value,
            }
        )
    flags = ["stale-mark"] if any(p["mark_stale"] for p in positions) else []
    missing = ["missing-mark"] if any(p["mark"] is None for p in positions) else []
    return _envelope(
        session=session,
        config=config,
        run=run,
        as_of=row.ts,
        quality_flags=flags + missing,
        payload={
            "positions": positions,
            "cash": _money(row.cash),
            "equity": _money(row.equity),
            "gross_exposure": _money(row.gross_exposure),
            "reconciliation_status": row.reconciliation_status,
        },
    )


def get_instrument_quality(session: Session, run_id: str) -> list[dict[str, Any]]:
    """Per-instrument truth: latest bar, session gap, derived quality flag."""
    out: list[dict[str, Any]] = []
    watermark = _run_watermark(session, run_id)
    for instrument_id in session.execute(
        select(instruments.c.instrument_id)
        .where(instruments.c.run_id == run_id)
        .order_by(instruments.c.instrument_id)
    ).scalars():
        latest = session.execute(
            select(
                market_bars.c.ts,
                market_bars.c.close,
                market_bars.c.quality,
            )
            .where(
                market_bars.c.run_id == run_id,
                market_bars.c.instrument_id == instrument_id,
            )
            .order_by(market_bars.c.ts.desc())
            .limit(1)
        ).first()
        gap_days = _session_gap(session, run_id, instrument_id)
        if latest is None:
            quality = "missing"
        elif (
            watermark is not None
            and (watermark - latest.ts).total_seconds() > 86400 * 2
            or gap_days >= 2
        ):
            quality = "stale"
        else:
            quality = "valid"
        out.append(
            {
                "instrument_id": instrument_id,
                "symbol": instrument_id,
                "latest_bar_at": _iso(latest.ts) if latest else None,
                "latest_close": _money(latest.close) if latest else None,
                "gap_days": gap_days,
                "quality": quality,
            }
        )
    return out


def get_instrument(
    session: Session, config: TradingConfig, run_id: str | None, instrument_id: str
) -> dict[str, Any]:
    run = resolve_run(session, run_id)
    if run is None:
        return _envelope(
            session=session, config=config, run=None, as_of=None, payload={"error": "no-run"}
        )
    row = (
        session.execute(
            select(instruments).where(
                instruments.c.run_id == run.run_id, instruments.c.instrument_id == instrument_id
            )
        )
        .scalars()
        .first()
    )
    if row is None:
        return _envelope(
            session=session,
            config=config,
            run=run,
            quality_flags=["not-found"],
            payload={"error": f"instrument {instrument_id} not in this run"},
        )
    quality = next(
        (
            item
            for item in get_instrument_quality(session, run.run_id)
            if item["instrument_id"] == instrument_id
        ),
        None,
    )
    return _envelope(
        session=session,
        config=config,
        run=run,
        as_of=quality["latest_bar_at"] if quality else None,
        quality_flags=[quality["quality"]] if quality and quality["quality"] != "valid" else [],
        payload={
            "instrument": {
                "instrument_id": row.instrument_id,
                "symbol": row.symbol,
                "asset_class": row.asset_class,
                "price_decimals": row.price_decimals,
                "quantity_precision": row.quantity_precision,
                "is_synthetic": row.is_synthetic,
                "eligible": row.eligible,
                "notes": row.notes,
            },
            "data_status": quality,
        },
    )


def get_prices(
    session: Session, config: TradingConfig, run_id: str | None, instrument_id: str
) -> dict[str, Any]:
    """Bars for one instrument plus time-aligned decision/order/fill markers.

    Ticks the run observed for other instruments but this one did not are
    reported in ``missing_ticks`` and rendered as gaps: never back-filled.
    """
    run = resolve_run(session, run_id)
    if run is None:
        return _envelope(session=session, config=config, run=None, as_of=None, payload={"bars": []})
    bars = [
        {
            "ts": _iso(row.ts),
            "open": _money(row.open),
            "high": _money(row.high),
            "low": _money(row.low),
            "close": _money(row.close),
            "volume": _money(row.volume),
            "quality": row.quality,
        }
        for row in session.execute(
            select(market_bars)
            .where(
                market_bars.c.run_id == run.run_id,
                market_bars.c.instrument_id == instrument_id,
            )
            .order_by(market_bars.c.ts)
        ).scalars()
    ]
    present = {row["ts"] for row in bars if row["ts"] is not None}
    all_ticks = [
        stamp
        for stamp in session.execute(
            select(market_bars.c.ts)
            .where(market_bars.c.run_id == run.run_id)
            .distinct()
            .order_by(market_bars.c.ts)
        ).scalars()
    ]
    missing_ticks = [
        iso
        for iso in (_iso(stamp) for stamp in all_ticks)
        if iso is not None and iso not in present
    ]
    from ..db.schema import activity_events

    marker_rows: list[tuple[str, str, str | None, str | None, str | None]] = []
    for row in session.execute(
        select(
            activity_events.c.ts,
            activity_events.c.event_type,
            activity_events.c.event_id,
            func.jsonb_extract(activity_events.c.correlation, "instrument"),
            activity_events.c.payload,
        ).where(activity_events.c.run_id == run.run_id)
    ):
        if str(row[3]) in (f'"{instrument_id}"', instrument_id):
            marker_rows.append(
                (
                    row[1],
                    "decision" if row[1].startswith("decision") else row[1],
                    _iso(row[0]),
                    row[2],
                    None,
                )
            )
    order_markers = [
        (
            f"order:{row.to_status}",
            "order",
            _iso(row.ts),
            row.order_id,
            None,
        )
        for row in session.execute(
            select(order_events)
            .where(
                order_events.c.run_id == run.run_id,
                broker_orders.c.instrument_id == instrument_id,
            )
            .join(broker_orders, order_events.c.order_id == broker_orders.c.order_id)
            .order_by(order_events.c.ts)
        ).scalars()
    ]
    fill_markers = [
        (
            f"fill:{row.side}",
            "fill",
            _iso(row.ts),
            row.fill_id,
            None,
        )
        for row in session.execute(
            select(fills)
            .where(
                fills.c.run_id == run.run_id,
                fills.c.instrument_id == instrument_id,
            )
            .order_by(fills.c.ts)
        ).scalars()
    ]
    markers = [
        {"kind": kind, "label": label, "ts": ts, "ref_id": ref}
        for label, kind, ts, ref, _ in (marker_rows + order_markers + fill_markers)
        if ts is not None
    ]
    markers.sort(key=lambda item: item["ts"])
    flags: list[str] = []
    if missing_ticks:
        flags.append("missing-data")
    return _envelope(
        session=session,
        config=config,
        run=run,
        as_of=bars[-1]["ts"] if bars else None,
        quality_flags=flags,
        payload={
            "instrument_id": instrument_id,
            "bars": bars,
            "missing_ticks": missing_ticks,
            "markers": markers,
        },
    )


def get_cash_ledger(session: Session, config: TradingConfig, run_id: str | None) -> dict[str, Any]:
    run = resolve_run(session, run_id)
    if run is None:
        return _envelope(
            session=session, config=config, run=None, as_of=None, payload={"events": []}
        )
    rows = session.execute(
        select(ledger_events)
        .where(
            ledger_events.c.run_id == run.run_id,
            ledger_events.c.portfolio_key == STRATEGY_BOOK,
        )
        .order_by(ledger_events.c.ts.desc(), ledger_events.c.event_id.desc())
        .limit(200)
    ).scalars()
    events = [
        {
            "event_id": row.event_id,
            "ts": _iso(row.ts),
            "kind": row.kind,
            "instrument_id": row.instrument_id,
            "quantity": _money(row.quantity),
            "price": _money(row.price),
            "amount": _money(row.amount),
            "fee": _money(row.fee),
            "cash_after": _money(row.cash_after),
            "position_after": _money(row.position_after),
            "ref_type": row.ref_type,
            "ref_id": row.ref_id,
            "note": row.note,
        }
        for row in rows
    ]
    return _envelope(
        session=session,
        config=config,
        run=run,
        as_of=events[0]["ts"] if events else None,
        pagination={"limit": 200},
        payload={"events": events, "note": "most recent 200 ledger events (strategy book)"},
    )


def utcnow() -> datetime:
    return datetime.now(UTC)
