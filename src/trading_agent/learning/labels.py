"""Point-in-time outcome labels for decisions (build plan section 12).

A decision made at a session close is labelled with what *actually happened
after it* -- never with information that was not yet observable:

* The reference price is the close of the decision session itself (the price
  the engine executed at, 16:00 exchange time). If that session is missing
  from the data, the most recent earlier close is used and the label is
  flagged as gapped; it still matures only from completed sessions.
* A forward horizon ``h`` matures only when ``h`` completed sessions exist
  strictly after the reference session and at or before ``as_of``. A missing
  session shortens the window and the horizon stays ``None`` (the owner's
  "data gaps shorten the window; never interpolate" convention).
* Horizons use *sessions*, not calendar days, so holidays never age a label
  prematurely; a horizon is a number of completed sessions.

Labels are raw market facts. Cost and position sizing are *not* applied
here -- the evaluation layer applies the strategy's cost model, and memory
aggregates the raw outcomes. All returns are Decimal at 8-decimal precision
(owner convention). Everything is deterministic for a given input.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any, Mapping, Sequence

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
                "horizons": {str(h): None if v is None else str(v) for h, v in self.horizons.items()},
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
        horizons = {int(h): None if v is None else Decimal(str(v)) for h, v in raw["horizons"].items()}
        return cls(
            decision_id=str(raw["decision_id"]),
            instrument_id=str(raw["instrument_id"]),
            action=str(raw["action"]),
            target_weight=Decimal(str(raw["target_weight"])),
            decision_session=date.fromisoformat(str(raw["decision_session"])),
            matured=bool(raw["matured"]),
            horizons=horizons,
            max_drawdown=None if raw.get("max_drawdown") is None else Decimal(str(raw["max_drawdown"])),
            recovered=None if raw.get("recovered") is None else bool(raw["recovered"]),
            gapped=bool(raw.get("gapped", False)),
            matured_as_of=date.fromisoformat(str(raw["matured_as_of"])),
            label_digest=str(raw.get("label_digest", "")),
        )


def _reference_close(series: CloseSeries, session: date) -> tuple[Decimal, date, bool]:
    """(close, reference session date, gapped) at the decision instant.

    The decision executes at the decision session's 16:00 close, which is
    observable at decision time, so same-session reference is *not* look-ahead.
    A session missing from the data falls back to the last earlier close and
    is flagged gapped.
    """
    same_day = series.value_on(session)
    if same_day is not None:
        return same_day, session, False
    before = series.value_through(session)
    if before is None:
        return Decimal(0), session, True  # no usable data; caller leaves horizons None
    window = series.up_to(session)
    return before, window[-1][0], True


def mature_label(
    record: DecisionRecord,
    series: CloseSeries | None,
    as_of: date,
    horizons: Sequence[int] = DEFAULT_HORIZONS,
) -> DecisionLabel:
    """Mature one decision's outcome at ``as_of`` (point-in-time).

    Every price consulted is from a completed session at or before ``as_of``.
    A horizon is filled only when enough completed sessions exist; otherwise
    it stays ``None`` and the label does not count as mature for memory.
* ``max_drawdown`` is a positive magnitude (owner metrics convention:
    """
    forward: dict[int, Decimal | None] = {h: None for h in horizons}
    max_drawdown: Decimal | None = None
    recovered: bool | None = None
    gapped = False

    if series is None:
        gapped = True
    else:
        reference_close, ref_session, gapped = _reference_close(series, record.decision_session)
        if reference_close > 0:
            # Completed sessions after the reference, up to as_of.
            future = [(d, c) for d, c in series.up_to(as_of) if d > ref_session]
            for h in horizons:
                if len(future) >= h:
                    return_h = future[h - 1][1]
                    forward[h] = round8(return_h / reference_close - 1)
            if future:
                # Owner metrics convention: positive peak-to-trough magnitude.
                peak = Decimal(0)
                worst_dd = Decimal(0)
                peak_at_trough = Decimal(0)
                last_close = Decimal(0)
                for _, close in future:
                    if close > peak:
                        peak = close
                    dd = round8(1 - close / peak)
                    if dd > worst_dd:
                        worst_dd = dd
                        peak_at_trough = peak
                    last_close = close
                max_drawdown = worst_dd
                recovered = last_close >= peak_at_trough

    matured = all(v is not None for v in forward.values())
    label = DecisionLabel(
        decision_id=record.decision_id,
        instrument_id=record.instrument_id,
        action=record.action,
        target_weight=record.target_weight,
        decision_session=record.decision_session,
        matured=matured,
        horizons=forward,
        max_drawdown=max_drawdown,
        recovered=recovered,
        gapped=gapped,
        matured_as_of=as_of,
    )
    return label


def mature_labels(
    records: Sequence[DecisionRecord],
    series_by_instrument: Mapping[str, CloseSeries | None],
    as_of: date,
    horizons: Sequence[int] = DEFAULT_HORIZONS,
) -> dict[str, DecisionLabel]:
    """Mature a batch of decisions; keyed by decision_id, input order kept."""
    return {
        record.decision_id: mature_label(record, series_by_instrument.get(record.instrument_id), as_of, horizons)
        for record in records
    }
