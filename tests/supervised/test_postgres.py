"""Actual database locking on a separately created disposable database; no broker I/O."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import create_engine, func, select

from trading_agent.db.schema import M6_TABLES, m6_orders
from trading_agent.supervised.contracts import Grant, digest, mock_sign, verify
from trading_agent.supervised.executor import MockControls, MockExecutor
from trading_agent.supervised.fake import FakeTransport
from trading_agent.supervised.fixtures import (
    KEY,
    NOW,
    approval_fixture,
    intent_fixture,
    resume_fixture,
    state_fixture,
)
from trading_agent.supervised.journal import Denied, Journal

URL = "postgresql+psycopg://review@127.0.0.1:55433/m6_review"


@pytest.fixture
def pg():
    if os.environ.get("TRADING_AGENT_M6_REVIEW_DB") != URL:
        pytest.skip("explicit dedicated disposable M6 PostgreSQL URL required")
    engine = create_engine(URL)
    journal = Journal(engine)
    journal.create_fixture_schema()
    with engine.begin() as conn:
        for table in reversed(M6_TABLES):
            conn.execute(table.delete())
    yield journal
    engine.dispose()


def test_concurrent_approved_jobs_cannot_reserve_the_same_capacity(pg):
    state = state_fixture()
    cfg = json.loads(state.config_json)
    cfg["risk"]["max_pending_entry_nav_fraction"] = "0.015"  # tighten fixture only, never widen
    grant = verify(state.authorization, Grant).changed(policy_hash=digest(cfg["risk"]))
    state = state.changed(config_json=json.dumps(cfg), authorization=mock_sign(grant))
    pg.seed(state, NOW)
    fake = FakeTransport(account_key=KEY)
    executor = MockExecutor(pg, fake, boot_id="pg-boot", clock=lambda: NOW)
    executor.startup(KEY, now=NOW)
    with pg.transaction() as conn:
        state = pg.state(conn, KEY)
    controls = MockControls(pg)
    controls.resume(mock_sign(resume_fixture(state)), now=NOW)
    with pg.transaction() as conn:
        state = pg.state(conn, KEY)
    intents = [intent_fixture(state, suffix=str(i)) for i in (1, 2)]
    approvals = [approval_fixture(state, intent) for intent in intents]
    for intent, approval in zip(intents, approvals, strict=True):
        controls.approve(intent, mock_sign(approval), now=NOW)
    barrier = Barrier(2)

    def reserve(index):
        barrier.wait(timeout=5)
        try:
            executor.reserve(intents[index], approvals[index].approval_id, now=NOW)
            return "reserved"
        except Denied:
            return "denied"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, [0, 1]))
    assert sorted(results) == ["denied", "reserved"]
    with pg.transaction() as conn:
        assert (
            pg.state(conn, KEY).reserved_cash
            == intents[0].quantity * intents[0].price_upper + intents[0].max_fee
        )
        assert conn.execute(select(func.count()).select_from(m6_orders)).scalar_one() == 1
    assert fake.calls == []


def test_current_boot_fencing_denies_stale_executor(pg):
    state = state_fixture()
    pg.seed(state, NOW)
    fake = FakeTransport(account_key=KEY)
    first = MockExecutor(pg, fake, boot_id="first", clock=lambda: NOW)
    first.startup(KEY, now=NOW)
    with pg.transaction() as conn:
        state = pg.state(conn, KEY)
    controls = MockControls(pg)
    controls.resume(mock_sign(resume_fixture(state)), now=NOW)
    with pg.transaction() as conn:
        state = pg.state(conn, KEY)
    intent = intent_fixture(state)
    approval = approval_fixture(state, intent)
    controls.approve(intent, mock_sign(approval), now=NOW)
    first.reserve(intent, approval.approval_id, now=NOW)
    second = MockExecutor(pg, fake, boot_id="second", clock=lambda: NOW)
    second.startup(KEY, now=NOW)
    with pytest.raises(Denied):
        first.dispatch_reserved(KEY, intent.intent_id, now=NOW)
    assert fake.calls == []
    with pg.transaction() as conn:
        assert pg.order(conn, intent.intent_id, KEY).status == "unknown"
        assert not pg.state(conn, KEY).resumed
