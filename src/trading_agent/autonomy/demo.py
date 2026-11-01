"""Three synthetic sessions, one initial resume, no per-intent application approval."""

from __future__ import annotations

import json
import os
import uuid
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import URL

from ..db.schema import m7_audit, m7_changes, m7_envelopes, m7_orders
from ..supervised.contracts import Fill
from ..supervised.fake import FakeTransport, Observation
from ..supervised.journal import Denied
from .artifacts import ArtifactVault
from .contracts import ChangeProposal
from .engine import AutonomousExecutor
from .fixtures import KEY, NOW, intent_fixture, owner_resume, seed_fixture
from .monitor import run_monitor
from .package import unsigned_package
from .promotion import prepare_review
from .store import Store


def run_demo(root: Path) -> dict[str, Any]:
    target = root / ("mock-" + uuid.uuid4().hex)
    target.mkdir(parents=True, mode=0o700)
    db = target / "journal.sqlite"
    fd = os.open(db, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    store = Store(create_engine(URL.create("sqlite", database=str(db.resolve()))))
    state, envelope, champion = seed_fixture(store, target / "artifacts")
    now = [NOW]
    fake = FakeTransport(account_key=KEY)
    executor = AutonomousExecutor(
        store, fake, artifacts=target / "artifacts", boot_id="m7-demo-first", clock=lambda: now[0]
    )
    executor.startup(KEY, now=NOW)
    reports = []
    monitor_pids = []
    for day in range(3):
        for step in range(2):
            now[0] = NOW + timedelta(days=day, minutes=step)
            quote = state.quote.changed(as_of=now[0])
            executor.observe_market(KEY, quote, now=now[0])
            with store.transaction() as conn:
                current = store.state(conn, KEY)
            assert executor.reconcile_account(
                KEY, cash=current.cash, holdings=current.holdings, now=now[0]
            )
            monitor = run_monitor(store, KEY, target / "artifacts", now[0])
            monitor_pids.append(monitor.process_id)
            if day == 0 and step == 0:
                executor.resume(owner_resume(store, now[0]), now=now[0])
            intent = intent_fixture(store, champion, suffix=f"{day}-{step}", now=now[0])
            order = executor.dispatch(intent, envelope.envelope_id, now=now[0])
            fill = Fill(
                fill_id="m7-fill-" + intent.intent_id,
                order_id=intent.intent_id,
                account_key=KEY,
                instrument=intent.instrument,
                side=intent.side,
                quantity=intent.quantity,
                price=intent.limit_price,
                fee=Decimal(".01"),
                at=now[0],
            )
            fake.observations[intent.intent_id] = Observation(
                status="filled", broker_order_id=order.broker_order_id, fills=(fill,)
            )
            executor.reconcile_order(KEY, intent.intent_id, now=now[0])
            with store.transaction() as conn:
                current = store.state(conn, KEY)
            assert executor.reconcile_account(
                KEY, cash=current.cash, holdings=current.holdings, now=now[0]
            )
            reports.append(
                {
                    "session": day + 1,
                    "intent_hash": intent.digest(),
                    "side": intent.side,
                    "cash": str(current.cash),
                    "owner_per_intent_approval": False,
                }
            )
    # Fail-closed expiry while independent observation remains operational.
    now[0] = envelope.expires_at
    expired = run_monitor(store, KEY, target / "artifacts", now[0])
    monitor_pids.append(expired.process_id)
    attempt = intent_fixture(store, champion, suffix="expired", now=now[0])
    calls = len(fake.calls)
    try:
        executor.dispatch(attempt, envelope.envelope_id, now=now[0])
    except Denied:
        pass
    else:
        raise AssertionError("expired envelope executed")
    assert len(fake.calls) == calls
    try:
        executor.request_state_change(KEY, "increase_capital", {"capital": "2000"}, now=now[0])
    except Denied:
        capital_expansion_denied = True
    else:
        raise AssertionError("capital expansion unexpectedly accepted")
    assert capital_expansion_denied
    proposal = ChangeProposal(
        envelope_hash=envelope.digest(),
        champion_hash=envelope.champion_hash,
        candidate_hash=envelope.champion_hash,
        change_class="PROMPT",
        diff=(("prompt", "old", "hidden memory override"),),
        dataset_hash=envelope.configuration_hash,
        protocol_hash=envelope.risk_policy_hash,
        all_trial_hashes=(envelope.champion_hash,),
        evidence_hash=envelope.champion_hash,
        matured_labels=0,
        shadow_sessions=0,
        edge_lower_bound=Decimal(0),
        turnover=Decimal(0),
        drawdown=Decimal(0),
        safety_regressions=0,
        failed_trials_preserved=True,
        rollback_target=envelope.rollback_target,
    )
    review = prepare_review(
        store, KEY, proposal, ArtifactVault(target / "artifacts" / "primary"), now=now[0]
    )
    with store.transaction() as conn:
        current = store.state(conn, KEY)
        count = conn.execute(
            select(func.count()).select_from(m7_changes).where(m7_changes.c.kind == "OWNER_RESUME")
        ).scalar_one()
        assert (
            count == 1
            and current.cash == Decimal("999.94")
            and current.high_water_mark >= Decimal(1000)
        )
        assert store.envelope(conn, KEY).digest() == envelope.digest()
        assert conn.execute(select(func.count()).select_from(m7_envelopes)).scalar_one() == 1
        assert conn.execute(select(func.count()).select_from(m7_orders)).scalar_one() == 6
        events = conn.execute(select(func.count()).select_from(m7_audit)).scalar_one()
    result = {
        "domain": "M7_MOCK_ONLY",
        "authority": "LIVE_NOT_AUTHORIZED",
        "actual_live_dispatch_allowed": False,
        "synthetic_sessions": 3,
        "filled_orders": 6,
        "per_intent_application_approvals": 0,
        "initial_owner_resume_commands": count,
        "cash": str(current.cash),
        "high_water_mark": str(current.high_water_mark),
        "envelope_hash": envelope.digest(),
        "envelope_unchanged": True,
        "champion_hash": envelope.champion_hash,
        "automatic_change_class": "NONE",
        "promotion_review": review,
        "monitor_process_ids": monitor_pids,
        "executor_process_id": os.getpid(),
        "independent_monitor_continued_after_expiry": not expired.healthy,
        "audit_events": events,
        "sessions": reports,
        "software_evidence": "CODE_PASS — synthetic harness only",
        "broker_operations_evidence": "EXTERNAL_VALIDATION_PENDING",
        "investment_evidence": "EXTERNAL_VALIDATION_PENDING",
        "journal": str(db.resolve()),
        "artifact_root": str((target / "artifacts").resolve()),
        "paused": current.paused,
    }
    assert all(pid != os.getpid() for pid in monitor_pids)
    (target / "report.json").write_text(json.dumps(result, indent=2) + "\n")
    (target / "owner-review.unsigned.json").write_text(
        json.dumps(unsigned_package(), indent=2) + "\n"
    )
    store.engine.dispose()
    return result
