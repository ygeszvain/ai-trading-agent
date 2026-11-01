from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from threading import Event

import pytest
from alembic import command
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from trading_agent.config.loading import load_config
from trading_agent.db.migrate import _alembic_config, run_migrations, verify_schema
from trading_agent.db.schema import fills, ledger_events, metadata
from trading_agent.engine.pipeline import PipelineError, TradingPipeline
from trading_agent.ledger.ledger import Ledger


def config(url):
    cfg = load_config("config/simulation.yaml", env={})
    cfg.app.db_url = url
    return cfg


def test_fresh_migration_matches_contract_and_preserves_legacy_provenance(database):
    cfg = config(database)
    command.upgrade(_alembic_config(cfg), "e71a4c09d522")
    engine = create_engine(database)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO data_snapshots "
                "(snapshot_id,source_id,content_digest,retrieved_at) VALUES "
                "('legacy','fixture','retained',now())"
            )
        )
        conn.execute(text("CREATE TABLE unrelated_witness(value TEXT)"))
        conn.execute(text("INSERT INTO unrelated_witness VALUES ('preserve')"))
    assert run_migrations(cfg) == "f4b020261101"
    verify_schema(cfg)
    with engine.connect() as conn:
        assert (
            conn.execute(text("SELECT content_digest FROM legacy_m3_data_snapshots")).scalar_one()
            == "retained"
        )
        assert conn.execute(text("SELECT value FROM unrelated_witness")).scalar_one() == "preserve"
        assert conn.execute(text("SELECT count(*) FROM data_snapshots")).scalar_one() == 0
    with pytest.raises(RuntimeError, match="nonempty evidence"):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO broker_gateway_events(event_id,provider,ts,event_type) "
                    "VALUES ('witness','fixture',now(),'retain')"
                )
            )
        command.downgrade(_alembic_config(cfg), "e71a4c09d522")
    verify_schema(cfg)  # refused downgrade is transactional
    engine.dispose()



@pytest.mark.parametrize(
    ("table", "insert"),
    [
        (
            "executor_leases",
            "INSERT INTO executor_leases VALUES ('simulation:fixture','owner',7)",
        ),
        (
            "market_bars",
            "INSERT INTO market_bars "
            "(run_id,instrument_id,ts,open,high,low,close,volume,source_id,session_id) "
            "VALUES ('fixture','TEST_A',now(),1,1,1,1,0,'synthetic','retained-session')",
        ),
        (
            "fills",
            "INSERT INTO fills "
            "(fill_id,run_id,order_id,instrument_id,side,ts,quantity,price,fee,raw_fill_id,"
            "portfolio_key) VALUES "
            "('fill','fixture','order','TEST_A','buy',now(),1,1,0,'raw','passive-baseline')",
        ),
    ],
)
def test_downgrade_preserves_nonledger_evidence_and_worker_generation(database, table, insert):
    cfg = config(database)
    run_migrations(cfg)
    # An empty revision is reversible; evidence written afterward is not disposable.
    command.downgrade(_alembic_config(cfg), "e71a4c09d522")
    run_migrations(cfg)
    engine = create_engine(database)
    try:
        with engine.begin() as conn:
            conn.execute(text(insert))
        with pytest.raises(RuntimeError, match="nonempty evidence"):
            command.downgrade(_alembic_config(cfg), "e71a4c09d522")
        verify_schema(cfg)
        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM " + table)).scalar_one() == 1
    finally:
        engine.dispose()


def test_pipeline_restart_is_idempotent_and_all_books_replay(database):
    cfg = config(database)
    pipeline = TradingPipeline(cfg)
    first = pipeline.run()
    engine = create_engine(database)

    def counts():
        with engine.connect() as conn:
            return {
                name: conn.execute(select(func.count()).select_from(table)).scalar_one()
                for name, table in metadata.tables.items()
            }

    before = counts()
    again = TradingPipeline(cfg).run()
    assert again.status == "already-complete" and counts() == before
    assert first.positions == again.positions and first.equity == again.equity
    assert first.fills == again.fills == 48 and first.reconciliation == "consistent"
    small = config(database)
    small.paper.initial_cash_usd = Decimal(500)
    small_pipeline = TradingPipeline(small)
    small_result = small_pipeline.run()
    assert small_result.run_id != first.run_id and small_result.orders == 0
    assert small_result.equity["strategy"] == Decimal("507.77790481")
    small_pipeline._engine.dispose()
    with Session(engine) as session:
        for book in ("strategy", "cash-baseline", "passive-baseline"):
            ledger = Ledger(
                session,
                run_id=first.run_id,
                portfolio_key=book,
                account_alias="local-sim",
                initial_cash=cfg.paper.initial_cash_usd,
                initial_ts=datetime.now(UTC),
            )
            assert ledger.cash >= 0
        assert (
            session.execute(
                select(func.count())
                .select_from(fills)
                .where(fills.c.portfolio_key == "passive-baseline", fills.c.run_id == first.run_id)
            ).scalar_one()
            == 3
        )
        assert not session.execute(
            select(ledger_events.c.event_id).where(ledger_events.c.application_seq.is_(None))
        ).first()
    engine.dispose()
    pipeline._engine.dispose()


def test_concurrent_worker_is_denied_and_crash_recovery_preserves_commits(database, monkeypatch):
    cfg = config(database)
    first = TradingPipeline(cfg)
    second = TradingPipeline(cfg)
    entered, release = Event(), Event()
    original = first._process_session
    count = [0]

    def crash(**kwargs):
        count[0] += 1
        if count[0] == 3:
            entered.set()
            assert release.wait(10)
            raise RuntimeError("injected crash before third session commit")
        return original(**kwargs)

    monkeypatch.setattr(first, "_process_session", crash)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(first.run)
        assert entered.wait(10)
        try:
            with pytest.raises(PipelineError, match="another simulation executor"):
                second.run()
        finally:
            release.set()
        with pytest.raises(RuntimeError, match="injected crash"):
            future.result()
    resumed = second.run()
    assert resumed.resumed and resumed.sessions == 128 and resumed.fills == 48
    assert resumed.equity["strategy"] == Decimal("101576.38120949")
    first._engine.dispose()
    second._engine.dispose()
