"""Only an explicitly selected disposable PostgreSQL database is used here."""

import os
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine

from trading_agent.config.loading import load_config
from trading_agent.db.schema import metadata, runs

REVIEW_URL = "postgresql+psycopg://review@127.0.0.1:55433/review"
NOW = datetime(2026, 1, 5, 15, tzinfo=UTC)


@pytest.fixture
def review_engine():
    if os.environ.get("TRADING_AGENT_REVIEW_DB") != REVIEW_URL:
        pytest.skip("set TRADING_AGENT_REVIEW_DB to the dedicated disposable review database")
    engine = create_engine(REVIEW_URL)
    metadata.create_all(engine)
    with engine.begin() as conn:
        for table in reversed(metadata.sorted_tables):
            conn.execute(table.delete())
    yield engine
    engine.dispose()


@pytest.fixture
def review_config():
    config = load_config("config/simulation.yaml", env={})
    config.app.db_url = REVIEW_URL
    return config


def seed_run(session, run_id="review-run", alias="local-sim", mode="simulation"):
    session.execute(
        runs.insert().values(
            run_id=run_id,
            account_alias=alias,
            mode=mode,
            config_digest="fixture",
            strategy_version="momentum-v1",
            risk_policy_version="paper-policy-v1",
            data_source="synthetic",
            data_snapshot_id="fixture",
            initial_cash=Decimal(100000),
            status="completed",
            created_at=NOW,
            completed_at=NOW,
        )
    )
