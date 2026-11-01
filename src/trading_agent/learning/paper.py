"""Paper-trading lifecycle and synthetic paper fills for challengers (plan M4).

A challenger earns ``promote`` only after paper-trading.  The state machine
is deterministic and fail-closed, and every transition is recorded with an
auditable reason.  Paper fills are computed against the same ``CloseSeries``
the evaluation uses, so the paper book, the backtest, and the replay all
read one price source.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any, Iterable, Mapping

from ..backtest.engine import CloseSeries
from .challenger import Challenger, ChallengerError


class PaperStatus(str, Enum):
    PAPER = "paper"
    PROMOTED = "promoted"
    RETIRED = "retired"
    FAILED = "failed"


class PaperError(ValueError):
    """Raised on illegal lifecycle transitions or malformed fills."""


def paper_digest(parts: Iterable[Any]) -> str:
    return hashlib.sha256(
        json.dumps(list(parts), sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class PaperTrade:
    trade_id: str
    entry_session: date
    entry_price: Decimal
    exit_session: date
    exit_price: Decimal
    direction: int
    units: Decimal
    realized_return_bps: Decimal

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "entry_session": self.entry_session.isoformat(),
            "entry_price": str(self.entry_price),
            "exit_session": self.exit_session.isoformat(),
            "exit_price": str(self.exit_price),
            "direction": self.direction,
            "units": str(self.units),
            "realized_return_bps": str(self.realized_return_bps),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> PaperTrade:
        return cls(
            trade_id=str(raw["trade_id"]),
            entry_session=date.fromisoformat(str(raw["entry_session"])),
            entry_price=Decimal(str(raw["entry_price"])),
            exit_session=date.fromisoformat(str(raw["exit_session"])),
            exit_price=Decimal(str(raw["exit_price"])),
            direction=int(raw["direction"]),
            units=Decimal(str(raw["units"])),
            realized_return_bps=Decimal(str(raw["realized_return_bps"])),
        )


@dataclass(frozen=True)
class PaperLifecycle:
    paper_id: str
    challenger_id: str
    status: PaperStatus
    opened_at: date
    minimum_trades: int
    rule_digest: str
    target_weight: Decimal
    trades: tuple[PaperTrade, ...] = ()
    realized_total_bps: Decimal = Decimal("0")
    max_drawdown_bps: Decimal = Decimal("0")
    last_update: date | None = None
    history: tuple[dict[str, str], ...] = ()
    digest: str = ""

    def open(self, *, at: date, note: str) -> PaperLifecycle:
        return replace(
            self,
            opened_at=at,
            status=PaperStatus.PAPER,
            history=self.history + ({"at": at.isoformat(), "status": "paper", "note": note},),
            last_update=at,
        )

    def record(self, trade: PaperTrade) -> PaperLifecycle:
        if self.status is not PaperStatus.PAPER:
            raise PaperError(
                f"paper book {self.paper_id} is {self.status.value}; no more fills"
            )
        trades = self.trades + (trade,)
        realized = self.realized_total_bps + trade.realized_return_bps
        drawdown = max(self.max_drawdown_bps, -trade.realized_return_bps)
        return replace(
            self,
            trades=trades,
            realized_total_bps=realized,
            max_drawdown_bps=drawdown,
            last_update=trade.exit_session,
        )

    def promote(self, *, at: date, reason: str) -> PaperLifecycle:
        if self.status is not PaperStatus.PAPER:
            raise PaperError(f"cannot promote a {self.status.value} paper book")
        if len(self.trades) < self.minimum_trades:
            raise PaperError(
                f"paper book needs {self.minimum_trades} trades; has {len(self.trades)}"
            )
        return replace(
            self,
            status=PaperStatus.PROMOTED,
            last_update=at,
            history=self.history
            + ({"at": at.isoformat(), "status": "promoted", "note": reason},),
            digest=paper_digest(
                (self.paper_id, self.challenger_id, "promoted", at.isoformat(), reason, self.rule_digest)
            ),
        )

    def retire(self, *, at: date, reason: str) -> PaperLifecycle:
        if self.status is PaperStatus.RETIRED:
            raise PaperError(f"paper book {self.paper_id} is already retired")
        return replace(
            self,
            status=PaperStatus.RETIRED,
            last_update=at,
            history=self.history + ({"at": at.isoformat(), "status": "retired", "note": reason},),
            digest=paper_digest(
                (self.paper_id, self.challenger_id, "retired", at.isoformat(), reason, self.rule_digest)
            ),
        )


def simulate_paper(
    challenger: Challenger,
    closes: CloseSeries,
    *,
    paper_id: str,
    opened_at: date,
    minimum_trades: int,
    initial_units: Decimal,
    fee_bps: Decimal = Decimal("5"),
) -> PaperLifecycle:
    """Run the challenger rule over a CloseSeries, emitting paper trades.

    One round trip per regime: hold ``initial_units`` long while the trend
    score is above the entry threshold, exit (paying the fee) when it
    crosses below the exit threshold.
    """
    if minimum_trades < 1:
        raise PaperError("minimum_trades must be >= 1")
    if initial_units <= 0:
        raise PaperError("initial_units must be positive")
    if challenger.rule.target_weight <= 0 or challenger.rule.target_weight > 1:
        raise ChallengerError(f"invalid target_weight {challenger.rule.target_weight}")

    lifecycle = PaperLifecycle(
        paper_id=paper_id,
        challenger_id=challenger.challenger_id,
        status=PaperStatus.PAPER,
        opened_at=opened_at,
        minimum_trades=minimum_trades,
        rule_digest=challenger.rule_digest,
        target_weight=challenger.rule.target_weight,
    )
    rule = challenger.rule
    dates = closes.dates()
    in_position = False
    entry_session: date | None = None
    entry_price: Decimal | None = None
    trade_index = 0
    for position, session in enumerate(dates):
        if position < rule.lookback:
            continue
        window = closes.up_to(session, rule.lookback + 1)
        base = window[0][1]
        current = window[-1][1]
        if base <= 0 or current <= 0:
            in_position = False
            entry_session = None
            continue
        score = (current - base) / base
        should_hold = score >= (rule.exit_momentum if in_position else rule.entry_momentum)
        if in_position and not should_hold:
            units = initial_units * rule.target_weight
            cost_basis = units * entry_price * (Decimal("1") + fee_bps / Decimal("10000"))
            proceeds = units * current
            fee = proceeds * fee_bps / Decimal("10000")
            realized = (
                (proceeds - fee - cost_basis) / cost_basis * Decimal("10000")
                if cost_basis > 0
                else Decimal("0")
            )
            trade_index += 1
            lifecycle = lifecycle.record(
                PaperTrade(
                    trade_id=f"{paper_id}-{trade_index:04d}",
                    entry_session=entry_session,
                    entry_price=entry_price,
                    exit_session=session,
                    exit_price=current,
                    direction=1,
                    units=units,
                    realized_return_bps=realized,
                )
            )
            in_position = False
            entry_session = None
            entry_price = None
        elif not in_position and score >= rule.entry_momentum:
            in_position = True
            entry_session = session
            entry_price = current
    if in_position and entry_session is not None and entry_price is not None:
        trade_index += 1
        current = closes.value_on(session)
        units = initial_units * rule.target_weight
        cost_basis = units * entry_price * (Decimal("1") + fee_bps / Decimal("10000"))
        proceeds = units * current
        fee = proceeds * fee_bps / Decimal("10000")
        realized = (
            (proceeds - fee - cost_basis) / cost_basis * Decimal("10000")
            if cost_basis > 0
            else Decimal("0")
        )
        lifecycle = lifecycle.record(
            PaperTrade(
                trade_id=f"{paper_id}-{trade_index:04d}",
                entry_session=entry_session,
                entry_price=entry_price,
                exit_session=session,
                exit_price=current,
                direction=1,
                units=units,
                realized_return_bps=realized,
            )
        )
    return lifecycle
