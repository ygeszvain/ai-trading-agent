"""Deterministic offline learning demonstration: synthetic evidence, proposals only."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal

from .records import (
    DatasetSnapshot,
    Evidence,
    Intent,
    Observation,
    RecordedDecision,
    RecordedFill,
    Scope,
    Session,
    Versions,
    build_snapshot,
    research_decimal,
)
from .workflow import (
    ExperimentPlan,
    ExperimentReport,
    FrozenChampion,
    OperationalIncident,
    ResearchProtocol,
    Rule,
    SearchSpace,
    advance_shadow,
    register_shadow,
    run_experiment,
    save_report,
)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


@research_decimal
def demo_inputs() -> tuple[
    ExperimentPlan,
    FrozenChampion,
    DatasetSnapshot,
    tuple[Session, ...],
    tuple[Observation, ...],
    DatasetSnapshot,
]:
    """Return fixed fixtures; weekdays here are a declared synthetic session calendar."""
    root = Path(__file__).resolve().parents[3]
    sessions: list[Session] = []
    day = date(2025, 1, 6)
    while len(sessions) < 150:
        if day.weekday() < 5:
            sessions.append(Session(session=day, closes_at=datetime.combine(day, time(21), UTC)))
        day += timedelta(days=1)
    calendar = tuple(sessions)
    observations = tuple(
        Observation(
            instrument="TEST_A",
            session=s.session,
            available_at=s.closes_at,
            close=Decimal(100) + Decimal(i % 25) * Decimal("0.8") - Decimal(i // 25),
            source_hash=_hash(f"synthetic-fixture-v1:{i}"),
        )
        for i, s in enumerate(calendar)
        if i != 113
    )
    rule = Rule(lookback=20, entry=Decimal("0.05"), exit=Decimal(0), weight=Decimal("0.05"))
    versions = Versions(
        code_hash=_hash(
            json.dumps(
                [
                    (str(path.relative_to(root)), hashlib.sha256(path.read_bytes()).hexdigest())
                    for path in sorted((root / "src").rglob("*.py"))
                ],
                separators=(",", ":"),
            )
        ),
        dependency_hash=hashlib.sha256((root / "uv.lock").read_bytes()).hexdigest(),
        source_hash=_hash("synthetic-fixture-v1"),
        model_hash=_hash("deterministic:no-model"),
        prompt_hash=_hash("no-inference"),
        feature_hash=_hash("close-momentum-v1"),
        strategy_hash=rule.digest(),
        policy_hash=_hash("fixed-research-only-no-live-authority"),
    )
    scope = Scope(account_alias="research-fixture", mode="simulation", run_id="learning-demo-v1")
    records: list[RecordedDecision] = []
    for i in (*range(0, 100, 5), 110, 112, 118):
        window_sessions = calendar[max(0, i - rule.lookback) : i + 1]
        window = tuple(v for v in observations if v.session in {s.session for s in window_sessions})
        content = json.dumps(
            {
                "source": "synthetic",
                "as_of": calendar[i].closes_at.isoformat(),
                "observations": [v.model_dump(mode="json") for v in window],
                "missing_sessions": [
                    s.session.isoformat()
                    for s in window_sessions
                    if not any(v.session == s.session for v in window)
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        action: Literal["HOLD", "ENTER", "REJECTED"] = (
            "ENTER" if i == 0 else "REJECTED" if i % 3 == 0 else "HOLD"
        )
        fills: tuple[RecordedFill, ...] = ()
        pnl = None
        if i == 0:
            fills = (
                RecordedFill(
                    fill_id="fixture-buy",
                    at=calendar[1].closes_at,
                    side="BUY",
                    quantity=Decimal(1),
                    price=Decimal("100.8"),
                    fee=Decimal("0.1"),
                ),
                RecordedFill(
                    fill_id="fixture-sell",
                    at=calendar[2].closes_at,
                    side="SELL",
                    quantity=Decimal(1),
                    price=Decimal("101.6"),
                    fee=Decimal("0.1"),
                ),
            )
            pnl = Decimal("0.6")  # 101.6 - 100.8 - 0.1 - 0.1; simulated realized ledger P&L
        records.append(
            RecordedDecision(
                decision_id=f"decision-{i:03}",
                scope=scope,
                instrument="TEST_A",
                session=calendar[i].session,
                decided_at=calendar[i].closes_at,
                versions=versions,
                evidence=(
                    Evidence(
                        evidence_id=f"evidence-{i}",
                        observed_at=calendar[i].closes_at,
                        sanitized_content=content,
                        content_hash=_hash(content),
                    ),
                ),
                intent=Intent(
                    intent_id=f"intent-{i}",
                    action=action,
                    quantity=Decimal(1) if i == 0 else Decimal(0),
                    target_weight=rule.weight if i == 0 else Decimal(0),
                    risk_reasons=("fixture-risk-rejection",) if action == "REJECTED" else (),
                ),
                portfolio_snapshot_hash=_hash(f"fixture-portfolio-{i}"),
                available_cash=Decimal("100000"),
                positions=(),
                reconciled_at=calendar[2].closes_at if pnl is not None else None,
                fills=fills,
                operating_cost=Decimal("0.01"),
                reconciled_realized_pnl=pnl,
                reconciliation_hash=_hash("fixture-reconciled-ledger") if pnl is not None else None,
            )
        )
    previous = build_snapshot(
        records=tuple(r for r in records if r.decided_at <= calendar[117].closes_at),
        as_of=calendar[117].closes_at,
        scope=scope,
        observations=observations,
        sessions=calendar,
        horizons=(1, 5, 10),
        holdout_start=calendar[100].session,
    )
    corrected = observations[5]
    correction = Observation(
        instrument="TEST_A",
        session=corrected.session,
        available_at=calendar[119].closes_at,
        close=corrected.close + Decimal("0.2"),
        source_hash=_hash("verified-fixture-correction"),
        revision=1,
        correction_of=corrected.digest(),
    )
    snapshot = build_snapshot(
        records=tuple(records),
        as_of=calendar[119].closes_at,
        previous=previous,
        scope=scope,
        observations=(*observations, correction),
        sessions=calendar,
        horizons=(1, 5, 10),
        holdout_start=calendar[100].session,
    )
    champion = FrozenChampion(
        champion_id="frozen-fixture-champion-v1", rule=rule, versions=versions, universe=("TEST_A",)
    )
    protocol = ResearchProtocol()
    # Four prespecified candidates, with no post-result objective changes.
    search = SearchSpace(
        lookbacks=(5, 10), entries=(Decimal("0.02"), Decimal("0.05")), exits=(Decimal("0"),)
    )
    plan = ExperimentPlan(
        champion_hash=champion.digest(),
        dataset_hash=snapshot.digest(),
        protocol=protocol,
        search=search,
        registered_at=calendar[119].closes_at + timedelta(seconds=1),
        holdout_start=snapshot.holdout_start,
    )
    return plan, champion, snapshot, calendar, observations, previous


def run_demo(root: Path) -> Path:
    plan, champion, snapshot, calendar, observations, previous = demo_inputs()
    from .workflow import save_artifact

    save_artifact(previous, root, "datasets")
    incident = OperationalIncident(
        incident_id="fixture-missing-close-113",
        category="data_quality",
        verified_at=snapshot.as_of,
        evidence_hash=_hash("fixture-missing-close-113"),
        note="Synthetic session 113 has no observation; preserve incomplete labels.",
    )
    report = run_experiment(snapshot, champion, plan, (incident,), artifact_root=root)
    # This is a synthetic event-by-event forward harness, not a claim that
    # real prospective sessions have elapsed. Holdout prices are never consumed.
    candidate = next(t.rule for t in report.trials if t.rule is not None)
    assert candidate is not None
    trial = next(t for t in report.trials if t.rule == candidate)
    shadow = register_shadow(report, trial.trial_id, registered_at=plan.registered_at)
    for index in range(120, 128):
        session = calendar[index]
        observation = next(v for v in observations if v.session == session.session)
        shadow, book, alerts = advance_shadow(
            report,
            shadow,
            observation,
            session,
            now=observation.available_at,
        )
    # An explicit missing observation triggers the predeclared research pause.
    shadow, book, alerts = advance_shadow(
        report,
        shadow,
        None,
        calendar[128],
        now=calendar[128].closes_at,
    )
    # Revalidation protects report links even when constructing an amended immutable snapshot.
    report = ExperimentReport.model_validate(
        {
            **report.model_dump(),
            "shadow": shadow,
            "shadow_book": book,
            "alerts": alerts,
        }
    )
    return save_report(report, root)
