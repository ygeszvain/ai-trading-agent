"""Immutable, point-in-time research evidence; never a runtime strategy store."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from functools import wraps
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from .labels import LearningError, round8


def research_decimal[**P, T](function: Callable[P, T]) -> Callable[P, T]:
    """Use the same explicit Decimal context regardless of the caller's context."""

    @wraps(function)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
        with localcontext(Context(prec=28, rounding=ROUND_HALF_EVEN)):
            return function(*args, **kwargs)

    return wrapped


class FrozenRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    def digest(self) -> str:
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()


class Scope(FrozenRecord):
    account_alias: str = Field(min_length=1)
    mode: Literal["simulation", "paper", "shadow"] = "simulation"
    run_id: str = Field(min_length=1)


class Versions(FrozenRecord):
    code_hash: str
    dependency_hash: str
    source_hash: str
    model_hash: str
    prompt_hash: str
    feature_hash: str
    strategy_hash: str
    policy_hash: str


class Evidence(FrozenRecord):
    evidence_id: str
    observed_at: AwareDatetime
    sanitized_content: str
    content_hash: str

    @model_validator(mode="after")
    def verify_content(self) -> Self:
        if hashlib.sha256(self.sanitized_content.encode()).hexdigest() != self.content_hash:
            raise ValueError("evidence content hash mismatch")
        return self


class Intent(FrozenRecord):
    intent_id: str
    action: Literal["HOLD", "ENTER", "EXIT", "REJECTED"]
    quantity: Decimal = Field(ge=0)
    limit_price: Decimal | None = Field(default=None, gt=0)
    target_weight: Decimal = Field(ge=0, le=1)
    risk_reasons: tuple[str, ...] = ()


class RecordedFill(FrozenRecord):
    fill_id: str
    at: AwareDatetime
    side: Literal["BUY", "SELL"]
    quantity: Decimal = Field(gt=0)
    price: Decimal = Field(gt=0)
    fee: Decimal = Field(ge=0)
    correction_of: str | None = None


class RecordedDecision(FrozenRecord):
    decision_id: str
    scope: Scope
    instrument: str
    session: date
    decided_at: AwareDatetime
    versions: Versions
    evidence: tuple[Evidence, ...]
    intent: Intent
    portfolio_snapshot_hash: str
    available_cash: Decimal | None = Field(default=None, ge=0)
    positions: tuple[tuple[str, Decimal], ...] = ()
    fills: tuple[RecordedFill, ...] = ()
    operating_cost: Decimal = Field(default=Decimal(0), ge=0)
    reconciled_realized_pnl: Decimal | None = None
    reconciliation_hash: str | None = None
    reconciled_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_evidence(self) -> Self:
        if any(item.observed_at > self.decided_at for item in self.evidence):
            raise ValueError("decision evidence was not available at decision time")
        if self.reconciled_realized_pnl is not None and (
            not self.reconciliation_hash or self.reconciled_at is None
        ):
            raise ValueError("realized P&L requires a reconciliation reference")
        if self.reconciled_at is not None and any(f.at > self.reconciled_at for f in self.fills):
            raise ValueError("reconciliation precedes a fill")
        if len({item.fill_id for item in self.fills}) != len(self.fills):
            raise ValueError("duplicate fill identifiers")
        return self


class Session(FrozenRecord):
    session: date
    closes_at: AwareDatetime


class Observation(FrozenRecord):
    instrument: str
    session: date
    available_at: AwareDatetime
    close: Decimal = Field(gt=0)
    source_hash: str
    source_kind: Literal["synthetic", "permitted_real"] = "synthetic"
    revision: int = Field(default=0, ge=0)
    correction_of: str | None = None


class Outcome(FrozenRecord):
    decision_id: str
    horizon_sessions: int = Field(gt=0)
    target_session: date | None
    status: Literal["PENDING", "INCOMPLETE", "MATURED"]
    kind: Literal["hypothetical_mark", "modeled_counterfactual"]
    market_return: Decimal | None
    released_at: AwareDatetime | None
    # A mark is never described as a realized or a missed gain. Realized P&L
    # below comes only from the separately reconciled fill/ledger input.
    realized_kind: Literal["realized"] | None = None
    reconciled_realized_pnl: Decimal | None = None
    explicit_fees: Decimal
    operating_cost: Decimal
    observation_hashes: tuple[str, ...]
    supersedes: str | None = None


class DatasetSnapshot(FrozenRecord):
    scope: Scope
    as_of: AwareDatetime
    records: tuple[RecordedDecision, ...]
    sessions: tuple[Session, ...]
    observations: tuple[Observation, ...]
    horizons: tuple[int, ...]
    holdout_start: date
    previous_snapshot_hash: str | None = None
    label_history: tuple[Outcome, ...]
    outcomes: tuple[Outcome, ...]

    def training_outcomes(self) -> tuple[Outcome, ...]:
        return tuple(
            item
            for item in self.outcomes
            if item.status == "MATURED"
            and item.target_session is not None
            and item.target_session < self.holdout_start
        )


def available_observations(
    observations: tuple[Observation, ...], as_of: datetime
) -> dict[tuple[str, date], Observation]:
    selected: dict[tuple[str, date], Observation] = {}
    for item in sorted(observations, key=lambda v: (v.available_at, v.revision)):
        if item.available_at > as_of:
            continue
        key = (item.instrument, item.session)
        previous = selected.get(key)
        if previous is not None:
            if item.digest() == previous.digest():
                continue
            if item.revision <= previous.revision or item.correction_of != previous.digest():
                raise LearningError("observation revision must link to its predecessor")
        elif item.revision != 0 or item.correction_of is not None:
            raise LearningError("observation correction is missing its predecessor")
        selected[key] = item
    return selected


@research_decimal
def build_snapshot(
    *,
    scope: Scope,
    records: tuple[RecordedDecision, ...],
    observations: tuple[Observation, ...],
    sessions: tuple[Session, ...],
    as_of: datetime,
    horizons: tuple[int, ...],
    holdout_start: date,
    previous: DatasetSnapshot | None = None,
) -> DatasetSnapshot:
    """Use explicit exchange sessions and availability; never shift a missing horizon."""
    if len(records) > 10000 or len(observations) > 10000 or len(sessions) > 10000:
        raise LearningError("dataset input budget exceeded")
    if len(horizons) > 10 or any(h > 252 for h in horizons):
        raise LearningError("label horizon budget exceeded")
    if not horizons or any(h < 1 for h in horizons) or len(set(horizons)) != len(horizons):
        raise LearningError("label horizons must be unique positive session counts")
    dates = [s.session for s in sessions]
    if dates != sorted(set(dates)) or any(
        a.closes_at >= b.closes_at for a, b in zip(sessions, sessions[1:], strict=False)
    ):
        raise LearningError("session calendar must be unique and chronological")
    if len({r.decision_id for r in records}) != len(records):
        raise LearningError("duplicate decision identifiers")
    if previous is not None and (previous.scope != scope or previous.as_of > as_of):
        raise LearningError("prior label history has a different scope or future cutoff")
    if previous is not None and not {r.decision_id for r in previous.records}.issubset(
        {r.decision_id for r in records}
    ):
        raise LearningError("a revision cannot discard previous decisions")
    closes = {s.session: s.closes_at for s in sessions}
    if any(v.session not in closes or v.available_at < closes[v.session] for v in observations):
        raise LearningError(
            "close observation is absent from calendar or available before session close"
        )
    selected = available_observations(observations, as_of)
    history = list(previous.label_history if previous else ())
    prior = {
        (v.decision_id, v.horizon_sessions): v for v in (previous.outcomes if previous else ())
    }
    outcomes: list[Outcome] = []
    for record in sorted(records, key=lambda r: (r.session, r.decision_id)):
        if record.scope != scope or record.decided_at > as_of:
            raise LearningError("decision scope or availability mismatch")
        if any(fill.at > as_of for fill in record.fills):
            raise LearningError("future fill in dataset snapshot")
        if record.session not in dates:
            raise LearningError("decision session is absent from the declared calendar")
        index = dates.index(record.session)
        for horizon in sorted(horizons):
            end = index + horizon
            target = sessions[end] if end < len(sessions) else None
            ready = target is not None and target.closes_at <= as_of
            ref = selected.get((record.instrument, record.session))
            mark = selected.get((record.instrument, target.session)) if target else None
            # Reference must also have completed: available prices cannot release
            # a label before the explicitly declared target session has closed.
            complete = ready and ref is not None and mark is not None
            realized = (
                complete
                and target is not None
                and record.reconciled_at is not None
                and record.reconciled_at <= target.closes_at
            )
            fee_cutoff = target.closes_at if ready and target else record.decided_at
            item = Outcome(
                decision_id=record.decision_id,
                horizon_sessions=horizon,
                target_session=target.session if target else None,
                status="MATURED" if complete else "INCOMPLETE" if ready else "PENDING",
                kind=(
                    "modeled_counterfactual"
                    if record.intent.action == "REJECTED"
                    else "hypothetical_mark"
                ),
                market_return=round8(mark.close / ref.close - 1)
                if complete and ref and mark
                else None,
                released_at=max(target.closes_at, ref.available_at, mark.available_at)
                if complete and target and ref and mark
                else None,
                realized_kind="realized"
                if realized and record.reconciled_realized_pnl is not None
                else None,
                reconciled_realized_pnl=record.reconciled_realized_pnl if realized else None,
                explicit_fees=sum((f.fee for f in record.fills if f.at <= fee_cutoff), Decimal(0)),
                operating_cost=record.operating_cost,
                observation_hashes=tuple(v.digest() for v in (ref, mark) if v) if ready else (),
            )
            old = prior.get((record.decision_id, horizon))
            if old:
                comparable = old.model_copy(update={"supersedes": None})
                if comparable == item:
                    item = old
                else:
                    item = item.model_copy(update={"supersedes": old.digest()})
            if not old or old != item:
                history.append(item)
            outcomes.append(item)
    return DatasetSnapshot(
        scope=scope,
        as_of=as_of,
        records=tuple(sorted(records, key=lambda r: r.decision_id)),
        sessions=sessions,
        observations=tuple(v for v in observations if v.available_at <= as_of),
        horizons=tuple(sorted(horizons)),
        holdout_start=holdout_start,
        outcomes=tuple(outcomes),
        label_history=tuple(history),
        previous_snapshot_hash=previous.digest() if previous else None,
    )
