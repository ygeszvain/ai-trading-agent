"""Run report: text/JSON summaries built purely from persisted state.

The report never trusts in-memory process state: every number is re-queried
from the run's database rows (decisions, risk evaluations, orders, fills,
ledger events, snapshots, reconciliation). Money renders as exact decimal
strings and the run is unmistakably labeled SIMULATION.

Realized P&L is re-derived read-only from ledger ``fill`` events using the
identical average-cost math and rounding as the ledger (plan section 20:
reconciliation must be reproducible from persisted events).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config.models import TradingConfig
from ..db.schema import (
    broker_orders,
    decisions,
    fills,
    ledger_events,
    market_bars,
    order_events,
    portfolio_snapshots,
    reconciliation_runs,
    risk_evaluations,
    runs,
)
from ..money import round_money
from .pipeline import CASH_BOOK, PASSIVE_BOOK, STRATEGY_BOOK

SIMULATION_LABEL = "SIMULATION"
_ONE_SESSION_SECONDS = 86400 * 2


class RunNotFoundError(LookupError):
    """The requested run id does not exist in the database."""


@dataclass(frozen=True)
class ReportData:
    """One run's persisted summary, ready for text or JSON rendering."""

    run_id: str
    status: str
    account_alias: str
    mode: str
    data_source: str
    data_snapshot_id: str
    strategy_version: str
    risk_policy_version: str
    initial_cash: Decimal
    sessions: int
    decisions: int
    holds: int
    entries: int
    exits: int
    risk_pass: int
    risk_reduce: int
    risk_reject: int
    orders: int
    filled_orders: int
    partially_filled_orders: int
    cancelled_orders: int
    expired_orders: int
    rejected_orders: int
    unknown_resolved: int
    fills: int
    total_fees: Decimal
    equity: dict[str, Decimal]
    realized_pnl: dict[str, Decimal]
    open_positions: dict[str, Decimal]
    final_marks: dict[str, dict[str, str | None]]
    data_gaps: dict[str, int]
    last_reconciliation: str
    reconciliation_sessions: int
    first_bar_at: datetime | None
    last_bar_at: datetime | None
    authority: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": SIMULATION_LABEL,
            "run_id": self.run_id,
            "status": self.status,
            "scope": {
                "account_alias": self.account_alias,
                "mode": self.mode.upper(),
                "run_id": self.run_id,
                "strategy_version": self.strategy_version,
                "risk_policy_version": self.risk_policy_version,
                "data_source": self.data_source,
                "data_snapshot_id": self.data_snapshot_id,
            },
            "initial_cash": str(self.initial_cash),
            "sessions": self.sessions,
            "decisions": {
                "total": self.decisions,
                "hold": self.holds,
                "enter": self.entries,
                "exit": self.exits,
            },
            "risk": {
                "pass": self.risk_pass,
                "reduce": self.risk_reduce,
                "reject": self.risk_reject,
            },
            "orders": {
                "total": self.orders,
                "filled": self.filled_orders,
                "partially_filled": self.partially_filled_orders,
                "cancelled": self.cancelled_orders,
                "expired": self.expired_orders,
                "rejected": self.rejected_orders,
                "unknown_resolved": self.unknown_resolved,
            },
            "fills": self.fills,
            "total_fees": str(self.total_fees),
            "final_equity": {key: str(value) for key, value in self.equity.items()},
            "realized_pnl": {key: str(value) for key, value in self.realized_pnl.items()},
            "open_positions": {key: str(value) for key, value in self.open_positions.items()},
            "final_marks": self.final_marks,
            "data_gaps_sessions": self.data_gaps,
            "reconciliation": {
                "last_status": self.last_reconciliation,
                "sessions": self.reconciliation_sessions,
            },
            "first_bar_at": self.first_bar_at.isoformat() if self.first_bar_at else None,
            "last_bar_at": self.last_bar_at.isoformat() if self.last_bar_at else None,
            "financial_authority": self.authority,
        }


def _count(session: Session, table: Any, run_id: str, *where: Any) -> int:
    query = select(func.count()).select_from(table).where(table.c.run_id == run_id, *where)
    return int(session.execute(query).scalar_one())


def _book_last_snapshot(session: Session, run_id: str, book: str) -> dict[str, Any] | None:
    row = (
        session.execute(
            select(
                portfolio_snapshots.c.equity,
                portfolio_snapshots.c.cash,
                portfolio_snapshots.c.positions,
                portfolio_snapshots.c.ts,
            )
            .where(
                portfolio_snapshots.c.run_id == run_id,
                portfolio_snapshots.c.portfolio_key == book,
            )
            .order_by(portfolio_snapshots.c.ts.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    positions = json.loads(row.positions) if isinstance(row.positions, str) else row.positions
    return {"equity": row.equity, "cash": row.cash, "positions": positions, "ts": row.ts}


def _session_gap(session: Session, run_id: str, instrument_id: str) -> int:
    """Largest gap, in calendar days, between consecutive observed bar days."""
    stamps: list[datetime | None] = list(
        session.execute(
            select(func.date_trunc("day", market_bars.c.exchange_time)).where(
                market_bars.c.run_id == run_id,
                market_bars.c.instrument_id == instrument_id,
                market_bars.c.exchange_time.is_not(None),
            )
        ).scalars()
    )
    days = sorted({stamp for stamp in stamps if stamp is not None})
    if len(days) < 2:
        return 0
    return int(max((b - a).days for a, b in zip(days, days[1:], strict=False)))


def _final_marks(session: Session, run_id: str) -> dict[str, dict[str, str | None]]:
    """Latest persisted bar per instrument; staleness judged at the run end."""
    rows: list[Any] = list(
        session.execute(
            select(market_bars.c.instrument_id, market_bars.c.ts, market_bars.c.close)
            .where(market_bars.c.run_id == run_id)
            .distinct(market_bars.c.instrument_id)
            .order_by(market_bars.c.instrument_id, market_bars.c.ts.desc())
        ).all()
    )
    watermark: datetime | None = session.execute(
        select(func.max(market_bars.c.ts)).where(market_bars.c.run_id == run_id)
    ).scalar_one()
    marks: dict[str, dict[str, str | None]] = {}
    for instrument_id, latest_ts, close in rows:
        age = watermark - latest_ts if watermark is not None and latest_ts is not None else None
        stale = age is not None and age.total_seconds() > _ONE_SESSION_SECONDS
        marks[instrument_id] = {
            "price": str(close),
            "as_of": latest_ts.isoformat() if latest_ts is not None else None,
            "quality": "stale" if stale else "valid" if latest_ts is not None else "missing",
        }
    return marks


def _rederive_realized_pnl(session: Session, run_id: str, portfolio_key: str) -> dict[str, Decimal]:
    """Replay the book's persisted fill events (average cost, ledger rounding)."""
    events = (
        session.execute(
            select(ledger_events)
            .where(
                ledger_events.c.run_id == run_id,
                ledger_events.c.portfolio_key == portfolio_key,
                ledger_events.c.kind == "fill",
            )
            .order_by(ledger_events.c.application_seq, ledger_events.c.ts, ledger_events.c.event_id)
        )
    ).all()
    sides: dict[str, str] = dict(
        session.execute(select(fills.c.fill_id, fills.c.side).where(fills.c.run_id == run_id)).all()
    )
    quantity: dict[str, Decimal] = {}
    average_cost: dict[str, Decimal] = {}
    realized: dict[str, Decimal] = {}
    for event in events:
        if event.instrument_id is None or event.quantity is None or event.price is None:
            continue
        side = sides.get(event.ref_id or "", "")
        qty = round_money(event.quantity)
        price = round_money(event.price)
        fee = round_money(event.fee) if event.fee is not None else Decimal("0")
        held = quantity.get(event.instrument_id, Decimal("0"))
        if side == "buy":
            new_qty = held + qty
            if new_qty > 0:
                average_cost[event.instrument_id] = round_money(
                    (held * average_cost.get(event.instrument_id, Decimal("0")) + qty * price + fee)
                    / new_qty
                )
            quantity[event.instrument_id] = new_qty
        elif side == "sell" and qty <= held:
            proceeds = round_money(qty * price) - fee
            realized[event.instrument_id] = round_money(
                realized.get(event.instrument_id, Decimal("0"))
                + proceeds
                - qty * average_cost.get(event.instrument_id, Decimal("0"))
            )
            quantity[event.instrument_id] = held - qty
    return {key: value for key, value in realized.items() if value != 0}


def build_report(session: Session, config: TradingConfig, run_id: str) -> ReportData:
    """Build the report for one run entirely from its persisted rows."""
    run = session.execute(select(runs).where(runs.c.run_id == run_id)).first()
    if run is None:
        raise RunNotFoundError(f"run {run_id!r} not found")

    books = (STRATEGY_BOOK, CASH_BOOK, PASSIVE_BOOK)
    equity: dict[str, Decimal] = {}
    open_positions: dict[str, Decimal] = {}
    for book in books:
        snapshot = _book_last_snapshot(session, run_id, book)
        if snapshot is None:
            continue
        equity[book] = round_money(snapshot["equity"])
        if book == STRATEGY_BOOK:
            for position in snapshot["positions"] or []:
                qty = Decimal(str(position.get("quantity", "0")))
                if qty > 0:
                    open_positions[position["instrument_id"]] = qty

    gaps = {
        instrument_id: _session_gap(session, run_id, instrument_id)
        for instrument_id in config.paper.synthetic_fixture_universe
    }
    recon = session.execute(
        select(reconciliation_runs.c.status, func.count())
        .where(reconciliation_runs.c.run_id == run_id)
        .group_by(reconciliation_runs.c.status)
    ).all()
    last_status_row = session.execute(
        select(reconciliation_runs.c.status)
        .where(reconciliation_runs.c.run_id == run_id)
        .order_by(reconciliation_runs.c.completed_at.desc())
        .limit(1)
    ).first()
    bar_range = session.execute(
        select(func.min(market_bars.c.ts), func.max(market_bars.c.ts)).where(
            market_bars.c.run_id == run_id
        )
    ).first()
    fees: Decimal | None = session.execute(
        select(func.sum(fills.c.fee)).where(
            fills.c.run_id == run_id, fills.c.portfolio_key == STRATEGY_BOOK
        )
    ).scalar_one()

    return ReportData(
        run_id=run.run_id,
        status=run.status,
        account_alias=run.account_alias,
        mode=run.mode,
        data_source=run.data_source,
        data_snapshot_id=run.data_snapshot_id,
        strategy_version=run.strategy_version,
        risk_policy_version=run.risk_policy_version,
        initial_cash=round_money(run.initial_cash),
        sessions=_count(session, portfolio_snapshots, run_id),
        decisions=_count(session, decisions, run_id),
        holds=_count(session, decisions, run_id, decisions.c.action == "HOLD"),
        entries=_count(session, decisions, run_id, decisions.c.action == "ENTER"),
        exits=_count(session, decisions, run_id, decisions.c.action == "EXIT"),
        risk_pass=_count(session, risk_evaluations, run_id, risk_evaluations.c.outcome == "pass"),
        risk_reduce=_count(
            session, risk_evaluations, run_id, risk_evaluations.c.outcome == "reduce"
        ),
        risk_reject=_count(
            session, risk_evaluations, run_id, risk_evaluations.c.outcome == "reject"
        ),
        orders=_count(session, broker_orders, run_id),
        filled_orders=_count(session, broker_orders, run_id, broker_orders.c.status == "filled"),
        partially_filled_orders=_count(
            session, order_events, run_id, order_events.c.to_status == "partially_filled"
        ),
        cancelled_orders=_count(
            session, broker_orders, run_id, broker_orders.c.status == "cancelled"
        ),
        expired_orders=_count(session, broker_orders, run_id, broker_orders.c.status == "expired"),
        rejected_orders=_count(
            session, broker_orders, run_id, broker_orders.c.status == "rejected"
        ),
        unknown_resolved=_count(
            session,
            order_events,
            run_id,
            order_events.c.to_status == "acknowledged",
            order_events.c.reason.like("reconciliation%"),
        ),
        fills=_count(session, fills, run_id, fills.c.portfolio_key == STRATEGY_BOOK),
        total_fees=round_money(fees or Decimal("0")),
        equity=equity,
        realized_pnl=_rederive_realized_pnl(session, run_id, STRATEGY_BOOK),
        open_positions=open_positions,
        final_marks=_final_marks(session, run_id),
        data_gaps={key: value for key, value in gaps.items() if value > 0},
        last_reconciliation=last_status_row[0] if last_status_row is not None else "unverified",
        reconciliation_sessions=sum(int(str(count)) for _, count in recon),
        first_bar_at=bar_range[0] if bar_range else None,
        last_bar_at=bar_range[1] if bar_range else None,
        authority=config.authority(),
    )


def render_text(report: ReportData) -> str:
    """Human-readable report with an unmistakable SIMULATION header."""
    bar = "=" * 72
    lines = [
        bar,
        "  SIMULATED TRADING RUN - SYNTHETIC DATA - NOT INVESTMENT EVIDENCE",
        "  SIMULATION: no real orders, no real money, no broker connection",
        bar,
        f"run id           {report.run_id}",
        f"status           {report.status}",
        (
            f"scope            {report.account_alias} / {report.mode.upper()}"
            f" / {report.strategy_version}"
        ),
        f"data             {report.data_source} snapshot {report.data_snapshot_id}",
        f"period           {report.first_bar_at} .. {report.last_bar_at} "
        f"({report.sessions} sessions) final equity (SIMULATED USD):",
    ]
    for book, value in report.equity.items():
        lines.append(f"  {book:<18} {value:>16}")
    lines.append("")
    lines.append(f"initial cash       {report.initial_cash}")
    lines.append(
        f"decisions          {report.decisions} total "
        f"({report.holds} HOLD / {report.entries} ENTER / {report.exits} EXIT)"
    )
    lines.append(
        f"risk               {report.risk_pass} pass / {report.risk_reduce} reduce / "
        f"{report.risk_reject} reject"
    )
    lines.append(
        f"orders             {report.orders} total ({report.filled_orders} filled, "
        f"{report.partially_filled_orders} partially filled, {report.cancelled_orders} "
        f"cancelled, {report.expired_orders} expired, {report.rejected_orders} rejected, "
        f"{report.unknown_resolved} unknown-resolved)"
    )
    lines.append(f"fills              {report.fills} (total simulated fees {report.total_fees})")
    realized = ", ".join(f"{key} {value}" for key, value in sorted(report.realized_pnl.items()))
    lines.append(f"realized P&L       {realized or 'none'}")
    positions = ", ".join(f"{key} {value}" for key, value in sorted(report.open_positions.items()))
    lines.append(f"open positions     {positions or 'none'}")
    lines.append(
        f"reconciliation     {report.last_reconciliation} "
        f"({report.reconciliation_sessions} session-end runs)"
    )
    if report.data_gaps:
        gaps = ", ".join(f"{key} {value} day(s)" for key, value in sorted(report.data_gaps.items()))
        lines.append(f"data gaps          {gaps} (rendered stale/missing, never fabricated)")
    else:
        lines.append("data gaps          none")
    lines += ["", f"financial authority  {report.authority}", bar]
    return "\n".join(lines)


def render_json(report: ReportData) -> str:
    return json.dumps(report.to_dict(), indent=2, sort_keys=True)
