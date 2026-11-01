"""Legacy daily-close labels with an explicit session calendar.

Use records.py for timestamped evidence, reconciliation and correction snapshots.
An as_of date here means the caller has verified that session is completed.
Missing session prices never shift a horizon or substitute an earlier reference.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from types import MappingProxyType
from typing import Any

from ..backtest.engine import CloseSeries
from ..exceptions import TradingAgentError

_RETURN_EXPONENT = Decimal("1e-8")

#: Standard label horizons in completed sessions (owner: research protocol
#: evaluation window, plus the full 21-session window for memory).
DEFAULT_HORIZONS: tuple[int, ...] = (1, 3, 5, 10, 21)

#: Actions that exist in the owner's decision contract.
KNOWN_ACTIONS: frozenset[str] = frozenset({"enter", "exit", "rebalance", "cancel", "hold"})


class LearningError(TradingAgentError):
    """Invalid learning input (label, dataset, challenger, promotion, memory)."""


def round8(value: Decimal) -> Decimal:
    """Owner precision convention: 8 decimal places, half-even."""
    return value.quantize(_RETURN_EXPONENT, rounding=ROUND_HALF_EVEN)


def _digest(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@dataclass(frozen=True)
class DecisionRecord:
    """One decision as recorded by the engine ledger, normalized for learning.

    Mirrors the owner's ``decisions`` table. ``decision_session`` is the
    exchange-calendar session in which the decision was made (its 16:00
    close is both the decision instant and the execution price).
    """

    decision_id: str
    run_id: str
    account_alias: str
    mode: str
    instrument_id: str
    decision_session: date
    action: str
    target_weight: Decimal
    strategy_version: str
    model_version: str | None
    data_snapshot_id: str
    risk_policy_version: str
    rationale: str = ""
    invalidation: tuple[str, ...] = ()
    source: str = "ledger"  # ledger | backtest | export

    def __post_init__(self) -> None:
        if self.action not in KNOWN_ACTIONS:
            raise LearningError(
                f"decision {self.decision_id}: unknown action {self.action!r}; "
                f"known actions: {sorted(KNOWN_ACTIONS)}"
            )
        if not self.instrument_id:
            raise LearningError(f"decision {self.decision_id}: instrument_id is required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "run_id": self.run_id,
            "account_alias": self.account_alias,
            "mode": self.mode,
            "instrument_id": self.instrument_id,
            "decision_session": self.decision_session.isoformat(),
            "action": self.action,
            "target_weight": str(self.target_weight),
            "strategy_version": self.strategy_version,
            "model_version": self.model_version,
            "data_snapshot_id": self.data_snapshot_id,
            "risk_policy_version": self.risk_policy_version,
            "rationale": self.rationale,
            "invalidation": list(self.invalidation),
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> DecisionRecord:
        return cls(
            decision_id=str(raw["decision_id"]),
            run_id=str(raw["run_id"]),
            account_alias=str(raw["account_alias"]),
            mode=str(raw["mode"]),
            instrument_id=str(raw["instrument_id"]),
            decision_session=date.fromisoformat(str(raw["decision_session"])),
            action=str(raw["action"]),
            target_weight=Decimal(str(raw["target_weight"])),
            strategy_version=str(raw["strategy_version"]),
            model_version=None if raw.get("model_version") is None else str(raw["model_version"]),
            data_snapshot_id=str(raw["data_snapshot_id"]),
            risk_policy_version=str(raw["risk_policy_version"]),
            rationale=str(raw.get("rationale", "")),
            invalidation=tuple(str(item) for item in raw.get("invalidation", [])),
            source=str(raw.get("source", "ledger")),
        )


@dataclass(frozen=True)
class DecisionLabel:
    """The matured outcome of one decision, computed point-in-time."""

    decision_id: str
    instrument_id: str
    action: str
    target_weight: Decimal
    decision_session: date
    matured: bool
    horizons: Mapping[int, Decimal | None]
    max_drawdown: Decimal | None  # positive peak-to-trough magnitude, >= 0
    recovered: bool | None  # final close back at/above the pre-trough peak
    gapped: bool  # True when the decision session itself had no close
    matured_as_of: date
    label_digest: str = field(default="")

    def __post_init__(self) -> None:
        object.__setattr__(self, "horizons", MappingProxyType(dict(self.horizons)))
        if not self.label_digest:
            object.__setattr__(self, "label_digest", self.compute_digest())

    def is_fully_matured(self, horizons: Sequence[int]) -> bool:
        """All requested horizons have values (owner: require_matured_labels)."""
        return all(self.horizons.get(h) is not None for h in horizons)

    def compute_digest(self) -> str:
        return _digest(
            {
                "decision_id": self.decision_id,
                "action": self.action,
                "target_weight": str(self.target_weight),
                "decision_session": self.decision_session.isoformat(),
                "matured": self.matured,
                "horizons": {
                    str(h): None if v is None else str(v) for h, v in self.horizons.items()
                },
                "max_drawdown": None if self.max_drawdown is None else str(self.max_drawdown),
                "recovered": self.recovered,
                "gapped": self.gapped,
                "matured_as_of": self.matured_as_of.isoformat(),
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "instrument_id": self.instrument_id,
            "action": self.action,
            "target_weight": str(self.target_weight),
            "decision_session": self.decision_session.isoformat(),
            "matured": self.matured,
            "horizons": {str(h): None if v is None else str(v) for h, v in self.horizons.items()},
            "max_drawdown": None if self.max_drawdown is None else str(self.max_drawdown),
            "recovered": self.recovered,
            "gapped": self.gapped,
            "matured_as_of": self.matured_as_of.isoformat(),
            "label_digest": self.label_digest,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> DecisionLabel:
        horizons = {
            int(h): None if v is None else Decimal(str(v)) for h, v in raw["horizons"].items()
        }
        return cls(
            decision_id=str(raw["decision_id"]),
            instrument_id=str(raw["instrument_id"]),
            action=str(raw["action"]),
            target_weight=Decimal(str(raw["target_weight"])),
            decision_session=date.fromisoformat(str(raw["decision_session"])),
            matured=bool(raw["matured"]),
            horizons=horizons,
            max_drawdown=None
            if raw.get("max_drawdown") is None
            else Decimal(str(raw["max_drawdown"])),
            recovered=None if raw.get("recovered") is None else bool(raw["recovered"]),
            gapped=bool(raw.get("gapped", False)),
            matured_as_of=date.fromisoformat(str(raw["matured_as_of"])),
            label_digest=str(raw.get("label_digest", "")),
        )


def mature_label(
    record: DecisionRecord,
    series: CloseSeries | None,
    as_of: date,
    horizons: Sequence[int] = DEFAULT_HORIZONS,
    *,
    session_calendar: Sequence[date] | None = None,
) -> DecisionLabel:
    """No calendar means unknown maturity, so fail instead of counting price rows."""
    if session_calendar is None:
        raise LearningError("an explicit session calendar is required for label maturity")
    calendar = tuple(session_calendar)
    if calendar != tuple(sorted(set(calendar))) or record.decision_session not in calendar:
        raise LearningError("invalid session calendar or absent decision session")
    if not horizons or any(h < 1 for h in horizons):
        raise LearningError("positive nonempty horizons required")
    index = calendar.index(record.decision_session)
    forward: dict[int, Decimal | None] = {h: None for h in horizons}
    reference = series.value_on(record.decision_session) if series else None
    gapped = reference is None
    max_drawdown: Decimal | None = None
    recovered: bool | None = None
    with localcontext(Context(prec=28, rounding=ROUND_HALF_EVEN)):
        if reference is not None:
            if not reference.is_finite() or reference <= 0:
                raise LearningError("nonpositive or nonfinite reference price")
            for horizon in horizons:
                end = index + horizon
                if end < len(calendar) and calendar[end] <= as_of:
                    mark = series.value_on(calendar[end]) if series else None
                    if mark is None:
                        gapped = True
                    elif mark.is_finite() and mark > 0:
                        forward[horizon] = round8(mark / reference - 1)
                    else:
                        raise LearningError("nonpositive or nonfinite horizon price")
            if all(value is not None for value in forward.values()) and series is not None:
                marks = [
                    series.value_on(day) for day in calendar[index : index + max(horizons) + 1]
                ]
                if all(mark is not None for mark in marks):
                    peak, worst, peak_at_trough = reference, Decimal(0), reference
                    for mark in marks:
                        assert mark is not None
                        if not mark.is_finite() or mark <= 0:
                            raise LearningError("invalid drawdown price")
                        peak = max(peak, mark)
                        drawdown = round8(1 - mark / peak)
                        if drawdown > worst:
                            worst, peak_at_trough = drawdown, peak
                    max_drawdown = worst
                    final = marks[-1]
                    assert final is not None
                    recovered = final >= peak_at_trough
                else:
                    gapped = True
    return DecisionLabel(
        decision_id=record.decision_id,
        instrument_id=record.instrument_id,
        action=record.action,
        target_weight=record.target_weight,
        decision_session=record.decision_session,
        matured=all(value is not None for value in forward.values()),
        horizons=forward,
        max_drawdown=max_drawdown,
        recovered=recovered,
        gapped=gapped,
        matured_as_of=as_of,
    )


def mature_labels(
    records: Sequence[DecisionRecord],
    series_by_instrument: Mapping[str, CloseSeries | None],
    as_of: date,
    horizons: Sequence[int] = DEFAULT_HORIZONS,
    *,
    session_calendar: Sequence[date] | None = None,
) -> dict[str, DecisionLabel]:
    """Mature against supplied sessions; duplicate decision identities are invalid."""
    if len({r.decision_id for r in records}) != len(records):
        raise LearningError("duplicate decision identities")
    return {
        record.decision_id: mature_label(
            record,
            series_by_instrument.get(record.instrument_id),
            as_of,
            horizons,
            session_calendar=session_calendar,
        )
        for record in records
    }
