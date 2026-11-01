"""Real row-lock/fencing checks, dedicated disposable DB, injected fake transport."""

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import create_engine, func, select

from trading_agent.autonomy.engine import AutonomousExecutor
from trading_agent.autonomy.fixtures import KEY, NOW, intent_fixture, owner_resume, seed_fixture
from trading_agent.autonomy.monitor import run_monitor
from trading_agent.autonomy.store import Store
from trading_agent.db.schema import M7_ALL_TABLES, m7_orders
from trading_agent.supervised.contracts import Fill
from trading_agent.supervised.fake import FakeTransport, Observation
from trading_agent.supervised.journal import Denied

URL = "postgresql+psycopg://review@127.0.0.1:55433/m7_review"


@pytest.fixture
def pg(tmp_path):
    if os.environ.get("TRADING_AGENT_M7_REVIEW_DB") != URL:
        pytest.skip("exact dedicated disposable M7 PostgreSQL URL required")
    store = Store(create_engine(URL))
    store.create_fixture_schema()
    with store.transaction() as conn:
        for table in reversed(M7_ALL_TABLES):
            conn.execute(table.delete())
    state, env, champion = seed_fixture(store, tmp_path / "artifacts")
    fake = FakeTransport(account_key=KEY)
    exe = AutonomousExecutor(
        store, fake, artifacts=tmp_path / "artifacts", boot_id="pg-first", clock=lambda: NOW
    )
    exe.startup(KEY, now=NOW)
    exe.observe_market(KEY, state.quote, now=NOW)
    exe.reconcile_account(KEY, cash=state.cash, holdings=(), now=NOW)
    heartbeat = run_monitor(store, KEY, tmp_path / "artifacts", NOW)
    assert heartbeat.healthy and heartbeat.process_id != os.getpid()
    exe.resume(owner_resume(store, NOW), now=NOW)
    yield store, exe, fake, env, champion, tmp_path / "artifacts"
    store.engine.dispose()


def test_concurrent_intents_cannot_share_reserved_capacity(pg):
    store, exe, fake, env, champion, root = pg
    intents = [intent_fixture(store, champion, suffix=str(i), now=NOW) for i in (1, 2)]
    barrier = Barrier(2)

    def reserve(i):
        barrier.wait(timeout=5)
        try:
            exe.reserve(intents[i], env.envelope_id, now=NOW)
            return "reserved"
        except Denied:
            return "denied"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(reserve, (0, 1))) == ["denied", "reserved"]
    with store.transaction() as conn:
        assert conn.execute(select(func.count()).select_from(m7_orders)).scalar_one() == 1
        assert (
            store.state(conn, KEY).reserved_cash
            == intents[0].quantity * intents[0].price_upper + intents[0].max_fee
        )
    assert not fake.calls


def test_same_envelope_allows_distinct_round_trip_orders_and_fences_restart(pg):
    store, exe, fake, env, champion, root = pg
    for suffix in ("buy", "sell"):
        intent = intent_fixture(store, champion, suffix=suffix, now=NOW)
        order = exe.dispatch(intent, env.envelope_id, now=NOW)
        fill = Fill(
            fill_id="pg-" + suffix,
            order_id=intent.intent_id,
            account_key=KEY,
            instrument=intent.instrument,
            side=intent.side,
            quantity=intent.quantity,
            price=intent.limit_price,
            fee=intent.max_fee,
            at=NOW,
        )
        fake.observations[intent.intent_id] = Observation(
            status="filled", broker_order_id=order.broker_order_id, fills=(fill,)
        )
        exe.reconcile_order(KEY, intent.intent_id, now=NOW)
        with store.transaction() as conn:
            current = store.state(conn, KEY)
        exe.reconcile_account(KEY, cash=current.cash, holdings=current.holdings, now=NOW)
    with store.transaction() as conn:
        assert conn.execute(select(func.count()).select_from(m7_orders)).scalar_one() == 2
        assert store.state(conn, KEY).resumed
    candidate = intent_fixture(store, champion, suffix="restart", now=NOW)
    exe.reserve(candidate, env.envelope_id, now=NOW)
    replacement = AutonomousExecutor(
        store, fake, artifacts=root, boot_id="pg-first", clock=lambda: NOW
    )
    replacement.startup(KEY, now=NOW)
    calls = len(fake.calls)
    with pytest.raises(Denied):
        exe.dispatch_reserved(KEY, candidate.intent_id, now=NOW)
    assert len(fake.calls) == calls
    with store.transaction() as conn:
        assert store.state(conn, KEY).high_water_mark >= 1000
        assert not store.state(conn, KEY).resumed
