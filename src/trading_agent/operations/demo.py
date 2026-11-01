"""Reproducible offline operational acceptance with one shared synthetic journal."""

from __future__ import annotations

import os
import uuid
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.engine import URL

from ..autonomy.contracts import Session
from ..autonomy.engine import AutonomousExecutor
from ..autonomy.fixtures import KEY, NOW, intent_fixture, owner_resume, seed_fixture
from ..autonomy.monitor import run_monitor
from ..autonomy.store import Store
from ..db.schema import ops_mail
from ..security.files import write_private_json
from ..supervised.contracts import Fill, State, digest
from ..supervised.executor import LiveExecutor
from ..supervised.fake import FakeTransport, Observation
from ..supervised.journal import Denied
from .closeout import CloseoutController, CloseoutPolicy, install_policy, ledger_view
from .email import DeliveryConsent, Dispatcher, EmailProfile, Notice, Status, enqueue
from .monitor import MonitorProfile, monitor_once
from .readiness import Evidence, readiness
from .reconciliation import COLLECTIONS, Comparison, Inventory, Position, compare, persist


def run_demo(root: Path) -> dict[str, Any]:
    target = root / ("mock-" + uuid.uuid4().hex)
    target.mkdir(parents=True, mode=0o700)
    db = target / "journal.sqlite"
    fd = os.open(db, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    store = Store(create_engine(URL.create("sqlite", database=str(db.resolve()))))
    store.create_fixture_schema()
    sessions = tuple(
        Session(
            session_id="ops-session-" + str(i),
            opens_at=NOW + timedelta(days=i),
            closes_at=NOW + timedelta(days=i, hours=6),
        )
        for i in range(3)
    )
    policy = CloseoutPolicy(
        account_key=KEY,
        instrument="MOCK_ETF",
        calendar_hash=digest([s.model_dump(mode="json") for s in sessions]),
        sessions=sessions,
        entry_cutoff_minutes=30,
        cancel_entries_minutes=20,
        exit_start_minutes=15,
        flat_deadline_minutes=5,
    )
    with store.transaction() as conn:
        policy_hash = install_policy(conn, policy)
    state, envelope, champion = seed_fixture(
        store, target / "artifacts", closeout_policy_hash=policy_hash, session_schedule=sessions
    )
    from .fixtures import acknowledge_fixture_channel

    acknowledge_fixture_channel(store.engine, KEY, NOW)
    clock = [NOW]
    fake = FakeTransport(account_key=KEY)
    exe = AutonomousExecutor(
        store, fake, artifacts=target / "artifacts", boot_id="ops-demo", clock=lambda: clock[0]
    )
    exe.startup(KEY, now=NOW)
    venue_cash = state.cash
    venue_quantity = Decimal(0)

    def read() -> State:
        with store.transaction() as conn:
            return store.state(conn, KEY)

    def refresh() -> Comparison:
        current = read()
        exe.observe_market(KEY, current.quote.changed(as_of=clock[0]), now=clock[0])
        current = read()
        assert exe.reconcile_account(KEY, cash=venue_cash, holdings=current.holdings, now=clock[0])
        run_monitor(store, KEY, target / "artifacts", clock[0])
        with store.transaction() as conn:
            view = ledger_view(exe, conn, store.state(conn, KEY))
            observed = Inventory(
                account_key=KEY,
                run_id=state.run_id,
                mode="simulation",
                currency="USD",
                schema_hash=envelope.tool_schema_hash,
                started_at=clock[0],
                completed_at=clock[0],
                source="FIXTURE",
                complete=True,
                cash=venue_cash,
                unleveraged_buying_power=venue_cash,
                settled_cash=venue_cash,
                positions=(
                    Position(asset_class="equity", instrument="MOCK_ETF", quantity=venue_quantity),
                )
                if venue_quantity
                else (),
                orders=view.orders,
                collections=tuple(sorted(COLLECTIONS)),
            )
            comparison = compare(
                observed, view, now=clock[0], approved_schema=envelope.tool_schema_hash
            )
            persist(conn, observed, view, comparison)
            assert comparison.consistent
            return comparison

    def fill(order_id: str) -> None:
        nonlocal venue_cash, venue_quantity
        with store.transaction() as conn:
            order = store.order(conn, order_id, KEY)
        i = order.intent
        fee = Decimal(".01")
        fake.observations[order_id] = Observation(
            status="filled",
            broker_order_id=order.broker_order_id,
            fills=(
                Fill(
                    fill_id="ops-fill-" + order_id,
                    order_id=order_id,
                    account_key=KEY,
                    instrument=i.instrument,
                    side=i.side,
                    quantity=i.quantity,
                    price=i.limit_price,
                    fee=fee,
                    at=clock[0],
                ),
            ),
        )
        exe.reconcile_order(KEY, order_id, now=clock[0])
        venue_cash += (
            (-i.quantity * i.limit_price - fee)
            if i.side == "buy"
            else (i.quantity * i.limit_price - fee)
        )
        venue_quantity += i.quantity if i.side == "buy" else -i.quantity

    try:
        refresh()
        exe.resume(owner_resume(store, NOW), now=NOW)
        entry = intent_fixture(store, champion, suffix="operations-entry", now=NOW)
        exe.dispatch(entry, envelope.envelope_id, now=NOW)
        fill(entry.intent_id)
        clock[0] = sessions[0].closes_at - timedelta(minutes=15)
        comparison = refresh()
        controller = CloseoutController(exe)
        assert controller.tick(KEY, now=clock[0], comparison=comparison) == "EXIT_WORKING"
        with store.transaction() as conn:
            exit_order = next(o for o in store.account_orders(conn, KEY) if o.intent.side == "sell")
        fill(exit_order.intent.intent_id)
        comparison = refresh()
        assert controller.tick(KEY, now=clock[0], comparison=comparison) == "FLAT"
        calls = list(fake.calls)
        assert (
            controller.tick(KEY, now=clock[0], comparison=comparison) == "FLAT"
            and fake.calls == calls
        )
        assert venue_quantity == 0 and read().cash == state.cash - Decimal(".02")
        # An independent health-check path can still record an incident without the executor.
        monitor = monitor_once(
            store.engine, MonitorProfile(enabled=True, scope=KEY), None, now=clock[0]
        )
        assert monitor["status"] == "ALERT"
        profile = EmailProfile(
            enabled=True, sender="owner@example.invalid", recipient="owner@example.invalid"
        )
        consent = DeliveryConsent(
            profile_hash=profile.digest(),
            scope=KEY,
            purpose="FIXTURE",
            approved=True,
            starts_at=NOW,
            expires_at=envelope.expires_at,
            max_messages=2,
        )

        class FixtureMail:
            calls: list[str] = []

            def send(self, notice: Notice, message_id: str) -> Status:
                self.calls.append(message_id)
                return "UNKNOWN" if notice.code == "OWNER_EMAIL_TEST" else "ACCEPTED"

        mail = FixtureMail()
        dispatcher = Dispatcher(store.engine, mail, profile, consent, clock=lambda: clock[0])
        first = dispatcher.send_one(str(monitor["message_id"]))
        with store.transaction() as conn:
            unknown = enqueue(
                conn,
                Notice(
                    domain="FIXTURE",
                    scope=KEY,
                    incident_hash=digest("ambiguous-email"),
                    code="OWNER_EMAIL_TEST",
                    at=clock[0],
                ),
            )
        second = dispatcher.send_one(unknown)
        before = len(mail.calls)
        assert dispatcher.send_one(unknown) == "UNKNOWN" and len(mail.calls) == before
        with store.transaction() as conn:
            statuses: list[str] = list(conn.execute(select(ops_mail.c.status)).scalars())
        try:
            LiveExecutor().dispatch(entry)
        except Denied:
            pass
        else:
            raise AssertionError("live dispatcher unexpectedly available")
        report = {
            "domain": "FIXTURE",
            "authority": "LIVE_NOT_AUTHORIZED",
            "journal": str(db),
            "run_id": state.run_id,
            "closed_out": "FLAT_CONFIRMED",
            "cash": str(read().cash),
            "positions": 0,
            "broker_calls": len(fake.calls),
            "duplicate_closeout_submissions": 0,
            "email_fixture_results": [first, second],
            "mail_statuses": statuses,
            "real_emails_sent": 0,
            "real_broker_calls": 0,
            "monitor_detected_missing_runtime": True,
            "readiness": readiness(
                Evidence(
                    email_code=True,
                    closeout_code=True,
                    reconciliation_code=True,
                    execution_controls_code=True,
                )
            ),
        }
        write_private_json(target / "report.json", report, replace=False)
        return report
    finally:
        store.engine.dispose()
