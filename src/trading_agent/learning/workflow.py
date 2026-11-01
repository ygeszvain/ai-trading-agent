"""Bounded research experiments and proposals. No strategy activation capability."""

from __future__ import annotations

import hashlib
import itertools
import os
import re
import tempfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal, Self, TypedDict

from pydantic import AwareDatetime, Field, model_validator

from ..money import round_money, round_qty
from .labels import LearningError
from .records import (
    DatasetSnapshot,
    FrozenRecord,
    Observation,
    Session,
    Versions,
    available_observations,
    build_snapshot,
    research_decimal,
)

ZERO = Decimal(0)
ONE = Decimal(1)


class Rule(FrozenRecord):
    lookback: int = Field(ge=2, le=250)
    entry: Decimal = Field(ge=0, lt=1)
    exit: Decimal = Field(ge=-1, lt=1)
    weight: Decimal = Field(gt=0, le=1)
    features: tuple[Literal["close_momentum"], ...] = ("close_momentum",)

    @model_validator(mode="after")
    def hysteresis(self) -> Self:
        if self.entry <= self.exit or self.features != ("close_momentum",):
            raise ValueError("fixed feature and entry > exit required")
        return self


class FrozenChampion(FrozenRecord):
    champion_id: str
    rule: Rule
    versions: Versions
    universe: tuple[str, ...]
    approved_live_capital: Literal["0"] = "0"
    authority: Literal["LIVE_NOT_AUTHORIZED"] = "LIVE_NOT_AUTHORIZED"

    @model_validator(mode="after")
    def strategy_manifest(self) -> Self:
        if self.versions.strategy_hash != self.rule.digest() or not self.universe:
            raise ValueError("champion manifest must bind the exact frozen rule and universe")
        return self


class ResearchProtocol(FrozenRecord):
    version: str = "research-demo-v1"
    numerical_convention: Literal["decimal28-half-even-money8-quantity8-down"] = (
        "decimal28-half-even-money8-quantity8-down"
    )
    hypothesis: str = (
        "Prespecified momentum parameters may improve net edge; evidence may reject them."
    )
    objective: Literal["cost_adjusted_edge_vs_passive"] = "cost_adjusted_edge_vs_passive"
    train_sessions: int = Field(default=40, ge=10, le=2000)
    test_sessions: int = Field(default=20, ge=5, le=1000)
    max_folds: int = Field(default=3, ge=1, le=20)
    max_trials: int = Field(default=4, ge=1, le=20)
    max_simulation_steps: int = Field(default=2000, ge=1, le=100000)
    max_observations: int = Field(default=2000, ge=1, le=10000)
    # A fixed operation count is the reproducible compute budget; no LLM calls.
    fee_rate: Decimal = Field(default=Decimal("0.0005"), ge=0, le=Decimal("0.01"))
    slippage_rate: Decimal = Field(default=Decimal("0.0015"), ge=0, le=Decimal("0.02"))
    initial_cash: Decimal = Field(default=Decimal("10000"), gt=0)
    cash_yield_annual: Decimal = Field(default=Decimal("0.045"), ge=0, le=1)
    min_matured_labels: int = Field(default=10, ge=1)
    min_folds: int = Field(default=3, ge=2)
    min_mean_edge: Decimal = Decimal("0.005")
    min_positive_fold_share: Decimal = Field(default=Decimal("0.5"), ge=0, le=1)
    max_drawdown: Decimal = Field(default=Decimal("0.35"), ge=0, le=1)
    max_turnover: Decimal = Field(default=Decimal("1"), gt=0)
    cost_stress_multiplier: Decimal = Field(default=Decimal("3"), ge=1, le=3)
    min_shadow_sessions: int = Field(default=30, ge=30)
    drift_window: int = Field(default=5, ge=2, le=100)
    feature_drift_mean_return_threshold: Decimal = Field(default=Decimal("0.05"), gt=0, le=1)
    pause_drawdown: Decimal = Field(default=Decimal("0.05"), gt=0, le=1)
    pause_missing_observations: int = Field(default=1, ge=1)


class WindowArgs(TypedDict):
    instrument: str
    start: int
    stop: int
    protocol: ResearchProtocol


class SearchSpace(FrozenRecord):
    lookbacks: tuple[int, ...] = (5, 10)
    entries: tuple[Decimal, ...] = (Decimal("0.02"), Decimal("0.05"))
    exits: tuple[Decimal, ...] = (Decimal("0"),)
    features: tuple[Literal["close_momentum"], ...] = ("close_momentum",)

    @model_validator(mode="after")
    def bounded(self) -> Self:
        if (
            not self.lookbacks
            or not self.entries
            or not self.exits
            or len(self.lookbacks) * len(self.entries) * len(self.exits) > 100
            or self.features != ("close_momentum",)
        ):
            raise ValueError("empty, excessive, or unapproved search space")
        if any(v < 2 or v > 250 for v in self.lookbacks):
            raise ValueError("lookback outside permitted range")
        if any(not v.is_finite() or v < 0 or v >= 1 for v in self.entries):
            raise ValueError("invalid entry grid")
        if any(not v.is_finite() or v < -1 or v >= 1 for v in self.exits):
            raise ValueError("invalid exit grid")
        return self


class ExperimentPlan(FrozenRecord):
    champion_hash: str
    dataset_hash: str
    protocol: ResearchProtocol
    search: SearchSpace
    registered_at: AwareDatetime
    holdout_start: date
    source_kind: Literal["synthetic", "permitted_real"] = "synthetic"


class OperationalIncident(FrozenRecord):
    incident_id: str
    category: Literal["data_quality", "execution_observation", "operational_incident"]
    verified_at: AwareDatetime
    evidence_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    note: str
    verified: Literal[True] = True
    corrects: str | None = None


class SimulatedFill(FrozenRecord):
    session: date
    side: Literal["BUY", "SELL"]
    quantity: Decimal
    price: Decimal
    fee: Decimal
    result_kind: Literal["modeled_counterfactual"] = "modeled_counterfactual"


class BookResult(FrozenRecord):
    total_return: Decimal
    cost: Decimal
    turnover: Decimal
    drawdown: Decimal
    fills: tuple[SimulatedFill, ...]
    safe: bool
    missing: int
    equity: tuple[Decimal, ...]


@research_decimal
def simulate_window(
    rule: Rule,
    observations: tuple[Observation, ...],
    sessions: tuple[Session, ...],
    *,
    instrument: str,
    start: int,
    stop: int,
    protocol: ResearchProtocol,
    kind: Literal["momentum", "passive", "cash"] = "momentum",
    stress: bool = False,
) -> BookResult:
    """Decide from earlier completed closes; fill at the next session close.

    Slippage is in fill prices. Only explicit fees are deducted from cash;
    slippage attribution is reported as cost, never deducted twice.
    """
    cash, units = protocol.initial_cash, ZERO
    peak, drawdown, cost, notional = cash, ZERO, ZERO, ZERO
    equities: list[Decimal] = []
    fills: list[SimulatedFill] = []
    if not 0 <= start < stop <= len(sessions):
        raise LearningError("invalid simulation window")
    safe, missing = True, 0
    last_mark: Decimal | None = None
    multiplier = protocol.cost_stress_multiplier if stress else ONE
    rate, slip = protocol.fee_rate * multiplier, protocol.slippage_rate * multiplier
    for index in range(start, stop):
        session = sessions[index]
        # Snapshot at execution time; corrections published later cannot leak back.
        current = available_observations(observations, session.closes_at)
        observation = current.get((instrument, session.session))
        # A decision using the previous close is formed before this close exists.
        cutoff = sessions[index - 1].closes_at if index else session.closes_at
        past = available_observations(observations, cutoff)
        window = [
            past.get((instrument, s.session))
            for s in sessions[max(0, index - rule.lookback - 1) : index]
        ]
        target = units > 0
        if kind == "cash":
            target = False
        elif kind == "passive":
            target = True
        elif len(window) == rule.lookback + 1 and all(window):
            first, last = window[0], window[-1]
            assert first is not None and last is not None
            score = last.close / first.close - 1
            target = score >= (rule.exit if units > 0 else rule.entry)
        else:
            target = False  # insufficient history blocks a new position
        if observation is None:
            missing += 1
            safe = False
        else:
            mark = observation.close
            last_mark = mark
            if target and units == 0:
                price = round_money(mark * (1 + slip))
                if price <= 0:
                    raise LearningError("modeled execution price rounds to zero")
                nav = cash
                quantity = round_qty(nav * rule.weight / (price * (1 + rate)), 8)
                fee = round_money(quantity * price * rate)
                cash = round_money(cash - quantity * price - fee)
                units = quantity
                cost += round_money(fee + quantity * (price - mark))
                notional += quantity * price
                fills.append(
                    SimulatedFill(
                        session=session.session,
                        side="BUY",
                        quantity=quantity,
                        price=price,
                        fee=fee,
                    )
                )
            elif not target and units > 0:
                price = round_money(mark * (1 - slip))
                if price <= 0:
                    raise LearningError("modeled execution price rounds to zero")
                fee = round_money(units * price * rate)
                cash = round_money(cash + units * price - fee)
                cost += round_money(fee + units * (mark - price))
                notional += units * price
                fills.append(
                    SimulatedFill(
                        session=session.session,
                        side="SELL",
                        quantity=units,
                        price=price,
                        fee=fee,
                    )
                )
                units = ZERO
        cash = round_money(cash * (1 + protocol.cash_yield_annual / Decimal(252)))
        equity = round_money(cash + units * (last_mark or ZERO))
        peak = max(peak, equity)
        drawdown = max(drawdown, 1 - equity / peak)
        safe = safe and cash >= 0 and units >= 0 and equity > 0
        equities.append(equity)
    return BookResult(
        total_return=equities[-1] / protocol.initial_cash - 1 if equities else ZERO,
        cost=cost,
        turnover=notional / protocol.initial_cash,
        drawdown=drawdown,
        fills=tuple(fills),
        safe=safe and bool(equities),
        missing=missing,
        equity=tuple(equities),
    )


class FoldComparison(FrozenRecord):
    train_end: date
    test_start: date
    test_end: date
    candidate: BookResult
    champion_return: Decimal
    passive_return: Decimal
    cash_return: Decimal
    stressed: BookResult
    edge: Decimal
    edge_vs_champion: Decimal


class Trial(FrozenRecord):
    trial_id: str
    parameters: tuple[tuple[str, str], ...]
    rule: Rule | None
    status: Literal["STARTED", "EVALUATED", "FAILED", "BUDGET_EXHAUSTED"]
    reasons: tuple[str, ...]
    folds: tuple[FoldComparison, ...] = ()
    mean_edge: Decimal | None = None
    edge_range: tuple[Decimal, Decimal] | None = None
    qualified_for_shadow: bool = False
    simulation_steps: int = 0


class ShadowState(FrozenRecord):
    rule: Rule
    plan_hash: str
    registered_at: AwareDatetime
    seed_history: tuple[Observation, ...]
    observations: tuple[Observation, ...] = ()
    sessions: tuple[Session, ...] = ()
    source_kind: Literal["synthetic", "permitted_real"]
    paused: bool = False
    simulation_steps: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_registration(self) -> Self:
        if any(v.available_at > self.registered_at for v in self.seed_history):
            raise ValueError("future shadow seed history")
        if any(v.source_kind != self.source_kind for v in (*self.seed_history, *self.observations)):
            raise ValueError("shadow source mismatch")
        if any(v.available_at <= self.registered_at for v in self.observations):
            raise ValueError("historical observation in prospective stream")
        dates = tuple(s.session for s in self.sessions)
        if dates != tuple(sorted(set(dates))):
            raise ValueError("shadow sessions must advance")
        return self


def append_shadow(
    state: ShadowState,
    observation: Observation | None,
    session: Session,
    *,
    now: datetime,
    max_sessions: int = 100,
) -> ShadowState:
    """Only observations arriving after registration; replay is never prospective evidence."""
    if not 1 <= max_sessions <= 100:
        raise LearningError("shadow session budget must be in 1..100")
    if (
        state.paused
        or session.closes_at <= state.registered_at
        or session.closes_at > now
        or len(state.sessions) >= max_sessions
    ):
        raise LearningError("shadow cursor is historical, future, paused, or over budget")
    if state.sessions and session.session <= state.sessions[-1].session:
        raise LearningError(
            "shadow cursor must advance without duplicate or reordered observations"
        )
    if observation is not None:
        if (
            observation.available_at <= state.registered_at
            or observation.available_at > now
            or session.closes_at > observation.available_at
            or observation.session != session.session
            or observation.revision != 0
            or observation.correction_of is not None
            or observation.source_kind != state.source_kind
        ):
            raise LearningError(
                "shadow observation is historical, future, corrected, or wrong source"
            )
        if state.observations and observation.available_at <= state.observations[-1].available_at:
            raise LearningError("shadow availability cursor must advance")
        if state.seed_history and observation.instrument != state.seed_history[0].instrument:
            raise LearningError("shadow instrument is outside the frozen universe")
    return ShadowState.model_validate(
        {
            **state.model_dump(),
            "observations": (*state.observations, observation)
            if observation
            else state.observations,
            "sessions": (*state.sessions, session),
        }
    )


class DriftAlert(FrozenRecord):
    rule: str
    trigger: str
    action: Literal["PAUSE_RESEARCH_CANDIDATE"] = "PAUSE_RESEARCH_CANDIDATE"
    replacement_strategy: None = None


@research_decimal
def drift_alerts(
    book: BookResult,
    protocol: ResearchProtocol,
    *,
    baseline_mean_return: Decimal | None = None,
    recent_returns: tuple[Decimal, ...] = (),
) -> tuple[DriftAlert, ...]:
    alerts: list[DriftAlert] = []
    if book.missing >= protocol.pause_missing_observations:
        alerts.append(DriftAlert(rule="missing-observations", trigger=str(book.missing)))
    tail = book.equity[-protocol.drift_window :]
    trailing = (1 - tail[-1] / max(tail)) if tail else ZERO
    if book.drawdown >= protocol.pause_drawdown or trailing >= protocol.pause_drawdown:
        alerts.append(DriftAlert(rule="drawdown", trigger=str(max(trailing, book.drawdown))))
    if baseline_mean_return is not None and len(recent_returns) >= protocol.drift_window:
        recent_mean = sum(recent_returns[-protocol.drift_window :], ZERO) / protocol.drift_window
        change = abs(recent_mean - baseline_mean_return)
        if change >= protocol.feature_drift_mean_return_threshold:
            alerts.append(DriftAlert(rule="mean-session-return-drift", trigger=str(change)))
    return tuple(alerts)


class PromotionProposal(FrozenRecord):
    schema_version: Literal["1"] = "1"
    hypothesis: str
    change_class: Literal["research_parameters_only"] = "research_parameters_only"
    champion_hash: str
    rollback_target: str
    candidate_hash: str | None
    diff: tuple[tuple[str, str, str], ...]
    dataset_hash: str
    plan_hash: str
    all_trial_hashes: tuple[str, ...]
    versions: Versions
    prerequisites: tuple[str, ...]
    authorization: None = None
    activation_allowed: Literal[False] = False
    status: Literal["BLOCKED_RESEARCH_PROPOSAL"] = "BLOCKED_RESEARCH_PROPOSAL"

    def activate(self) -> None:
        raise LearningError("research packages have no activation capability; LIVE_NOT_AUTHORIZED")


class ExperimentReport(FrozenRecord):
    schema_version: Literal["1"] = "1"
    dataset: DatasetSnapshot
    frozen_champion: FrozenChampion
    champion_after_hash: str
    plan: ExperimentPlan
    trials: tuple[Trial, ...]
    unattempted_parameters: int
    simulation_steps: int
    operational_memory: tuple[OperationalIncident, ...]
    shadow: ShadowState | None
    shadow_book: BookResult | None
    alerts: tuple[DriftAlert, ...]
    proposal: PromotionProposal
    mechanism: Literal["matured outcome tracking and offline parameter research"] = (
        "matured outcome tracking and offline parameter research"
    )
    weights_trained: Literal[False] = False
    active_parameters_changed: Literal[False] = False

    @model_validator(mode="after")
    def integrity(self) -> Self:
        if (
            self.plan.dataset_hash != self.dataset.digest()
            or self.plan.champion_hash != self.frozen_champion.digest()
            or self.champion_after_hash != self.plan.champion_hash
            or self.proposal.plan_hash != self.plan.digest()
            or self.proposal.all_trial_hashes != tuple(t.digest() for t in self.trials)
        ):
            raise ValueError("experiment provenance or unchanged champion check failed")
        if (
            self.simulation_steps != sum(t.simulation_steps for t in self.trials)
            or self.simulation_steps > self.plan.protocol.max_simulation_steps
            or self.proposal.champion_hash != self.frozen_champion.digest()
            or self.proposal.rollback_target != self.frozen_champion.digest()
            or self.proposal.dataset_hash != self.dataset.digest()
            or self.proposal.versions != self.frozen_champion.versions
        ):
            raise ValueError("proposal evidence or reserved compute budget mismatch")
        if self.shadow is not None and (
            self.shadow.plan_hash != self.plan.digest()
            or self.shadow.source_kind != self.plan.source_kind
            or self.shadow.simulation_steps + self.simulation_steps
            > self.plan.protocol.max_simulation_steps
            or not any(t.rule == self.shadow.rule for t in self.trials)
            or self.shadow.paused != bool(self.alerts)
            or self.shadow_book is None
        ):
            raise ValueError("shadow scope, pause, or budget mismatch")
        return self


@research_decimal
def run_experiment(
    dataset: DatasetSnapshot,
    champion: FrozenChampion,
    plan: ExperimentPlan,
    operational_memory: tuple[OperationalIncident, ...] = (),
    *,
    artifact_root: Path | None = None,
) -> ExperimentReport:
    """One preregistered grid, one unchanged objective, zero holdout selection."""
    # Revalidate rather than trusting model_copy(update=...) to enforce constraints.
    dataset = DatasetSnapshot.model_validate(dataset.model_dump())
    champion = FrozenChampion.model_validate(champion.model_dump())
    plan = ExperimentPlan.model_validate(plan.model_dump())
    if (
        plan.dataset_hash != dataset.digest()
        or plan.champion_hash != champion.digest()
        or plan.holdout_start != dataset.holdout_start
        or plan.registered_at < dataset.as_of
    ):
        raise LearningError("experiment manifest does not match frozen inputs")
    if len(champion.universe) != 1:
        raise LearningError("v1 research evaluator requires exactly one frozen instrument")
    if any(r.instrument not in champion.universe for r in dataset.records):
        raise LearningError("dataset instrument outside frozen universe")
    if any(v.source_kind != plan.source_kind for v in dataset.observations):
        raise LearningError("declared evidence source does not match observation provenance")
    if len(dataset.observations) > plan.protocol.max_observations:
        raise LearningError("observation compute budget exceeded")
    rebuilt = build_snapshot(
        scope=dataset.scope,
        records=dataset.records,
        observations=dataset.observations,
        sessions=dataset.sessions,
        as_of=dataset.as_of,
        horizons=dataset.horizons,
        holdout_start=dataset.holdout_start,
    )
    if (
        tuple(v.model_copy(update={"supersedes": None}) for v in dataset.outcomes)
        != rebuilt.outcomes
    ):
        raise LearningError("dataset labels do not match point-in-time evidence")
    protocol = plan.protocol
    # Do not even hand the final holdout observations to the evaluator.
    observations = tuple(v for v in dataset.observations if v.session < plan.holdout_start)
    sessions = tuple(
        s
        for s in dataset.sessions
        if s.session < plan.holdout_start and s.closes_at <= dataset.as_of
    )
    bounds: list[tuple[int, int]] = []
    for start in range(protocol.train_sessions, len(sessions), protocol.test_sessions):
        stop = start + protocol.test_sessions
        if stop <= len(sessions) and len(bounds) < protocol.max_folds:
            bounds.append((start, stop))
    grid = tuple(itertools.product(plan.search.lookbacks, plan.search.entries, plan.search.exits))
    trials: list[Trial] = []
    if artifact_root is not None:
        save_artifact(dataset, artifact_root, "datasets")
        save_artifact(champion, artifact_root, "champions")
        save_artifact(plan, artifact_root, "plans")
        for incident in operational_memory:
            save_artifact(incident, artifact_root, "incidents")

    def record_trial(trial: Trial) -> None:
        if artifact_root is not None:
            save_artifact(trial, artifact_root, "trials")
        trials.append(trial)

    steps = 0
    for index, (lookback, entry, exit_) in enumerate(grid[: protocol.max_trials]):
        params = (("lookback", str(lookback)), ("entry", str(entry)), ("exit", str(exit_)))
        trial_id = hashlib.sha256(f"{plan.digest()}:{index}".encode()).hexdigest()
        if artifact_root is not None:
            save_artifact(
                Trial(
                    trial_id=trial_id, parameters=params, rule=None, status="STARTED", reasons=()
                ),
                artifact_root,
                "trials",
            )
        try:
            rule = Rule(
                lookback=lookback,
                entry=entry,
                exit=exit_,
                weight=champion.rule.weight,
                features=plan.search.features,
            )
        except ValueError as error:
            record_trial(
                Trial(
                    trial_id=trial_id,
                    parameters=params,
                    rule=None,
                    status="FAILED",
                    reasons=(f"invalid_candidate: {type(error).__name__}",),
                )
            )
            continue
        needed = sum(stop - start for start, stop in bounds) * 5
        if steps + needed > protocol.max_simulation_steps:
            record_trial(
                Trial(
                    trial_id=trial_id,
                    parameters=params,
                    rule=rule,
                    status="BUDGET_EXHAUSTED",
                    reasons=("simulation_step_budget",),
                )
            )
            continue
        steps += needed  # reserve the complete trial budget even if evaluation fails
        results: list[FoldComparison] = []
        reasons: list[str] = []
        if len(bounds) < protocol.min_folds:
            reasons.append("insufficient_walk_forward_folds")
        if len(dataset.training_outcomes()) < protocol.min_matured_labels:
            reasons.append("insufficient_matured_labels")
        try:
            for start, stop in bounds:
                kwargs: WindowArgs = dict(
                    instrument=champion.universe[0], start=start, stop=stop, protocol=protocol
                )
                candidate = simulate_window(rule, observations, sessions, **kwargs)
                reference = simulate_window(champion.rule, observations, sessions, **kwargs)
                passive = simulate_window(
                    Rule(lookback=2, entry=ZERO, exit=Decimal("-1"), weight=ONE),
                    observations,
                    sessions,
                    kind="passive",
                    **kwargs,
                )
                cash = simulate_window(rule, observations, sessions, kind="cash", **kwargs)
                stressed = simulate_window(rule, observations, sessions, stress=True, **kwargs)
                results.append(
                    FoldComparison(
                        train_end=sessions[start - 1].session,
                        test_start=sessions[start].session,
                        test_end=sessions[stop - 1].session,
                        candidate=candidate,
                        champion_return=reference.total_return,
                        passive_return=passive.total_return,
                        cash_return=cash.total_return,
                        stressed=stressed,
                        edge=candidate.total_return - passive.total_return,
                        edge_vs_champion=candidate.total_return - reference.total_return,
                    )
                )
                if not all(book.safe for book in (candidate, reference, passive, cash, stressed)):
                    reasons.append("safety_or_missing_data_regression")
                if max(candidate.drawdown, stressed.drawdown) > protocol.max_drawdown:
                    reasons.append("drawdown_regression")
                if max(candidate.turnover, stressed.turnover) > protocol.max_turnover:
                    reasons.append("turnover_budget")
                if stressed.total_return <= cash.total_return:
                    reasons.append("cost_stress_not_above_cash")
        except (ValueError, ArithmeticError, LearningError) as error:
            record_trial(
                Trial(
                    trial_id=trial_id,
                    parameters=params,
                    rule=rule,
                    status="FAILED",
                    reasons=(f"evaluation_failed: {type(error).__name__}",),
                    folds=tuple(results),
                    simulation_steps=needed,
                )
            )
            continue
        edges = tuple(f.edge for f in results)
        mean = sum(edges, ZERO) / len(edges) if edges else None
        # Observed range is dispersion, not a calibrated confidence interval.
        uncertainty = (min(edges), max(edges)) if edges else None
        if mean is None or mean < protocol.min_mean_edge:
            reasons.append("inadequate_net_edge")
        if (
            not edges
            or Decimal(sum(e > 0 for e in edges)) / len(edges) < protocol.min_positive_fold_share
        ):
            reasons.append("insufficient_positive_fold_share")
        if uncertainty is None or uncertainty[0] <= 0:
            reasons.append("uncertainty_includes_nonpositive_edge")
        if results and any(f.edge_vs_champion <= 0 for f in results):
            reasons.append("not_robustly_above_champion")
        if plan.source_kind == "synthetic":
            reasons.append("synthetic_evidence_only")
        record_trial(
            Trial(
                trial_id=trial_id,
                parameters=params,
                rule=rule,
                status="EVALUATED",
                reasons=tuple(sorted(set(reasons))),
                folds=tuple(results),
                mean_edge=mean,
                edge_range=uncertainty,
                qualified_for_shadow=not reasons,
                simulation_steps=needed,
            )
        )
    # Proposals may be prepared for rejected candidates, but retain all blockers.
    evaluated = [t for t in trials if t.mean_edge is not None and t.rule is not None]
    best = max(evaluated, key=lambda t: t.mean_edge or ZERO) if evaluated else None
    proposed_rule = best.rule if best else None
    before, after = (
        champion.rule.model_dump(mode="json"),
        (proposed_rule.model_dump(mode="json") if proposed_rule else {}),
    )
    diff = tuple(
        (key, str(before[key]), str(after[key]))
        for key in sorted(after)
        if before[key] != after[key]
    )
    proposal = PromotionProposal(
        hypothesis=protocol.hypothesis,
        champion_hash=champion.digest(),
        rollback_target=champion.digest(),
        candidate_hash=proposed_rule.digest() if proposed_rule else None,
        diff=diff,
        dataset_hash=dataset.digest(),
        plan_hash=plan.digest(),
        all_trial_hashes=tuple(t.digest() for t in trials),
        versions=champion.versions,
        prerequisites=tuple(
            sorted(
                set(
                    (best.reasons if best else ("no_evaluated_candidate",))
                    + (
                        "owner_authorization_absent",
                        "activation_service_not_implemented",
                        "prospective_shadow_sessions_pending",
                        "independent_uncertainty_review_required",
                        "runtime_risk_recovery_regressions_pending",
                        "prior_milestone_acceptance_pending",
                    )
                )
            )
        ),
    )
    return ExperimentReport(
        dataset=dataset,
        frozen_champion=champion,
        champion_after_hash=champion.digest(),
        plan=plan,
        trials=tuple(trials),
        unattempted_parameters=max(0, len(grid) - protocol.max_trials),
        simulation_steps=steps,
        operational_memory=operational_memory,
        shadow=None,
        shadow_book=None,
        alerts=(),
        proposal=proposal,
    )


def register_shadow(
    report: ExperimentReport,
    trial_id: str,
    *,
    registered_at: datetime,
) -> ShadowState:
    trial = next((t for t in report.trials if t.trial_id == trial_id), None)
    if trial is None or trial.rule is None or trial.status != "EVALUATED":
        raise LearningError("shadow registration requires an evaluated candidate")
    if report.plan.source_kind != "synthetic" and not trial.qualified_for_shadow:
        raise LearningError("inadequate evidence for prospective shadow registration")
    if registered_at < report.plan.registered_at:
        raise LearningError("shadow registration cannot predate the experiment")
    return ShadowState(
        rule=trial.rule,
        plan_hash=report.plan.digest(),
        registered_at=registered_at,
        seed_history=tuple(
            v for v in report.dataset.observations if v.session < report.plan.holdout_start
        ),
        source_kind=report.plan.source_kind,
    )


@research_decimal
def advance_shadow(
    report: ExperimentReport,
    state: ShadowState,
    observation: Observation | None,
    session: Session,
    *,
    now: datetime,
) -> tuple[ShadowState, BookResult, tuple[DriftAlert, ...]]:
    expected_seed = tuple(
        v for v in report.dataset.observations if v.session < report.plan.holdout_start
    )
    if (
        state.plan_hash != report.plan.digest()
        or state.seed_history != expected_seed
        or not any(t.rule == state.rule for t in report.trials)
    ):
        raise LearningError("shadow configuration differs from its frozen experiment")
    needed = state.simulation_steps + len(state.sessions) + 1
    if report.simulation_steps + needed > report.plan.protocol.max_simulation_steps:
        raise LearningError("shadow simulation compute budget exceeded")
    updated = append_shadow(state, observation, session, now=now)
    history = tuple(s for s in report.dataset.sessions if s.session < report.plan.holdout_start)
    book = simulate_window(
        state.rule,
        (*state.seed_history, *updated.observations),
        (*history, *updated.sessions),
        instrument=report.frozen_champion.universe[0],
        start=len(history),
        stop=len(history) + len(updated.sessions),
        protocol=report.plan.protocol,
    )
    reference = available_observations(state.seed_history, state.registered_at)
    baseline_prices = tuple(
        reference[(report.frozen_champion.universe[0], s.session)].close
        for s in history[: report.plan.protocol.train_sessions]
        if (report.frozen_champion.universe[0], s.session) in reference
    )
    baseline_returns = tuple(
        b / a - 1 for a, b in zip(baseline_prices, baseline_prices[1:], strict=False)
    )
    recent_prices = tuple(v.close for v in updated.observations)
    recent_returns = tuple(
        b / a - 1 for a, b in zip(recent_prices, recent_prices[1:], strict=False)
    )
    baseline_mean = (
        (sum(baseline_returns, ZERO) / len(baseline_returns)) if baseline_returns else None
    )
    alerts = drift_alerts(
        book,
        report.plan.protocol,
        baseline_mean_return=baseline_mean,
        recent_returns=recent_returns,
    )
    updated = ShadowState.model_validate(
        {
            **updated.model_dump(),
            "simulation_steps": needed,
            "paused": bool(alerts),
        }
    )
    return updated, book, alerts


def save_artifact(
    record: FrozenRecord,
    root: Path,
    kind: Literal["experiments", "datasets", "champions", "plans", "trials", "incidents"],
) -> Path:
    """Write-once content-addressed artifacts; repeated identical saves are a no-op."""
    directory = root.expanduser().resolve() / kind
    if directory.is_symlink():
        raise LearningError("research store directory cannot be a symlink")
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{record.digest()}.json"
    payload = record.model_dump_json(indent=2) + "\n"
    descriptor, temporary = tempfile.mkstemp(dir=directory)
    try:
        with os.fdopen(descriptor, "w") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, target)  # exclusive create; never replace a prior artifact
        except FileExistsError:
            if target.is_symlink() or target.read_text() != payload:
                raise LearningError("immutable research artifact conflict") from None
    finally:
        os.unlink(temporary)
    return target


def save_report(report: ExperimentReport, root: Path) -> Path:
    return save_artifact(report, root, "experiments")


def load_report(root: Path, experiment_id: str) -> ExperimentReport:
    if not re.fullmatch(r"[a-f0-9]{64}", experiment_id):
        raise LearningError("invalid experiment id")
    directory = root.expanduser().resolve() / "experiments"
    target = directory / f"{experiment_id}.json"
    if directory.is_symlink() or target.is_symlink() or target.stat().st_size > 10_000_000:
        raise LearningError("invalid or oversized research artifact")
    report = ExperimentReport.model_validate_json(target.read_text())
    if report.digest() != experiment_id:
        raise LearningError("research artifact hash mismatch")
    return report
