"""Four fixed numerical research probes, persisted against the actual M2 schema.

This score describes only the synthetic tasks. It never grants strategy/weight,
execution or live authority. Missing/failed tasks count against the full budget.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config.models import TradingConfig
from ..data import SyntheticMarketProvider
from ..db.schema import research_evaluations, research_jobs
from .jobs import AdvisoryClient, _digest
from .model_client import ModelClientError

GOLDEN_THRESHOLD = 0.7
PROBE_TASKS = 4
LOOKBACK = 10
WARMUP = 5


def _golden_momentum(prices: list[float]) -> int:
    if len(prices) < max(WARMUP, LOOKBACK + 1) or prices[-LOOKBACK - 1] <= 0:
        return 0
    change = prices[-1] / prices[-LOOKBACK - 1] - 1
    return 1 if change > 0.01 else (-1 if change < -0.01 else 0)


def probe(
    client: AdvisoryClient,
    provider: SyntheticMarketProvider,
    config: TradingConfig,
    session: Session,
    run_id: str,
) -> dict[str, object]:
    job_id = (
        "rj-"
        + _digest(run_id, "probe-v2", client.model or "unknown", provider.data_snapshot_id())[:20]
    )
    existing: list[Any] = list(
        session.execute(
            select(research_evaluations.c.sanitized_response).where(
                research_evaluations.c.job_id == job_id
            )
        )
        .scalars()
        .all()
    )
    if existing:
        records = [json.loads(r) if isinstance(r, str) else r for r in existing]
        correct = sum(bool(r.get("correct")) for r in records)
        return {
            "job_id": job_id,
            "model": client.model,
            "version": "probe-v2",
            "capability": correct / PROBE_TASKS,
            "gated_advisory_only": True,
            "reused": True,
        }
    days = provider.sessions()
    if not days:
        raise ValueError("capability probe requires a persisted synthetic data interval")
    now = datetime.now(UTC)
    config_digest = hashlib.sha256(config.model_dump_json().encode()).hexdigest()
    session.execute(
        research_jobs.insert().values(
            job_id=job_id,
            run_id=run_id,
            session_date=days[-1],
            source_id="capability_probe",
            model_id=client.model,
            prompt_version="probe-v2",
            config_digest=config_digest,
            status="running",
            calls_made=0,
            calls_budget=PROBE_TASKS,
            evaluations_count=0,
            created_at=now,
            started_at=now,
        )
    )
    correct = attempted = 0
    instruments = config.paper.synthetic_fixture_universe
    for offset in range(PROBE_TASKS):
        instrument = sorted(instruments)[offset % len(instruments)]
        day = days[max(0, len(days) - 1 - offset)]
        closes = provider.recent_session_closes(instrument, day, LOOKBACK + 1)
        prices = [float(c.close) for c in closes]
        expected = {1: "up", -1: "down", 0: "hold"}[_golden_momentum(prices)]
        got = ""
        if len(closes) >= LOOKBACK + 1:
            attempted += 1
            prompt = (
                "Synthetic observations, oldest to newest: "
                + ", ".join(f"{p:.4f}" for p in prices)
                + ". Compare newest to the value 10 sessions ago: above +1% means up, "
                "below -1% means down, otherwise hold. Return only up, down or hold."
            )
            try:
                response = client.complete(
                    "Numerical research probe only. No trading authority.", prompt, max_tokens=128
                )
                got = response.text.strip().lower()
            except ModelClientError:
                got = ""
        passed = bool(got and got == expected)
        correct += passed
        session.execute(
            research_evaluations.insert().values(
                eval_id="re-" + _digest(job_id, str(offset))[:20],
                job_id=job_id,
                run_id=run_id,
                session_date=day,
                instrument_id=instrument,
                data_snapshot_id=provider.data_snapshot_id(),
                model_id=client.model,
                prompt_version="probe-v2",
                validation_status="valid" if passed else "invalid",
                action=None,
                weight=None,
                sanitized_response={
                    "task": offset,
                    "expected": expected,
                    "correct": passed,
                    "scope": "synthetic_numerical_probe_only",
                },
                response_chars=0,
                created_at=now,
            )
        )
    score = correct / PROBE_TASKS
    session.execute(
        research_jobs.update()
        .where(research_jobs.c.job_id == job_id)
        .values(
            status="probe_pass" if score >= GOLDEN_THRESHOLD else "probe_fail",
            calls_made=attempted,
            evaluations_count=PROBE_TASKS,
            finished_at=datetime.now(UTC),
        )
    )
    session.commit()
    return {
        "job_id": job_id,
        "model": client.model,
        "version": "probe-v2",
        "capability": score,
        "gated_advisory_only": True,
        "reused": False,
    }
