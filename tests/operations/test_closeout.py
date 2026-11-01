from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select

from trading_agent.autonomy.contracts import Session
from trading_agent.autonomy.engine import AutonomousExecutor
from trading_agent.autonomy.fixtures import KEY, NOW, intent_fixture, owner_resume, seed_fixture
from trading_agent.autonomy.monitor import run_monitor
from trading_agent.autonomy.store import Store
from trading_agent.db.schema import ops_closeouts, ops_records
from trading_agent.operations.closeout import (
    CloseoutController,
    CloseoutPolicy,
    install_policy,
    ledger_view,
)
from trading_agent.operations.reconciliation import (
    COLLECTIONS,
    Inventory,
    Position,
    compare,
    persist,
)
from trading_agent.supervised.contracts import Fill, digest
from trading_agent.supervised.fake import FakeTransport, Observation
from trading_agent.supervised.journal import Denied


def make(tmp_path, early=False):
    now = datetime(2026, 11, 27, 14, 30, tzinfo=UTC) if early else NOW
    sessions = tuple(
        Session(
            session_id="session-" + str(i),
            opens_at=now + timedelta(days=i),
            closes_at=now + timedelta(days=i, hours=3, minutes=30)
            if early
            else now + timedelta(days=i, hours=6),
        )
        for i in range(1 if early else 3)
    )
    store = Store(create_engine("sqlite:///" + str(tmp_path / "closeout.sqlite")))
    store.create_fixture_schema()
    policy = CloseoutPolicy(
        account_key=KEY,
        instrument="MOCK_ETF",
        sessions=sessions,
        calendar_hash=digest([s.model_dump(mode="json") for s in sessions]),
        entry_cutoff_minutes=30,
        cancel_entries_minutes=20,
        exit_start_minutes=15,
        flat_deadline_minutes=5,
    )
    with store.transaction() as conn:
        policy_id = install_policy(conn, policy)
    state, envelope, champion = seed_fixture(
        store,
        tmp_path / "artifacts",
        now=now,
        closeout_policy_hash=policy_id,
        session_schedule=sessions,
    )
    from trading_agent.operations.fixtures import acknowledge_fixture_channel

    acknowledge_fixture_channel(store.engine, KEY, now)
    clock = [now]
    fake = FakeTransport(account_key=KEY)
    exe = AutonomousExecutor(
        store, fake, artifacts=tmp_path / "artifacts", boot_id="ops", clock=lambda: clock[0]
    )
    exe.startup(KEY, now=now)
    s = SimpleNamespace(
        store=store,
        exe=exe,
        fake=fake,
        envelope=envelope,
        champion=champion,
        clock=clock,
        root=tmp_path / "artifacts",
        policy=policy,
        venue_cash=state.cash,
        venue_quantity=Decimal(0),
    )
    refresh(s, now)
    exe.resume(owner_resume(store, now), now=now)
    return s


def read(s):
    with s.store.transaction() as conn:
        return s.store.state(conn, KEY)


def refresh(s, now):
    s.clock[0] = now
    state = read(s)
    s.exe.observe_market(KEY, state.quote.changed(as_of=now), now=now)
    state = read(s)
    # Existing reconciliation gate receives an independent scripted venue balance.
    s.exe.reconcile_account(KEY, cash=s.venue_cash, holdings=state.holdings, now=now)
    run_monitor(s.store, KEY, s.root, now)
    with s.store.transaction() as conn:
        state = s.store.state(conn, KEY)
        view = ledger_view(s.exe, conn, state)
        observed = Inventory(
            account_key=KEY,
            run_id=state.run_id,
            mode="simulation",
            currency="USD",
            schema_hash=s.envelope.tool_schema_hash,
            started_at=now,
            completed_at=now,
            source="FIXTURE",
            complete=True,
            cash=s.venue_cash,
            unleveraged_buying_power=s.venue_cash,
            settled_cash=s.venue_cash,
            positions=(
                Position(asset_class="equity", instrument="MOCK_ETF", quantity=s.venue_quantity),
            )
            if s.venue_quantity
            else (),
            orders=view.orders,
            collections=tuple(sorted(COLLECTIONS)),
        )
        result = compare(observed, view, now=now, approved_schema=s.envelope.tool_schema_hash)
        persist(conn, observed, view, result)
    return result


def fill(s, order_id):
    with s.store.transaction() as conn:
        order = s.store.order(conn, order_id, KEY)
    i = order.intent
    fee = Decimal(".01")
    s.fake.observations[order_id] = Observation(
        status="filled",
        broker_order_id=order.broker_order_id,
        fills=(
            Fill(
                fill_id="fill-" + order_id,
                order_id=order_id,
                account_key=KEY,
                instrument=i.instrument,
                side=i.side,
                quantity=i.quantity,
                price=i.limit_price,
                fee=fee,
                at=s.clock[0],
            ),
        ),
    )
    s.exe.reconcile_order(KEY, order_id, now=s.clock[0])
    if i.side == "buy":
        s.venue_cash -= i.quantity * i.limit_price + fee
        s.venue_quantity += i.quantity
    else:
        s.venue_cash += i.quantity * i.limit_price - fee
        s.venue_quantity -= i.quantity


@pytest.mark.parametrize("early", [False, True])
def test_calendar_bound_closeout_uses_existing_executor_and_requires_fresh_flat_proof(
    tmp_path, early
):
    s = make(tmp_path, early)
    try:
        i = intent_fixture(s.store, s.champion, suffix="entry", now=s.clock[0])
        s.exe.dispatch(i, s.envelope.envelope_id, now=s.clock[0])
        fill(s, i.intent_id)
        close = s.envelope.sessions[0].closes_at
        at = close - timedelta(minutes=15)
        comparison = refresh(s, at)
        ctl = CloseoutController(s.exe)
        assert ctl.tick(KEY, now=at, comparison=comparison) == "EXIT_WORKING"
        with s.store.transaction() as conn:
            jobs = conn.execute(select(ops_closeouts)).all()
            import json

            exit_id = json.loads(jobs[0].document)["intent_id"]
        fill(s, exit_id)
        assert (
            ctl.tick(KEY, now=at, comparison=comparison) == "BLOCKED"
        )  # stale comparison cannot claim flat
        # Separate clean run exercises confirmed-flat completion below.
        assert s.venue_quantity == 0 and read(s).cash == s.venue_cash
        assert all(kind in {"submit", "observe"} for kind, _ in s.fake.calls)
    finally:
        s.store.engine.dispose()


def test_confirmed_flat_is_idempotent_without_duplicate_orders(tmp_path):
    s = make(tmp_path)
    try:
        i = intent_fixture(s.store, s.champion, suffix="entry", now=s.clock[0])
        s.exe.dispatch(i, s.envelope.envelope_id, now=s.clock[0])
        fill(s, i.intent_id)
        at = s.envelope.sessions[0].closes_at - timedelta(minutes=15)
        comparison = refresh(s, at)
        ctl = CloseoutController(s.exe)
        assert ctl.tick(KEY, now=at, comparison=comparison) == "EXIT_WORKING"
        with s.store.transaction() as conn:
            rows = s.store.account_orders(conn, KEY)
            exit_id = next(o.intent.intent_id for o in rows if o.intent.side == "sell")
        fill(s, exit_id)
        comparison = refresh(s, at)
        assert ctl.tick(KEY, now=at, comparison=comparison) == "FLAT"
        before = list(s.fake.calls)
        assert ctl.tick(KEY, now=at, comparison=comparison) == "FLAT" and s.fake.calls == before
    finally:
        s.store.engine.dispose()


def test_entry_cutoff_is_execution_side_even_without_controller_tick(tmp_path):
    s = make(tmp_path)
    try:
        at = s.envelope.sessions[0].closes_at - timedelta(minutes=30)
        refresh(s, at)
        i = intent_fixture(s.store, s.champion, suffix="late", now=at)
        with pytest.raises(Denied, match="preclose_entry_cutoff"):
            s.exe.dispatch(i, s.envelope.envelope_id, now=at)
        assert s.fake.calls == []
    finally:
        s.store.engine.dispose()


def test_unknown_submission_and_missed_deadline_cannot_resubmit_or_sell_blindly(tmp_path):
    s = make(tmp_path)
    try:
        i = intent_fixture(s.store, s.champion, suffix="entry", now=s.clock[0])
        s.exe.dispatch(i, s.envelope.envelope_id, now=s.clock[0])
        fill(s, i.intent_id)
        at = s.envelope.sessions[0].closes_at - timedelta(minutes=15)
        comparison = refresh(s, at)
        s.fake.scenario = "timeout"
        ctl = CloseoutController(s.exe)
        ctl.tick(KEY, now=at, comparison=comparison)
        before = list(s.fake.calls)
        ctl.tick(KEY, now=at, comparison=comparison)
        assert s.fake.calls == before and read(s).paused and s.venue_quantity > 0
    finally:
        s.store.engine.dispose()


def test_tampered_policy_cannot_change_entry_cutoff(tmp_path):
    s = make(tmp_path)
    try:
        with s.store.transaction() as conn:
            conn.execute(
                ops_records.update()
                .where(ops_records.c.record_id == s.envelope.closeout_policy_hash)
                .values(document=s.policy.changed(entry_cutoff_minutes=60).model_dump_json())
            )
        at = s.envelope.sessions[0].closes_at - timedelta(minutes=15)
        with pytest.raises(Denied):
            s.exe.dispatch(
                intent_fixture(s.store, s.champion, suffix="tamper", now=at),
                s.envelope.envelope_id,
                now=at,
            )
        assert s.fake.calls == []
    finally:
        s.store.engine.dispose()


def test_working_entries_cancel_before_flat_confirmation(tmp_path):
    s = make(tmp_path)
    try:
        entry = intent_fixture(s.store, s.champion, suffix="working", now=s.clock[0])
        s.exe.dispatch(entry, s.envelope.envelope_id, now=s.clock[0])
        at = s.envelope.sessions[0].closes_at - timedelta(minutes=20)
        comparison = refresh(s, at)
        ctl = CloseoutController(s.exe)
        assert ctl.tick(KEY, now=at, comparison=comparison) == "AWAIT_RECONCILIATION"
        assert s.fake.calls.count(("cancel", entry.intent_id)) == 1
        assert read(s).reserved_cash == 0
        comparison = refresh(s, at + timedelta(minutes=5))
        assert ctl.tick(KEY, now=s.clock[0], comparison=comparison) == "FLAT"
    finally:
        s.store.engine.dispose()


def test_missing_mail_verification_blocks_new_entry_before_wire(tmp_path):
    from trading_agent.db.schema import ops_mail

    s = make(tmp_path)
    try:
        with s.store.transaction() as conn:
            conn.execute(ops_mail.update().values(status="UNKNOWN"))
        entry = intent_fixture(s.store, s.champion, suffix="email-unverified", now=s.clock[0])
        with pytest.raises(Denied, match="email_delivery_unverified"):
            s.exe.dispatch(entry, s.envelope.envelope_id, now=s.clock[0])
        assert s.fake.calls == []
    finally:
        s.store.engine.dispose()


def test_unpersisted_comparison_cannot_claim_closeout_health(tmp_path):
    s = make(tmp_path)
    try:
        at = s.envelope.sessions[0].closes_at - timedelta(minutes=15)
        comparison = refresh(s, at)
        with s.store.transaction() as conn:
            conn.execute(ops_records.delete().where(ops_records.c.kind == "reconciliation"))
        assert CloseoutController(s.exe).tick(KEY, now=at, comparison=comparison) == "BLOCKED"
        assert s.fake.calls == []
    finally:
        s.store.engine.dispose()


def test_exit_deadline_keeps_unfilled_order_and_exposure_visible(tmp_path):
    s = make(tmp_path)
    try:
        entry = intent_fixture(s.store, s.champion, suffix="entry", now=s.clock[0])
        s.exe.dispatch(entry, s.envelope.envelope_id, now=s.clock[0])
        fill(s, entry.intent_id)
        at = s.envelope.sessions[0].closes_at - timedelta(minutes=15)
        ctl = CloseoutController(s.exe)
        assert ctl.tick(KEY, now=at, comparison=refresh(s, at)) == "EXIT_WORKING"
        at = s.envelope.sessions[0].closes_at - timedelta(minutes=5)
        comparison = refresh(s, at)
        before = list(s.fake.calls)
        assert ctl.tick(KEY, now=at, comparison=comparison) == "BLOCKED"
        assert s.fake.calls == before and s.venue_quantity == 2 and read(s).paused
    finally:
        s.store.engine.dispose()


def test_partial_exit_never_creates_a_second_sell(tmp_path):
    s = make(tmp_path)
    try:
        entry = intent_fixture(s.store, s.champion, suffix="entry", now=s.clock[0])
        s.exe.dispatch(entry, s.envelope.envelope_id, now=s.clock[0])
        fill(s, entry.intent_id)
        at = s.envelope.sessions[0].closes_at - timedelta(minutes=15)
        ctl = CloseoutController(s.exe)
        assert ctl.tick(KEY, now=at, comparison=refresh(s, at)) == "EXIT_WORKING"
        with s.store.transaction() as conn:
            order = next(o for o in s.store.account_orders(conn, KEY) if o.intent.side == "sell")
        i = order.intent
        for part in (1, 2):
            fill_part = Fill(
                fill_id="exit-part-" + str(part),
                order_id=i.intent_id,
                account_key=KEY,
                instrument=i.instrument,
                side="sell",
                quantity=Decimal(1),
                price=i.limit_price,
                fee=Decimal(".005"),
                at=at,
            )
            s.fake.observations[i.intent_id] = Observation(
                status="acknowledged" if part == 1 else "filled",
                broker_order_id=order.broker_order_id,
                fills=(fill_part,),
            )
            s.exe.reconcile_order(KEY, i.intent_id, now=at)
            s.venue_cash += i.limit_price - Decimal(".005")
            s.venue_quantity -= 1
            comparison = refresh(s, at)
            phase = ctl.tick(KEY, now=at, comparison=comparison)
            assert phase == ("AWAIT_RECONCILIATION" if part == 1 else "FLAT")
        assert sum(kind == "submit" for kind, _ in s.fake.calls) == 2
        assert read(s).cash == s.venue_cash and s.venue_quantity == 0
    finally:
        s.store.engine.dispose()


def test_same_symbol_manual_holding_is_not_automatically_sold(tmp_path):
    s = make(tmp_path)
    try:
        entry = intent_fixture(s.store, s.champion, suffix="entry", now=s.clock[0])
        s.exe.dispatch(entry, s.envelope.envelope_id, now=s.clock[0])
        fill(s, entry.intent_id)
        # A separately observed manual share must not be attributed to the pilot.
        with s.store.transaction() as conn:
            state = s.store.state(conn, KEY)
            holding = state.holdings[0].changed(quantity=Decimal(3))
            s.store.save(conn, state.changed(holdings=(holding,)))
        s.venue_quantity = Decimal(3)
        at = s.envelope.sessions[0].closes_at - timedelta(minutes=15)
        comparison = refresh(s, at)
        before = list(s.fake.calls)
        assert CloseoutController(s.exe).tick(KEY, now=at, comparison=comparison) == "BLOCKED"
        assert s.fake.calls == before and s.venue_quantity == 3
    finally:
        s.store.engine.dispose()


def test_report_timestamp_cannot_hide_a_stale_broker_snapshot(tmp_path):
    s = make(tmp_path)
    try:
        at = s.envelope.sessions[0].closes_at - timedelta(minutes=15)
        current = refresh(s, at)
        with s.store.transaction() as conn:
            raw = conn.execute(
                select(ops_records.c.document).where(
                    ops_records.c.record_id == current.inventory_record_id
                )
            ).scalar_one()
            old = Inventory.model_validate_json(raw).changed(
                started_at=at - timedelta(seconds=30), completed_at=at - timedelta(seconds=30)
            )
            view = ledger_view(s.exe, conn, s.store.state(conn, KEY))
            broad = compare(
                old, view, now=at, approved_schema=s.envelope.tool_schema_hash, max_age_seconds=100
            )
            assert broad.consistent
            persist(conn, old, view, broad)
        assert CloseoutController(s.exe).tick(KEY, now=at, comparison=broad) == "BLOCKED"
        assert s.fake.calls == []
    finally:
        s.store.engine.dispose()
