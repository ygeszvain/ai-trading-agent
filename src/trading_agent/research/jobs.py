"""Research jobs: the advisory model layer, run as tracked, budgeted jobs.

One job covers one session of one run. For each selected instrument the job
builds a point-in-time brief, prompts the local model (v1 or v2), evaluates
and validates the output, and persists both the sanitized response and the
deterministic strategy's decision for side-by-side comparison.

Safety guarantees (plan sections 8/9):
- Jobs never execute. They have no broker, no orders, no cash movement.
- Each call hits the loopback-only LocalModelClient under a hard budget.
- Model failures are classified per instrument and per job; a dead model
  degrades the research layer, it never fails the deterministic run.
- Jobs are idempotent: the deterministic job id plus the persisted
  (job, instrument) evaluation key make re-runs resume instead of duplicate.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config.models import TradingConfig
from ..data import SyntheticMarketProvider
from ..db.schema import decisions, portfolio_snapshots, research_evaluations, research_jobs
from ..fixtures.synthetic import FIXTURE_MODEL_VERSION
from .evaluation import EvaluatedOutput, evaluate_output
from .model_client import ModelClientError, ModelResponse
from .prompts import PROMPT_VERSIONS, ResearchBrief, build_prompt

MAX_RESPONSE_CHARS = 4000


@dataclass
class JobSummary:
    job_id: str
    run_id: str
    session_date: date
    status: str
    error_class: str | None = None
    error_message: str | None = None
    evaluations: int = 0
    evaluations_ok: int = 0
    calls_made: int = 0
    tokens_used: int = 0
    eval_ids: list[str] = field(default_factory=list)


def _digest(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def job_id_for(run_id: str, session_date: date, source_id: str, prompt_version: str) -> str:
    return "rj-" + _digest(run_id, session_date.isoformat(), source_id, prompt_version)[:20]


def run_job(
    *,
    config: TradingConfig,
    session: Session,
    run_id: str,
    session_date: date,
    session_start: datetime,
    decision_ts: datetime,
    provider: SyntheticMarketProvider,
    client,
    prompt_version: str = "v1",
) -> JobSummary:
    """Execute one research job for a session, committing per evaluation.

    ``client`` is a LocalModelClient (or a duck-typed stand-in in tests).
    Raises only on infrastructure failure; model-level failures are
    classified inside the summary.
    """
    if prompt_version not in PROMPT_VERSIONS:
        raise ValueError(f"unknown research prompt version: {prompt_version!r}")
    source_id = "local_model"
    job_id = job_id_for(run_id, session_date, source_id, prompt_version)

    instruments = json.loads(config.paper.synthetic_fixture_universe)
    existing = session.execute(
        select(research_jobs.c.status).where(research_jobs.c.job_id == job_id)
    ).first()
    if existing is not None and existing[0] == "ok":
        return JobSummary(
            job_id=job_id, run_id=run_id, session_date=session_date, status="already-ok"
        )
    existing_evals = {
        row[0]
        for row in session.execute(
            select(research_evaluations.c.instrument_id).where(
                research_evaluations.c.job_id == job_id
            )
        ).all()
    }

    selected = _select_instruments(
        session, run_id, session_start, decision_ts, instruments,
        limit=config.research.evaluations_per_job,
    )
    if existing is not None:
        selected = [inst for inst in selected if inst not in existing_evals]

    now = datetime.now(UTC)
    if existing is None and selected:
        session.execute(
            research_jobs.insert().values(
                job_id=job_id,
                run_id=run_id,
                session_date=session_date,
                source_id=source_id,
                model_id=client.model,
                prompt_version=prompt_version,
                config_digest=config_digest,
                status="running",
                calls_budget=config.research.monthly_call_budget,
                evaluations_count=0,
                started_at=now,
            )
        )
        session.commit()

    summary = JobSummary(
        job_id=job_id, run_id=run_id, session_date=session_date, status="running"
    )
    if not selected:
        summary.status = "ok"
        _finish_job(session, job_id, summary, ended_at=now)
        return summary

    for instrument_id in selected:
        brief = _build_brief(
            config, provider, session, run_id, session_date, instrument_id,
            session_start=session_start, decision_ts=decision_ts,
        )
        if brief is None:
            summary.status = "degraded"
            continue
        prompt_digest = _digest(prompt_version, brief.prompt_seed())
        system, user = build_prompt(brief, prompt_version)
        eval_id = "re-" + _digest(job_id, instrument_id, brief.data_snapshot_id)[:20]
        response: ModelResponse | None = None
        try:
            response = client.complete(system, user)
            evaluated = evaluate_output(response.text, prompt_version=prompt_version)
        except ModelClientError as exc:
            evaluated = EvaluatedOutput(
                output_status="model_error",
                response_text=None,
                structured=None,
                error_class=type(exc).__name__,
                error_message=str(exc)[:500],
            )
        deterministic = _deterministic_decision(
            session, run_id, instrument_id, session_start, decision_ts
        )
        session.execute(
            research_evaluations.insert().values(
                eval_id=eval_id,
                job_id=job_id,
                run_id=run_id,
                session_date=session_date,
                instrument_id=instrument_id,
                data_snapshot_id=brief.data_snapshot_id,
                model_id=response.model if response is not None else client.model,
                prompt_version=prompt_version,
                validation_status=evaluated.validation_status,
                action=evaluated.sanitized.get("action") if evaluated.sanitized else None,
                weight=evaluated.sanitized.get("weight") if evaluated.sanitized else None,
                rationale=(
                    str(evaluated.sanitized.get("rationale"))[:1024]
                    if evaluated.sanitized and evaluated.sanitized.get("rationale")
                    else None
                ),
                sanitized_response=evaluated.sanitized or {},
                response_digest=_digest(
                    evaluated.validation_status,
                    json.dumps(evaluated.sanitized or {}, sort_keys=True),
                ),
                response_chars=len(evaluated.response_text or ""),
                strategy_action=deterministic[0],
                strategy_weight=deterministic[1],
                latency_ms=response.latency_ms if response is not None else None,
                tokens_out=response.tokens_out if response is not None else None,
                created_at=now,
            )
        )
        session.commit()
        summary.evaluations += 1
        if evaluated.output_status == "ok":
            summary.evaluations_ok += 1
        else:
            summary.status = "degraded"
        summary.calls_made = client.calls_made
        summary.tokens_used += response.tokens_out if response is not None else 0
        summary.eval_ids.append(eval_id)
        if summary.status == "degraded" and "Model" in (evaluated.error_class or ""):
            # Endpoint-level failure (unreachable/timeout/HTTP/budget): the
            # remaining instruments would fail identically — stop calling.
            summary.error_class = evaluated.error_class
            summary.error_message = evaluated.error_message
            break

    summary.status = _final_status(summary)
    _finish_job(session, job_id, summary, ended_at=datetime.now(UTC))
    return summary


def _final_status(summary: JobSummary) -> str:
    if summary.status == "already-ok":
        return "already-ok"
    if summary.evaluations == 0:
        return "degraded"
    if summary.evaluations_ok == summary.evaluations:
        return "ok"
    if summary.evaluations_ok == 0:
        if summary.error_class and "Budget" in summary.error_class:
            return "budget_exceeded"
        if summary.error_class and "Invalid" in summary.error_class:
            return "invalid_output"
        return "model_unavailable"
    return "degraded"


def _finish_job(session: Session, job_id: str, summary: JobSummary, *, ended_at: datetime) -> None:
    session.execute(
        research_jobs.update()
        .where(research_jobs.c.job_id == job_id)
        .values(
            status=summary.status,
            error_class=summary.error_class,
            error_detail=summary.error_message,
            calls_made=summary.calls_made,
            evaluations_count=summary.evaluations,
            finished_at=ended_at,
        )
    )
    session.commit()


def _select_instruments(
    session: Session,
    run_id: str,
    session_start: datetime,
    decision_ts: datetime,
    instruments: dict[str, tuple[str, str]],
    *,
    limit: int,
) -> list[str]:
    """Instruments the strategy touched this session, non-HOLD first."""
    rows = session.execute(
        select(decisions.c.instrument_id, decisions.c.action, decisions.c.target_weight)
        .where(
            decisions.c.run_id == run_id,
            decisions.c.decision_at >= session_start,
            decisions.c.decision_at <= decision_ts,
        )
        .order_by(decisions.c.instrument_id)
    ).all()
    seen: dict[str, tuple[str, Decimal | None]] = {}
    for instrument_id, action, weight in rows:
        if instrument_id in instruments:
            seen[instrument_id] = (action, weight)
    ordered = sorted(
        seen, key=lambda instrument_id: (seen[instrument_id][0] == "HOLD", instrument_id)
    )
    return ordered[:limit]


def _build_brief(
    config: TradingConfig,
    provider: SyntheticMarketProvider,
    session: Session,
    run_id: str,
    session_date: date,
    instrument_id: str,
    *,
    session_start: datetime,
    decision_ts: datetime,
) -> ResearchBrief | None:
    quote = provider.quote(instrument_id, decision_ts)
    closes = provider.recent_session_closes(
        instrument_id, session_date, config.research.closes_per_brief
    )
    if quote is None and not closes:
        return None
    instruments = json.loads(config.paper.synthetic_fixture_universe)
    symbol, asset_class = instruments.get(instrument_id, (instrument_id, "unknown"))
    snapshot = _last_snapshot(session, run_id, session_start, decision_ts)
    action, weight = _deterministic_decision(session, run_id, instrument_id, session_date)
    age = (
        provider.sessions_since_observation(instrument_id, decision_ts)
        if quote is not None
        else None
    )
    return ResearchBrief(
        instrument_id=instrument_id,
        symbol=symbol,
        asset_class=asset_class,
        is_synthetic=True,
        session_date=session_date,
        data_snapshot_id=provider.data_snapshot_id,
        generator_version=FIXTURE_MODEL_VERSION,
        session_closes=closes,
        last_quote_price=quote.price if quote is not None else None,
        quote_as_of=quote.as_of if quote is not None else None,
        quote_age_sessions=None if age is None or age < 0 else age,
        session_volume=provider.session_volume(instrument_id, decision_ts),
        nav=snapshot.get("equity"),
        cash=snapshot.get("cash"),
        open_positions=len(snapshot.get("positions", {})),
        deterministic_action=action,
        deterministic_weight=weight,
    )


def _last_snapshot(
    session: Session, run_id: str, session_start: datetime, decision_ts: datetime
) -> dict:
    row = session.execute(
        select(
            portfolio_snapshots.c.equity,
            portfolio_snapshots.c.cash,
            portfolio_snapshots.c.positions,
            portfolio_snapshots.c.ts,
        )
        .where(
            portfolio_snapshots.c.run_id == run_id,
            portfolio_snapshots.c.portfolio_key == "strategy",
            portfolio_snapshots.c.ts >= session_start,
            portfolio_snapshots.c.ts <= decision_ts,
        )
        .order_by(portfolio_snapshots.c.ts.desc())
        .limit(1)
    ).first()
    if row is None:
        return {"equity": None, "cash": None, "positions": {}}
    equity, cash, positions, _ = row
    return {
        "equity": equity,
        "cash": cash,
        "positions": positions if isinstance(positions, dict) else json.loads(positions or "{}"),
    }


def _deterministic_decision(
    session: Session,
    run_id: str,
    instrument_id: str,
    session_start: datetime,
    decision_ts: datetime,
) -> tuple[str, Decimal | None]:
    row = session.execute(
        select(decisions.c.action, decisions.c.target_weight)
        .where(
            decisions.c.run_id == run_id,
            decisions.c.instrument_id == instrument_id,
            decisions.c.decision_at >= session_start,
            decisions.c.decision_at <= decision_ts,
        )
        .order_by(decisions.c.decision_at.desc())
        .limit(1)
    ).first()
    if row is None:
        return ("NO_DECISION", None)
    return (row[0], row[1])
