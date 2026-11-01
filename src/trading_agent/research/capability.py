"""Capability probing for advisory research (plan section 8, v1 advisory scope).

The probe runs a fixed, deterministic task set — a documented momentum signal
over synthetic fixture closes, graded against golden values — and persists a
capability record on the research_jobs table. Advisory research is GATED on
this record: capability < 0.7 means the model stays advisory-only (no weight
proposals), per the plan's capability gate.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..data import SyntheticMarketProvider
from ..db.schema import research_jobs
from .jobs import _digest
from .model_client import LocalModelClient

GOLDEN_THRESHOLD = 0.7
PROBE_TASKS = 4
LOOKBACK = 10
WARMUP = 5


def _golden_momentum(prices: list[float]) -> int:
    """Documented probe rule: sign of the 10-session return.

    +1 if the close rose at least 1% over the lookback, -1 if it fell at
    least 1%, else 0 (hold). Fewer than WARMUP closes means no signal.
    """
    if len(prices) < WARMUP or len(prices) < LOOKBACK + 1:
        return 0
    ref = prices[-LOOKBACK - 1]
    if ref <= 0:
        return 0
    change = prices[-1] / ref - 1
    if change > 0.01:
        return 1
    if change < -0.01:
        return -1
    return 0


def probe(
    client: LocalModelClient,
    provider: SyntheticMarketProvider,
    config,
    session: Session,
    run_id: str,
) -> dict:
    """Run the probe task set, persist the job record, return the summary."""
    job_id = "rj-" + _digest(run_id, "probe", "v1")[:20]
    instruments = json.loads(config.paper.synthetic_fixture_universe)
    sessions = provider.sessions()

    # Idempotent: a completed probe for this run is reused.
    existing = session.execute(
        select(research_jobs.c.capability).where(research_jobs.c.job_id == job_id)
    ).first()
    if existing is not None and existing[0] is not None:
        return {
            "job_id": job_id,
            "model": client.model,
            "version": "v1",
            "capability": float(existing[0]),
            "gated_advisory_only": float(existing[0]) < GOLDEN_THRESHOLD,
            "reused": True,
        }

    attempted = 0
    correct = 0
    for offset in range(PROBE_TASKS):
        instrument_id = sorted(instruments)[offset % len(instruments)]
        as_of_session = sessions[max(0, len(sessions) - 1 - offset)]
        closes = provider.recent_session_closes(instrument_id, as_of_session, LOOKBACK + 1)
        if len(closes) < LOOKBACK + 1:
            continue
        prices = [float(c.close) for c in closes]
        golden = _golden_momentum(prices)
        expect = {1: "long", -1: "short", 0: "hold"}[golden]
        prompt = (
            f"Closing prices, oldest to newest, {as_of_session.isoformat()} session: "
            f"{', '.join(_preprices(prices))}\n"
            f"Instrument: {instrument_id}\n"
            "Rule: compare the newest price to the price 10 sessions earlier. "
            "Answer exactly one word: long if it rose more than 1%, short if it "
            "fell more than 1%, otherwise hold.\nAnswer:"
        )
        system = "You answer quantitative questions with exactly one word."
        try:
            response = client.complete(system, prompt)
        except Exception:
            continue
        attempted += 1
        got = response.text.strip().lower().split()[0] if response.text.strip() else ""
        if got == expect:
            correct += 1

    capability = correct / attempted if attempted else 0.0
    now = datetime.now(UTC)
    session.execute(
        research_jobs.insert().values(
            job_id=job_id,
            run_id=run_id,
            source_id="local_model",
            model_id=client.model,
            prompt_version="v1",
            status="ok",
            calls_made=client.calls_made,
            tokens_used=client.tokens_used,
            capability=capability,
            started_at=now,
            ended_at=now,
        )
    )
    session.commit()
    return {
        "job_id": job_id,
        "model": client.model,
        "version": "v1",
        "capability": capability,
        "gated_advisory_only": capability < GOLDEN_THRESHOLD,
        "reused": False,
    }


def _preprices(prices: list[float]) -> list[str]:
    return [f"{price:.4f}" for price in prices]
