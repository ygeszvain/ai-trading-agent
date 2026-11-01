import json
from datetime import UTC, datetime, time, timedelta

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from trading_agent.config.loading import load_config
from trading_agent.db.schema import broker_orders, research_evaluations
from trading_agent.engine.pipeline import TradingPipeline
from trading_agent.gateway.fixture import build_gateway
from trading_agent.research.jobs import run_job
from trading_agent.research.model_client import ModelResponse, ModelTimeoutError


class FakeAdvisory:
    model = "fixture-model-no-weights"
    calls_made = 0
    fail = False

    def complete(self, system, user, *, max_tokens=512):
        self.calls_made += 1
        if self.fail:
            raise ModelTimeoutError("classified synthetic timeout")
        return ModelResponse(
            text=json.dumps(
                {
                    "view": "insufficient_data",
                    "confidence": 0,
                    "key_factors": [],
                    "risk_flags": ["synthetic"],
                    "summary": "No investment conclusion from a fixture.",
                    "agrees_with_strategy": False,
                }
            ),
            model=self.model,
            latency_ms=1,
            tokens_out=32,
        )


def test_advisory_jobs_persist_valid_failed_and_idempotent_evidence_without_orders(database):
    cfg = load_config("config/simulation.yaml", env={})
    cfg.app.db_url = database
    cfg.research.enabled = True
    pipeline = TradingPipeline(cfg)
    result = pipeline.run()
    gateway = build_gateway(cfg)
    provider = gateway.provider
    day = provider.sessions()[-1]
    start = datetime.combine(day, time.min, tzinfo=UTC)
    end = start + timedelta(hours=23)
    engine = create_engine(database)
    client = FakeAdvisory()
    with Session(engine) as session:
        before = session.execute(select(func.count()).select_from(broker_orders)).scalar_one()
        args = dict(
            config=cfg,
            session=session,
            run_id=result.run_id,
            session_date=day,
            session_start=start,
            decision_ts=end,
            provider=provider,
            client=client,
            prompt_version="v2",
        )
        summary = run_job(**args)
        assert summary.status == "ok" and summary.evaluations > 0
        calls = client.calls_made
        assert run_job(**args).status == "already-ok" and client.calls_made == calls
        rows = session.execute(select(research_evaluations)).all()
        assert all(
            r.validation_status == "valid" and r.action is None and r.weight is None for r in rows
        )
        client.model = "fixture-failing-model"
        client.fail = True
        failed = run_job(**args)
        assert failed.status == "model_unavailable"
        assert session.execute(
            select(research_evaluations).where(
                research_evaluations.c.validation_status == "unavailable"
            )
        ).first()
        assert (
            session.execute(select(func.count()).select_from(broker_orders)).scalar_one() == before
        )
    engine.dispose()
    pipeline._engine.dispose()
