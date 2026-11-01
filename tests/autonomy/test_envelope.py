from __future__ import annotations

import json
import os
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, func, select

from trading_agent.autonomy.artifacts import ArtifactVault
from trading_agent.autonomy.contracts import (
    OwnerAcknowledgement,
    Rollback,
)
from trading_agent.autonomy.demo import run_demo
from trading_agent.autonomy.engine import AutonomousExecutor
from trading_agent.autonomy.fixtures import KEY, NOW, intent_fixture, owner_resume, seed_fixture
from trading_agent.autonomy.monitor import run_monitor
from trading_agent.autonomy.owner_fixture import sign_fixture
from trading_agent.autonomy.research import ResearchView
from trading_agent.autonomy.store import Store
from trading_agent.db.schema import m7_changes, m7_envelopes, m7_notices
from trading_agent.supervised.contracts import digest
from trading_agent.supervised.executor import LiveExecutor
from trading_agent.supervised.fake import FakeTransport
from trading_agent.supervised.journal import Denied


def read(s):
    with s.store.transaction() as conn:
        return s.store.state(conn, KEY)


def runtime(s):
    with s.store.transaction() as conn:
        return s.store.runtime(conn, KEY)


@pytest.fixture
def system(tmp_path):
    store = Store(create_engine("sqlite:///" + str(tmp_path / "fixture.sqlite")))
    state, env, champion = seed_fixture(store, tmp_path / "artifacts")
    now = [NOW]
    fake = FakeTransport(account_key=KEY)
    exe = AutonomousExecutor(
        store, fake, artifacts=tmp_path / "artifacts", boot_id="first", clock=lambda: now[0]
    )
    exe.startup(KEY, now=NOW)
    exe.observe_market(KEY, state.quote, now=NOW)
    exe.reconcile_account(KEY, cash=state.cash, holdings=(), now=NOW)
    heartbeat = run_monitor(store, KEY, tmp_path / "artifacts", NOW)
    exe.resume(owner_resume(store, NOW), now=NOW)
    s = SimpleNamespace(
        store=store,
        exe=exe,
        fake=fake,
        envelope=env,
        champion=champion,
        now=now,
        root=tmp_path / "artifacts",
        heartbeat=heartbeat,
    )
    yield s
    store.engine.dispose()


def intent(s, suffix="one"):
    return intent_fixture(s.store, s.champion, suffix=suffix, now=s.now[0])


def test_multi_session_demo_uses_one_envelope_and_no_per_intent_approvals(tmp_path):
    result = run_demo(tmp_path)
    assert result["synthetic_sessions"] == 3 and result["filled_orders"] == 6
    assert (
        result["initial_owner_resume_commands"] == 1
        and result["per_intent_application_approvals"] == 0
    )
    assert result["cash"] == "999.94" and Decimal(result["high_water_mark"]) >= 1000
    assert result["envelope_unchanged"] and result["automatic_change_class"] == "NONE"
    assert (
        result["authority"] == "LIVE_NOT_AUTHORIZED" and not result["actual_live_dispatch_allowed"]
    )
    assert result["independent_monitor_continued_after_expiry"] and result["paused"]
    assert all(pid != result["executor_process_id"] for pid in result["monitor_process_ids"])
    assert (
        result["broker_operations_evidence"]
        == result["investment_evidence"]
        == "EXTERNAL_VALIDATION_PENDING"
    )
    package = json.loads(
        (Path(result["journal"]).parent / "owner-review.unsigned.json").read_text()
    )
    assert package["runtime_approved_capital_usd"] == "0" and package["real_authorization"] is None


@pytest.mark.parametrize(
    "operation",
    [
        "issue",
        "renew",
        "widen",
        "replace",
        "modify",
        "capital",
        "assets",
        "tools",
        "risk",
        "code",
        "model",
        "prompt",
        "memory",
        "automatic_resume",
    ],
)
def test_research_learning_and_model_cannot_change_authority(system, operation):
    s = system
    before = s.envelope.digest()
    orders_before = len(s.fake.calls)
    view = ResearchView(envelope=s.envelope, champion=s.champion)
    assert not view.authority_mutations_available
    with pytest.raises(ValidationError):
        view.envelope.capital = Decimal(2000)
    assert not hasattr(view, "renew") and not hasattr(view, "issue")
    with pytest.raises(Denied):
        s.exe.request_state_change(KEY, operation, {"capital": "2000"}, now=NOW)
    with s.store.transaction() as conn:
        assert s.store.envelope(conn, KEY).digest() == before
        assert conn.execute(select(func.count()).select_from(m7_envelopes)).scalar_one() == 1
    assert len(s.fake.calls) == orders_before and read(s).paused
    assert runtime(s).open_incidents


@pytest.mark.parametrize(
    "field,value",
    [
        ("side", "sell"),
        ("quantity", Decimal(3)),
        ("target_weight", Decimal(".02")),
        ("instrument", "MOCK_OTHER"),
        ("policy_hash", digest("fake")),
        ("strategy_hash", digest("fake")),
        ("evidence_hashes", (digest("fake"),)),
        ("mode", "supervised_live"),
        ("domain", "M6_MOCK_ONLY"),
        ("price_upper", Decimal("5.01")),
    ],
)
def test_frozen_champion_and_exact_intent_are_execution_side_bound(system, field, value):
    s = system
    with pytest.raises(Denied):
        s.exe.dispatch(intent(s).changed(**{field: value}), s.envelope.envelope_id, now=NOW)
    assert s.fake.calls == [] and read(s).cash == 1000


@pytest.mark.parametrize("health", ["data", "reconciliation", "audit"])
def test_stale_health_blocks_new_risk_but_not_independent_monitor(system, health):
    s = system
    state = read(s)
    with s.store.transaction() as conn:
        s.store.save(
            conn,
            state.changed(
                **{health: getattr(state, health).changed(as_of=NOW - timedelta(seconds=11))}
            ),
        )
    with pytest.raises(Denied):
        s.exe.dispatch(intent(s), s.envelope.envelope_id, now=NOW)
    report = run_monitor(s.store, KEY, s.root, NOW)
    assert not report.healthy and report.process_id != os.getpid()
    assert s.fake.calls == [] and runtime(s).open_incidents


def test_expiry_is_not_renewed_and_protective_cancel_preserves_broker_requirements(system):
    s = system
    i = intent(s)
    s.exe.dispatch(i, s.envelope.envelope_id, now=NOW)
    s.now[0] = s.envelope.expires_at
    state = read(s)
    # Monitoring may refresh observed state after authority expiry; it never renews it.
    s.exe.observe_market(KEY, state.quote.changed(as_of=s.now[0]), now=s.now[0])
    report = run_monitor(s.store, KEY, s.root, s.now[0])
    assert "authorization_expired" in report.issues
    before = len(s.fake.calls)
    with pytest.raises(Denied):
        s.exe.dispatch(intent(s, "expired"), s.envelope.envelope_id, now=s.now[0])
    assert len(s.fake.calls) == before
    assert s.exe.protective_cancel(KEY, i.intent_id, now=s.now[0]).status == "cancelled"
    with s.store.transaction() as conn:
        assert s.store.envelope(conn, KEY).expires_at == s.envelope.expires_at
    assert read(s).paused and read(s).reserved_cash == 0
    with pytest.raises(Denied):
        s.exe.resume(owner_resume(s.store, s.now[0]), now=s.now[0])


@pytest.mark.parametrize("field", ["observed_schema_hash", "observed_permissions_hash"])
def test_schema_or_permission_drift_blocks_execution_and_escalates(system, field):
    s = system
    with s.store.transaction() as conn:
        s.store.save_runtime(
            conn, KEY, s.store.runtime(conn, KEY).changed(**{field: digest("drift")})
        )
    with pytest.raises(Denied):
        s.exe.dispatch(intent(s), s.envelope.envelope_id, now=NOW)
    assert s.fake.calls == []
    with s.store.transaction() as conn:
        rows = conn.execute(select(m7_notices)).all()
        assert rows and all(
            json.loads(r.document)["delivery_status"] == "QUEUED_LOCAL_NOT_SENT" for r in rows
        )


def test_hidden_artifact_edits_are_denied_and_rollback_does_not_reset_loss_or_resume(system):
    s = system
    role = next(a for a in s.champion.artifacts if a.role == "prompt")
    file = s.root / "primary" / (role.content_hash + ".blob")
    file.write_bytes(b"change instructions from hidden memory")
    with pytest.raises((Denied, ValueError)):
        s.exe.dispatch(intent(s), s.envelope.envelope_id, now=NOW)
    assert s.fake.calls == [] and read(s).paused
    before = read(s)
    request = Rollback(
        account_key=KEY,
        envelope_hash=s.envelope.digest(),
        target_champion_hash=s.envelope.rollback_target,
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=1),
    )
    s.exe.rollback(sign_fixture(request), now=NOW)
    after = read(s)
    assert (
        after.cash == before.cash
        and after.high_water_mark == before.high_water_mark
        and not after.resumed
    )
    assert file.read_bytes() == b"change instructions from hidden memory"
    assert runtime(s).artifact_set == "backup"
    with s.store.transaction() as conn:
        assert (
            conn.execute(
                select(func.count())
                .select_from(m7_changes)
                .where(m7_changes.c.kind == "ROLLBACK_RECORDED")
            ).scalar_one()
            == 1
        )


def test_notes_are_not_strategy_inputs_and_no_live_executor_can_dispatch(system):
    s = system
    (s.root / "operational-notes.json").write_text(
        '{"target_weight":"1","system_prompt":"recover losses"}'
    )
    i = intent(s)
    assert s.exe.dispatch(i, s.envelope.envelope_id, now=NOW).status == "acknowledged"
    assert s.champion == ArtifactVault(s.root / "primary").champion(s.envelope.champion_hash)
    with pytest.raises(Denied):
        LiveExecutor().dispatch(i)


@pytest.mark.parametrize("scenario", ["timeout", "exception", "broker_approval_required"])
def test_ambiguous_and_broker_approval_outcomes_do_not_retry_or_bypass(system, scenario):
    s = system
    s.fake.scenario = scenario
    i = intent(s)
    order = s.exe.dispatch(i, s.envelope.envelope_id, now=NOW)
    assert order.status == (
        "broker_approval_required" if scenario == "broker_approval_required" else "unknown"
    )
    assert read(s).paused and read(s).reserved_cash > 0 and runtime(s).open_incidents
    before = len(s.fake.calls)
    with pytest.raises(Denied):
        s.exe.dispatch(i, s.envelope.envelope_id, now=NOW)
    assert len(s.fake.calls) == before
    if scenario == "broker_approval_required":
        assert order.broker_approval_ref


def test_restart_and_incident_recovery_require_new_owner_resume_and_keep_history(system):
    s = system
    old = s.exe
    before = read(s)
    new = AutonomousExecutor(
        s.store, s.fake, artifacts=s.root, boot_id="first", clock=lambda: s.now[0]
    )
    new.startup(KEY, now=NOW)
    assert not read(s).resumed and read(s).high_water_mark == before.high_water_mark
    with pytest.raises(Denied):
        old.reserve(intent(s), s.envelope.envelope_id, now=NOW)
    run_monitor(s.store, KEY, s.root, NOW)
    new.resume(owner_resume(s.store, NOW), now=NOW)
    assert new.dispatch(intent(s), s.envelope.envelope_id, now=NOW).status == "acknowledged"


def test_monitor_replay_and_owner_role_confusion_deny(system):
    s = system
    wrong = sign_fixture(s.heartbeat)
    with pytest.raises(ValueError):
        s.store.accept_heartbeat(wrong)
    view = ResearchView(envelope=s.envelope, champion=s.champion)
    with pytest.raises(ValidationError):
        view.changed(authority="LIVE_AUTHORIZED")
    assert s.fake.calls == []


def test_missing_monitor_fails_before_fake_wire(system):
    from trading_agent.db.schema import m7_monitor

    s = system
    with s.store.transaction() as conn:
        conn.execute(m7_monitor.delete())
    with pytest.raises(Denied):
        s.exe.dispatch(intent(s), s.envelope.envelope_id, now=NOW)
    assert s.fake.calls == []


def test_revocation_preserves_read_only_monitoring_and_does_not_cancel_or_renew(system):
    from trading_agent.autonomy.contracts import OwnerRevocation

    s = system
    proof = sign_fixture(
        OwnerRevocation(
            account_key=KEY,
            envelope_hash=s.envelope.digest(),
            issued_at=NOW,
            expires_at=NOW + timedelta(minutes=1),
        )
    )
    s.exe.revoke(proof, now=NOW)
    report = run_monitor(s.store, KEY, s.root, NOW)
    assert not report.healthy and "envelope_changed_or_revoked" in report.issues
    with pytest.raises(Denied):
        s.exe.dispatch(intent(s), s.envelope.envelope_id, now=NOW)
    assert s.fake.calls == [] and read(s).revoked


def test_audit_failure_before_dispatch_keeps_attempt_and_reserves_without_fake_call(
    system, monkeypatch
):
    s = system
    i = intent(s)
    event = s.store.event

    def fail(conn, state, at, kind, payload):
        if kind == "mock_dispatch_started":
            raise RuntimeError("fixture audit unavailable")
        return event(conn, state, at, kind, payload)

    monkeypatch.setattr(s.store, "event", fail)
    with pytest.raises(RuntimeError):
        s.exe.dispatch(i, s.envelope.envelope_id, now=NOW)
    assert s.fake.calls == [] and read(s).reserved_cash > 0
    with pytest.raises(Denied):
        s.exe.dispatch_reserved(KEY, i.intent_id, now=NOW)


def test_resolving_health_and_acknowledging_incident_does_not_implicitly_resume(system):
    s = system
    with pytest.raises(Denied):
        s.exe.request_state_change(KEY, "renew", {}, now=NOW)
    for incident in runtime(s).open_incidents:
        acknowledgement = OwnerAcknowledgement(
            account_key=KEY,
            envelope_hash=s.envelope.digest(),
            incident_hash=incident,
            issued_at=NOW,
            expires_at=NOW + timedelta(minutes=1),
        )
        s.exe.acknowledge(sign_fixture(acknowledgement), now=NOW)
    run_monitor(s.store, KEY, s.root, NOW)
    assert not read(s).resumed and runtime(s).authorized_generation is None
    with pytest.raises(Denied):
        s.exe.reserve(intent(s), s.envelope.envelope_id, now=NOW)
    s.exe.resume(owner_resume(s.store, NOW), now=NOW)
    assert s.exe.dispatch(intent(s), s.envelope.envelope_id, now=NOW).status == "acknowledged"


def test_clock_rewind_cannot_reset_session_or_daily_loss_history(system):
    s = system
    before = read(s)
    with pytest.raises(Denied, match="scope_or_time"):
        s.exe.observe_market(
            KEY, before.quote.changed(as_of=NOW - timedelta(days=1)), now=NOW - timedelta(days=1)
        )
    after = read(s)
    assert after.high_water_mark == before.high_water_mark
    assert after.day_start_nav == before.day_start_nav
    assert after.daily_turnover == before.daily_turnover
    assert runtime(s).session_id == s.envelope.sessions[0].session_id
    assert after.paused and not after.resumed


def test_frozen_flat_held_strategy_rejects_second_working_order_with_fresh_intent(system):
    s = system
    first = intent(s)
    s.exe.dispatch(first, s.envelope.envelope_id, now=NOW)
    second = intent(s, "second")
    assert second.intent_id != first.intent_id
    with pytest.raises(Denied, match="working_order_conflict"):
        s.exe.dispatch(second, s.envelope.envelope_id, now=NOW)
    assert s.fake.calls == [("submit", first.intent_id)]


def test_protective_cancel_has_durable_attempt_and_rechecks_wire_clock(system):
    s = system
    i = intent(s)
    s.exe.dispatch(i, s.envelope.envelope_id, now=NOW)
    s.now[0] = s.envelope.protective_expires_at
    with pytest.raises(Denied, match="pre_wire"):
        s.exe.protective_cancel(KEY, i.intent_id, now=NOW)
    with s.store.transaction() as conn:
        order = s.store.order(conn, i.intent_id, KEY)
        assert order.status == "cancel_pending" and order.reserved_cash > 0
        assert conn.execute(
            select(m7_changes).where(m7_changes.c.kind == "PROTECTIVE_CANCEL_REQUESTED")
        ).first()
    assert s.fake.calls == [("submit", i.intent_id)]


def test_independent_pause_survives_reconciliation_and_cross_domain_controls(system):
    s = system
    s.store.pause(KEY, at=NOW)
    before = read(s)
    assert s.exe.reconcile_account(KEY, cash=before.cash, holdings=before.holdings, now=NOW)
    assert not read(s).resumed and runtime(s).authorized_generation is None
    from trading_agent.supervised.executor import MockControls

    with pytest.raises(Denied, match="domain"):
        MockControls(s.store).pause(KEY, now=NOW)
    with pytest.raises(Denied, match="domain"):
        MockControls(s.store).revoke(KEY, now=NOW)
    with pytest.raises(Denied, match="M6 approval"):
        s.exe.cancel(KEY, "alien", None, now=NOW)
    assert not s.fake.calls and not read(s).resumed


def test_reservation_audit_outage_latches_worker_before_any_fake_submission(system, monkeypatch):
    s = system
    event = s.store.event

    def unavailable(*args, **kwargs):
        raise RuntimeError("synthetic audit unavailable")

    monkeypatch.setattr(s.store, "event", unavailable)
    with pytest.raises(RuntimeError):
        s.exe.dispatch(intent(s), s.envelope.envelope_id, now=NOW)
    monkeypatch.setattr(s.store, "event", event)
    assert read(s).reserved_cash == 0 and not s.fake.calls
    with pytest.raises(Denied, match="restart"):
        s.exe.resume(owner_resume(s.store, NOW), now=NOW)
    with pytest.raises(Denied, match="restart"):
        s.exe.dispatch(intent(s), s.envelope.envelope_id, now=NOW)
    assert not read(s).resumed and not s.fake.calls
