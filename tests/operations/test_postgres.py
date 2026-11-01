from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from threading import Event

import pytest
from alembic import command
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.orm import Session

from tests.operations.test_email import setup
from tests.stabilization.conftest import database as database
from trading_agent.config.loading import load_config
from trading_agent.db.migrate import _alembic_config, run_migrations, verify_schema
from trading_agent.db.schema import OPS_TABLES, fills, ledger_events, portfolio_snapshots
from trading_agent.engine.pipeline import TradingPipeline
from trading_agent.operations.email import Notice, enqueue
from trading_agent.operations.journal import record
from trading_agent.operations.reconciliation import (
    COLLECTIONS,
    Inventory,
    Position,
    compare,
    persist,
    persisted_ledger_view,
)
from trading_agent.supervised.contracts import digest
from trading_agent.supervised.journal import Journal


def config(url):
    cfg = load_config("config/simulation.yaml", env={})
    cfg.app.db_url = url
    return cfg


def test_operations_migration_roundtrip_preserves_evidence_and_unrelated_rows(database):
    cfg = config(database)
    command.upgrade(_alembic_config(cfg), "f4b020261101")
    engine = create_engine(database)
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE operations_unrelated_witness(value TEXT)"))
            conn.execute(text("INSERT INTO operations_unrelated_witness VALUES ('retained')"))
        assert run_migrations(cfg) == "a61120261101"
        assert all(inspect(engine).has_table(t.name) for t in OPS_TABLES)
        command.downgrade(_alembic_config(cfg), "f4b020261101")
        run_migrations(cfg)
        with Journal(engine).transaction() as conn:
            record(conn, digest("scope"), "fixture_evidence", {"preserve": True})
        with pytest.raises(RuntimeError, match="nonempty operational evidence"):
            command.downgrade(_alembic_config(cfg), "f4b020261101")
        verify_schema(cfg)
        with engine.connect() as conn:
            assert (
                conn.execute(text("SELECT value FROM operations_unrelated_witness")).scalar_one()
                == "retained"
            )
    finally:
        engine.dispose()


def test_existing_ledger_projection_and_reconciliation_never_rewrite_accounting(database):
    cfg = config(database)
    pipeline = TradingPipeline(cfg)
    result = pipeline.run()
    engine = create_engine(database)
    try:

        def counts():
            with engine.connect() as conn:
                return tuple(
                    conn.execute(select(func.count()).select_from(t)).scalar_one()
                    for t in (fills, ledger_events, portfolio_snapshots)
                )

        before = counts()
        with Session(engine) as session:
            view = persisted_ledger_view(
                session,
                run_id=result.run_id,
                account_key=digest("fixture account binding"),
                expected_account_alias="local-sim",
                audit_healthy=True,
            )
            with pytest.raises(ValueError):
                persisted_ledger_view(
                    session,
                    run_id=result.run_id,
                    account_key=digest("wrong"),
                    expected_account_alias="different",
                )
            snap = session.execute(
                select(portfolio_snapshots)
                .where(
                    portfolio_snapshots.c.run_id == result.run_id,
                    portfolio_snapshots.c.portfolio_key == "strategy",
                )
                .order_by(portfolio_snapshots.c.ts.desc())
                .limit(1)
            ).one()
            now = datetime.now(UTC)
            observed = Inventory(
                account_key=view.account_key,
                run_id=view.run_id,
                mode="simulation",
                currency="USD",
                schema_hash=digest("fixture schema"),
                source="FIXTURE",
                started_at=now,
                completed_at=now,
                complete=True,
                cash=snap.cash,
                unleveraged_buying_power=snap.cash,
                positions=tuple(
                    Position(
                        asset_class="equity", instrument=p["instrument_id"], quantity=p["quantity"]
                    )
                    for p in snap.positions
                    if Decimal(p["quantity"])
                ),
                orders=(),
                collections=tuple(sorted(COLLECTIONS)),
            )
            comparison = compare(observed, view, now=now, approved_schema=observed.schema_hash)
            assert comparison.consistent
            persist(session.connection(), observed, view, comparison)
            corrected = observed.changed(
                cash=observed.cash + Decimal(1), corrects_snapshot_hash=observed.digest()
            )
            failure = compare(corrected, view, now=now, approved_schema=observed.schema_hash)
            assert not failure.consistent
            persist(session.connection(), corrected, view, failure)
            session.commit()
        assert counts() == before
    finally:
        engine.dispose()
        pipeline._engine.dispose()


def test_postgres_concurrent_mail_claims_respect_one_message_cap(database):
    cfg = config(database)
    run_migrations(cfg)
    engine = create_engine(database)
    try:
        worker, sink, key, clock = setup(engine)
        with Journal(engine).transaction() as conn:
            other = enqueue(
                conn,
                Notice(
                    domain="FIXTURE",
                    scope=digest("scope"),
                    incident_hash=digest("other"),
                    code="CONTROL_INCIDENT",
                    at=clock[0],
                ),
            )
        entered, release = Event(), Event()

        def slow(notice, message_id):
            sink.calls.append(message_id)
            entered.set()
            assert release.wait(10)
            return "ACCEPTED"

        sink.send = slow
        with ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(worker.send_one, key)
            assert entered.wait(10)
            try:
                assert worker.send_one(other) == "DENIED"
            finally:
                release.set()
            assert first.result() == "ACCEPTED"
        assert sink.calls == [key]
    finally:
        engine.dispose()
