"""Append-only, idempotent money ledger (plan section 16: ledger_events).

Design invariants (build plan section 20):
- Cash and inventory reconcile with fills: every movement is an event row.
- A sell cannot create a short position; cash can never go negative.
- Duplicate fill events do not duplicate cash or inventory: each event has a
  deterministic ``event_key`` with a database unique constraint, and the
  in-memory cache tracks applied keys so replays are no-ops.
- Money is always Decimal, rounded to the canonical 8-decimal precision.

The ledger is one *book* (portfolio_key) of one run. Baselines are separate
books in the same database, never blended.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..contracts.market import QualityFlag
from ..contracts.orders import Fill, OrderSide
from ..contracts.portfolio import PortfolioSnapshot, Position
from ..db.schema import fills, ledger_events, runs
from ..money import round_money


class LedgerInvariantError(RuntimeError):
    """A ledger movement would break a money invariant; the transaction fails."""


@dataclass
class _PositionState:
    quantity: Decimal = Decimal("0")
    average_cost: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")


class Ledger:
    """One book's accounting state with durable, idempotent event application."""

    def __init__(
        self,
        session: Session,
        *,
        run_id: str,
        portfolio_key: str,
        account_alias: str,
        initial_cash: Decimal,
        initial_ts: datetime,
        fencing_token: int = 0,
    ) -> None:
        self._session = session
        self._run_id = run_id
        self._portfolio_key = portfolio_key
        self._account_alias = account_alias
        self._fencing_token = fencing_token
        self._cash: Decimal | None = None
        self._positions: dict[str, _PositionState] = {}
        self._applied: set[str] = set()
        self._pending: list[dict[str, Any]] = []
        self._pending_fills: dict[str, Fill] = {}
        self._dirty = False
        self._failed = False
        self._persisted_keys: set[str] = set()
        self._raw_fills: dict[str, tuple[str, str, Decimal, Decimal, Decimal]] = {}
        self._cash_flows: dict[
            tuple[str, str | None, str | None, datetime, str | None], Decimal
        ] = {}
        self._initial_ts = initial_ts
        if not self._load_from_db():
            self._cash = Decimal("0")
            self._deposit_initial(initial_cash, ts=self._initial_ts)

    # ------------------------------------------------------------ state

    @property
    def cash(self) -> Decimal:
        assert self._cash is not None
        return self._cash

    @property
    def positions(self) -> dict[str, _PositionState]:
        return dict(self._positions)

    def position(self, instrument_id: str) -> _PositionState:
        if instrument_id not in self._positions:
            self._positions[instrument_id] = _PositionState()
        return self._positions[instrument_id]

    def total_realized_pnl(self) -> Decimal:
        return round_money(sum((p.realized_pnl for p in self._positions.values()), Decimal("0")))

    def snapshot(
        self,
        *,
        as_of: datetime,
        marks: dict[str, tuple[Decimal | None, datetime | None, QualityFlag]],
        reconciliation_status: str = "unverified",
    ) -> PortfolioSnapshot:
        if self._failed:
            raise LedgerInvariantError("ledger failed; rollback and reconstruct before reuse")
        positions: list[Position] = []
        gross = Decimal("0")
        for instrument_id, state in sorted(self._positions.items()):
            if state.quantity <= 0:
                continue
            mark = marks.get(instrument_id)
            if mark is None:
                price, mark_as_of, quality = None, None, QualityFlag.MISSING
            else:
                price, mark_as_of, quality = mark
            if price is None:
                raise LedgerInvariantError(
                    "held position mark missing; NAV and new risk unavailable"
                )
            mark_stale = quality is QualityFlag.STALE
            value = state.quantity * (price if price is not None else Decimal("0"))
            if price is not None:
                gross += value
            positions.append(
                Position(
                    instrument_id=instrument_id,
                    quantity=state.quantity,
                    average_cost=state.average_cost,
                    mark=price,
                    mark_as_of=mark_as_of,
                    mark_stale=mark_stale,
                )
            )
        equity = round_money(self.cash + gross)
        return PortfolioSnapshot(
            portfolio_key=self._portfolio_key,
            run_id=self._run_id,
            as_of=as_of,
            cash=round_money(self.cash),
            positions=tuple(positions),
            gross_exposure=round_money(gross),
            equity=equity,
            reconciliation_status=reconciliation_status,
        )

    # ------------------------------------------------------- mutations

    def _deposit_initial(self, initial_cash: Decimal, *, ts: datetime) -> None:
        self.apply_cash_flow(
            round_money(initial_cash),
            kind="initial_deposit",
            ts=ts,
            note="simulated initial capital (clearly labeled; not real money)",
            ref_type="run",
            ref_id=self._run_id,
        )

    def apply_fill(self, fill: Fill, *, at: datetime | None = None) -> bool:
        """Apply one fill exactly once. Returns False (no-op) on duplicate."""
        if self._failed:
            raise LedgerInvariantError("ledger failed; rollback and reconstruct before reuse")
        if fill.run_id != self._run_id or fill.corrected_by is not None:
            raise LedgerInvariantError(
                "fill scope mismatch or unsupported correction requires review"
            )
        fingerprint = (fill.side.value, fill.instrument_id, fill.quantity, fill.price, fill.fee)
        previous = self._raw_fills.get(fill.raw_fill_id)
        if previous is not None:
            if previous != fingerprint:
                raise LedgerInvariantError("conflicting duplicate fill requires correction review")
            return False
        key = self._event_key("fill", fill.raw_fill_id, fill.fill_id)
        if key in self._applied:
            return False
        if not self._db_key_absent(key):
            return False
        quantity = round_money(fill.quantity)
        price = round_money(fill.price)
        fee = round_money(fill.fee)
        if quantity <= 0 or price <= 0 or fee < 0:
            raise LedgerInvariantError(
                f"fill {fill.fill_id}: nonpositive quantity or negative price"
            )
        before_cash = self.cash
        state = self.position(fill.instrument_id)
        if fill.side is OrderSide.BUY:
            cost = round_money(quantity * price) + fee
            if cost > before_cash:
                raise LedgerInvariantError(
                    f"fill {fill.fill_id}: cost {cost} exceeds available cash {before_cash}; "
                    "a buy must never spend cash that is not reserved and present"
                )
            self._cash = before_cash - cost
            new_qty = state.quantity + quantity
            if new_qty > 0:
                state.average_cost = round_money(
                    (state.quantity * state.average_cost + quantity * price + fee) / new_qty
                )
            state.quantity = new_qty
        else:
            if quantity > state.quantity:
                raise LedgerInvariantError(
                    f"fill {fill.fill_id}: sells {quantity} but holds {state.quantity}; "
                    "a sell cannot create a short position"
                )
            proceeds = round_money(quantity * price) - fee
            if before_cash + proceeds < 0:
                raise LedgerInvariantError("sell fees would drive cash negative")
            self._cash = before_cash + proceeds
            state.realized_pnl = round_money(
                state.realized_pnl + proceeds - quantity * state.average_cost
            )
            state.quantity = state.quantity - quantity
            if state.quantity == 0:
                state.average_cost = Decimal("0")
        if self._cash < 0:
            raise LedgerInvariantError(f"fill {fill.fill_id} drives cash negative: {self._cash}")
        self._applied.add(key)
        self._raw_fills[fill.raw_fill_id] = fingerprint
        self._pending.append(
            self._row(
                event_id=key,
                event_key=key,
                ts=at or fill.ts,
                kind="fill",
                instrument_id=fill.instrument_id,
                quantity=quantity,
                price=price,
                amount=None,
                fee=fee,
                ref_type="fill",
                ref_id=fill.fill_id,
                note=fill.source,
            )
        )
        self._pending[-1]["cash_after"] = self.cash
        self._pending[-1]["position_after"] = state.quantity
        self._pending_fills[fill.fill_id] = fill
        self._dirty = True
        return True

    def apply_cash_flow(
        self,
        amount: Decimal,
        *,
        kind: str,
        ts: datetime,
        note: str = "",
        ref_type: str | None = None,
        ref_id: str | None = None,
        instrument_id: str | None = None,
    ) -> bool:
        """Apply a cash movement (accrual, deposit, fee) exactly once."""
        if self._failed:
            raise LedgerInvariantError("ledger failed; rollback and reconstruct before reuse")
        identity = (kind, ref_type, ref_id, ts, instrument_id)
        if identity in self._cash_flows:
            if self._cash_flows[identity] != round_money(amount):
                raise LedgerInvariantError(
                    "conflicting cash-flow reference requires correction review"
                )
            return False
        ref = f"{ref_type or kind}:{ref_id or kind}:{ts.isoformat()}"
        key = self._event_key(kind, ref)
        if key in self._applied or not self._db_key_absent(key):
            return False
        before = self.cash
        proposed = round_money(before + amount)
        if not proposed.is_finite() or proposed < 0:
            raise LedgerInvariantError("cash flow would make cash negative or nonfinite")
        self._cash = proposed
        self._cash_flows[identity] = round_money(amount)
        self._applied.add(key)
        self._pending.append(
            self._row(
                event_id=key,
                event_key=key,
                ts=ts,
                kind=kind,
                instrument_id=instrument_id,
                quantity=None,
                price=None,
                amount=round_money(amount),
                fee=None,
                ref_type=ref_type,
                ref_id=ref_id,
                note=note,
            )
        )
        self._pending[-1]["cash_after"] = self.cash
        self._dirty = True
        return True

    # ------------------------------------------------------- persistence

    def flush(self) -> int:
        """Persist pending events (call inside the caller's transaction)."""
        if not self._pending:
            return 0
        if self._failed:
            raise LedgerInvariantError("ledger failed; rollback and reconstruct before reuse")
        inserted = 0
        try:
            if (
                self._session.execute(
                    select(runs.c.fencing_token)
                    .where(runs.c.run_id == self._run_id)
                    .with_for_update()
                ).scalar_one_or_none()
                != self._fencing_token
            ):
                raise LedgerInvariantError("ledger run missing or executor fencing token changed")
            current: set[str] = set(
                self._session.execute(
                    select(ledger_events.c.event_key).where(
                        ledger_events.c.run_id == self._run_id,
                        ledger_events.c.portfolio_key == self._portfolio_key,
                    )
                ).scalars()
            )
            if current != self._persisted_keys:
                raise LedgerInvariantError("concurrent ledger update; rollback and reconstruct")
            for fill in self._pending_fills.values():
                prior = self._session.execute(
                    select(fills).where(
                        fills.c.run_id == self._run_id,
                        fills.c.raw_fill_id == fill.raw_fill_id,
                    )
                ).first()
                values = {
                    "portfolio_key": self._portfolio_key,
                    "fill_id": fill.fill_id,
                    "run_id": fill.run_id,
                    "order_id": fill.order_id,
                    "instrument_id": fill.instrument_id,
                    "side": fill.side.value,
                    "ts": fill.ts,
                    "quantity": fill.quantity,
                    "price": fill.price,
                    "fee": fill.fee,
                    "raw_fill_id": fill.raw_fill_id,
                    "source": fill.source,
                    "corrected_by": fill.corrected_by,
                }
                if prior is None:
                    self._session.execute(fills.insert().values(**values))
                elif any(
                    getattr(prior, field) != values[field]
                    for field in (
                        "fill_id",
                        "order_id",
                        "instrument_id",
                        "side",
                        "quantity",
                        "price",
                        "fee",
                    )
                ):
                    raise LedgerInvariantError(
                        "persisted fill evidence conflicts with ledger input"
                    )
            unsequenced = self._session.execute(
                select(func.count())
                .select_from(ledger_events)
                .where(
                    ledger_events.c.run_id == self._run_id,
                    ledger_events.c.portfolio_key == self._portfolio_key,
                    ledger_events.c.application_seq.is_(None),
                )
            ).scalar_one()
            if unsequenced:
                raise LedgerInvariantError("legacy ledger ordering requires reviewed migration")
            sequence = (
                self._session.execute(
                    select(func.max(ledger_events.c.application_seq)).where(
                        ledger_events.c.run_id == self._run_id,
                        ledger_events.c.portfolio_key == self._portfolio_key,
                    )
                ).scalar_one()
                or 0
            )
            for row in self._pending:
                sequence += 1
                row["application_seq"] = sequence
                self._session.execute(ledger_events.insert().values(**row))
                self._persisted_keys.add(row["event_key"])
                inserted += 1
        except Exception:
            self._failed = True
            raise
        self._pending = []
        self._pending_fills = {}
        self._dirty = False
        return inserted

    def _load_from_db(self) -> bool:
        """Rebuild the cache from persisted events (restart safety)."""
        rows = list(
            self._session.execute(
                select(ledger_events)
                .where(
                    ledger_events.c.run_id == self._run_id,
                    ledger_events.c.portfolio_key == self._portfolio_key,
                )
                .order_by(
                    ledger_events.c.application_seq, ledger_events.c.ts, ledger_events.c.event_id
                )
            ).all()
        )
        if not rows:
            return False
        if any(row.application_seq is None for row in rows) and len(
            {row.ts for row in rows}
        ) != len(rows):
            raise LedgerInvariantError(
                "ambiguous equal-timestamp history requires reviewed durable ordering"
            )
        if any(row.application_seq is None for row in rows):
            rows.sort(key=lambda row: (row.ts, row.event_id))
        cash = Decimal("0")
        for row in rows:
            cash = row.cash_after if row.cash_after is not None else cash
            self._applied.add(row.event_key)
            self._persisted_keys.add(row.event_key)
            if row.kind != "fill":
                identity = (row.kind, row.ref_type, row.ref_id, row.ts, row.instrument_id)
                if identity in self._cash_flows:
                    raise LedgerInvariantError(
                        "duplicate legacy cash-flow evidence requires review"
                    )
                self._cash_flows[identity] = row.amount or Decimal(0)
            if row.kind == "fill" and row.ref_id is not None:
                record = self._session.execute(
                    select(fills).where(
                        fills.c.run_id == self._run_id,
                        fills.c.fill_id == row.ref_id,
                    )
                ).first()
                if record is None:
                    raise LedgerInvariantError("fill evidence missing during replay")
                self._raw_fills[record.raw_fill_id] = (
                    record.side,
                    record.instrument_id,
                    record.quantity,
                    record.price,
                    record.fee,
                )
                self._apply_fill_row(row)
        self._cash = cash
        return True

    def _apply_fill_row(self, row: Any) -> None:
        """Re-derive position state from a persisted fill row (avg cost, realized)."""
        quantity = row.quantity or Decimal("0")
        price = row.price or Decimal("0")
        fee = row.fee or Decimal("0")
        state = self.position(row.instrument_id)
        # Side is encoded in the quantity sign convention of the row: a buy
        # increases position, a sell decreases it.
        side = self._fill_side(row)
        if side == "buy":
            new_qty = state.quantity + quantity
            if new_qty > 0:
                state.average_cost = round_money(
                    (state.quantity * state.average_cost + quantity * price + fee) / new_qty
                )
            state.quantity = new_qty
        else:
            state.realized_pnl = round_money(
                state.realized_pnl + (quantity * price - fee) - quantity * state.average_cost
            )
            state.quantity = state.quantity - quantity
            if state.quantity == 0:
                state.average_cost = Decimal("0")

    def _fill_side(self, row: Any) -> str:
        # The ledger row stores the signed position delta implicitly; the
        # canonical source of truth for side is the fills table.
        from ..db.schema import fills

        record = self._session.execute(
            select(fills.c.side).where(
                fills.c.fill_id == row.ref_id, fills.c.run_id == self._run_id
            )
        ).first()
        if record is None or record[0] not in {"buy", "sell"}:
            raise LedgerInvariantError(
                "persisted fill side is unavailable; refusing guessed replay"
            )
        return str(record[0])

    def _row(self, **values: Any) -> dict[str, Any]:
        base = {
            "run_id": self._run_id,
            "portfolio_key": self._portfolio_key,
            "fencing_token": self._fencing_token,
        }
        base.update(values)
        return base

    def _db_key_absent(self, key: str) -> bool:
        existing = self._session.execute(
            select(ledger_events.c.event_id).where(
                ledger_events.c.event_key == key,
                ledger_events.c.run_id == self._run_id,
                ledger_events.c.portfolio_key == self._portfolio_key,
            )
        ).first()
        return existing is None

    def _event_key(self, kind: str, *parts: str) -> str:
        # References repeat across simulation runs. Preserve old keys on disk;
        # logical-reference replay above also deduplicates pre-v2 histories.
        return hashlib.sha256(
            "|".join((self._run_id, self._account_alias, self._portfolio_key, kind, *parts)).encode(
                "utf-8"
            )
        ).hexdigest()

    # ------------------------------------------------- reservation view

    def available_cash_excluding_reservations(
        self, session: Session, *, run_id: str, portfolio_key: str
    ) -> Decimal:
        from ..db.schema import reservations

        reserved = session.execute(
            select(reservations.c.amount).where(
                reservations.c.run_id == run_id,
                reservations.c.kind == "cash",
                reservations.c.status == "active",
            )
        ).all()
        reserved_total = sum((row[0] for row in reserved), Decimal("0"))
        return round_money(self.cash - reserved_total)
