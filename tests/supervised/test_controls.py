from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select

from trading_agent.db.schema import m6_audit
from trading_agent.supervised.contracts import Fill, Grant, digest, mock_sign, verify
from trading_agent.supervised.executor import LiveExecutor, MockControls, MockExecutor
from trading_agent.supervised.fake import FakeTransport, Observation
from trading_agent.supervised.fixtures import (
    KEY,
    NOW,
    approval_fixture,
    intent_fixture,
    resume_fixture,
    state_fixture,
)
from trading_agent.supervised.journal import Denied, Journal
from trading_agent.supervised.readiness import evaluate


def read(journal):
    with journal.transaction() as conn:
        return journal.state(conn, KEY)


def setup(journal, scenario="acknowledged"):
    state = state_fixture()
    journal.seed(state, NOW)
    transport = FakeTransport(account_key=KEY, scenario=scenario)
    executor = MockExecutor(journal, transport, boot_id="fixture-boot", clock=lambda: NOW)
    executor.startup(KEY, now=NOW)
    controls = MockControls(journal)
    controls.resume(mock_sign(resume_fixture(read(journal))), now=NOW)
    return controls, executor, transport


@pytest.fixture
def system(tmp_path):
    journal = Journal(create_engine("sqlite:///" + str(tmp_path / "m6-fixture.sqlite")))
    journal.create_fixture_schema()
    controls, executor, transport = setup(journal)
    yield journal, controls, executor, transport
    journal.engine.dispose()


def approved(system, suffix="one"):
    journal, controls, executor, transport = system
    state = read(journal)
    intent = intent_fixture(state, suffix=suffix)
    approval = approval_fixture(state, intent)
    controls.approve(intent, mock_sign(approval), now=NOW)
    return intent, approval


def test_real_dispatch_is_impossible_even_with_perfect_mock_evidence(system):
    j, c, e, t = system
    i, a = approved(system)
    report = evaluate(read(j), now=NOW, intent=i, approval=a)
    assert report.mock_controls_satisfied and report.authority == "LIVE_NOT_AUTHORIZED"
    assert not report.actual_dispatch_allowed
    assert [x.name for x in report.checks if not x.satisfied] == ["build_live_dispatch_disabled"]
    for method in (LiveExecutor().dispatch, LiveExecutor().cancel, LiveExecutor().resume):
        with pytest.raises(Denied):
            method(i)
    assert not evaluate(None, now=NOW).mock_controls_satisfied
    assert t.calls == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("account_alias", "other"),
        ("account_key", digest("other")),
        ("instrument", "MOCK_OTHER"),
        ("side", "sell"),
        ("quantity", Decimal(3)),
        ("target_weight", Decimal(".02")),
        ("limit_price", Decimal("4.99")),
        ("price_lower", Decimal("4.98")),
        ("price_upper", Decimal("5.01")),
        ("max_fee", Decimal(".02")),
        ("strategy_version", "other"),
        ("policy_version", "other"),
        ("strategy_hash", digest("other")),
        ("policy_hash", digest("other")),
        ("evidence_hashes", (digest("other"),)),
        ("risk_snapshot_hash", digest("other")),
        ("expires_at", NOW + timedelta(seconds=59)),
        ("run_id", "other"),
    ],
)
def test_any_material_intent_change_invalidates_approval(system, field, value):
    j, c, e, t = system
    i, a = approved(system)
    changed = i.changed(**{field: value})
    with pytest.raises(Denied):
        e.dispatch(changed, a.approval_id, now=NOW)
    assert t.calls == [] and read(j).reserved_cash == 0


@pytest.mark.parametrize(
    "change",
    [
        {"observed_account_key": digest("wrong")},
        {"authorization": None},
        {"strategy_frozen": False},
        {"strategy_hash": digest("changed")},
        {"account_as_of": NOW - timedelta(seconds=11)},
        {"eligibility_as_of": NOW - timedelta(seconds=11)},
        {"paused": True},
        {"resumed": False},
        {"revoked": True},
    ],
)
def test_missing_stale_mismatched_and_revoked_state_deny(system, change):
    j, c, e, t = system
    i, a = approved(system)
    with j.transaction() as conn:
        j.save(conn, j.state(conn, KEY).changed(**change))
    with pytest.raises(Denied):
        e.dispatch(i, a.approval_id, now=NOW)
    assert t.calls == []


@pytest.mark.parametrize("health", ["data", "reconciliation", "audit"])
@pytest.mark.parametrize("problem", ["failed", "stale", "future"])
def test_health_prerequisites_are_independently_enforced(system, health, problem):
    j, c, e, t = system
    i, a = approved(system)
    s = read(j)
    h = getattr(s, health)
    changed = (
        h.changed(status="failed")
        if problem == "failed"
        else h.changed(as_of=NOW + timedelta(seconds=1 if problem == "future" else -11))
    )
    with j.transaction() as conn:
        j.save(conn, s.changed(**{health: changed}))
    with pytest.raises(Denied):
        e.dispatch(i, a.approval_id, now=NOW)
    assert t.calls == []


def test_single_flag_and_changed_policy_strategy_settings_cannot_bypass(system):
    import json

    j, c, e, t = system
    i, a = approved(system)
    state = read(j)
    for section, key, value in [
        ("live", "enabled", False),
        ("live", "approved_capital_usd", "0"),
        ("app", "mode", "simulation"),
        ("universe", "live_instrument_allowlist", []),
        ("risk", "max_order_nav_fraction", "0.03"),
        ("strategy", "lookback_days", 21),
    ]:
        raw = json.loads(state.config_json)
        raw[section][key] = value
        changed = state.changed(config_json=json.dumps(raw))
        assert not evaluate(changed, now=NOW, intent=i, approval=a).mock_controls_satisfied
    assert t.calls == []


def test_approval_expiry_signature_and_replay(system):
    j, c, e, t = system
    i, a = approved(system)
    with pytest.raises(Denied):
        e.dispatch(i, a.approval_id, now=i.expires_at)
    with pytest.raises(ValueError):
        c.approve(i, mock_sign(a).changed(signature="0" * 64), now=NOW)
    assert e.dispatch(i, a.approval_id, now=NOW).status == "acknowledged"
    with pytest.raises(Denied):
        e.dispatch(i, a.approval_id, now=NOW)
    with pytest.raises(Denied):
        e.dispatch_reserved(KEY, i.intent_id, now=NOW)
    assert t.calls == [("submit", i.intent_id)]


def test_recheck_between_reservation_and_wire_retains_capacity_on_revocation(system):
    j, c, e, t = system
    i, a = approved(system)
    order = e.reserve(i, a.approval_id, now=NOW)
    assert read(j).reserved_cash == Decimal("10.01")
    c.revoke(KEY, now=NOW)
    with pytest.raises(Denied):
        e.dispatch_reserved(KEY, i.intent_id, now=NOW)
    assert t.calls == [] and read(j).reserved_cash == order.reserved_cash
    with j.transaction() as conn:
        assert j.approval(conn, KEY, a.approval_id)[1]


@pytest.mark.parametrize(
    "scenario", ["timeout", "exception", "rejected", "broker_approval_required"]
)
def test_submission_outcomes_never_retry_or_override_broker_approval(tmp_path, scenario):
    j = Journal(create_engine("sqlite:///" + str(tmp_path / "outcome.sqlite")))
    j.create_fixture_schema()
    c, e, t = setup(j, scenario)
    i, a = approved((j, c, e, t))
    order = e.dispatch(i, a.approval_id, now=NOW)
    expected = "unknown" if scenario in {"timeout", "exception"} else scenario
    assert order.status == expected
    assert read(j).reserved_cash == (0 if scenario == "rejected" else Decimal("10.01"))
    if scenario == "broker_approval_required":
        assert order.broker_approval_ref
    with pytest.raises(Denied):
        e.dispatch(i, a.approval_id, now=NOW)
    assert t.calls == [("submit", i.intent_id)]


def test_partial_fills_duplicate_delivery_and_cancel_fill_race(system):
    j, c, e, t = system
    i, a = approved(system)
    order = e.dispatch(i, a.approval_id, now=NOW)
    f1 = Fill(
        fill_id="mock-f1",
        order_id=i.intent_id,
        account_key=KEY,
        instrument=i.instrument,
        side="buy",
        quantity=Decimal(1),
        price=Decimal(5),
        fee=Decimal(".005"),
        at=NOW,
    )
    t.observations[i.intent_id] = Observation(
        status="acknowledged", broker_order_id=order.broker_order_id, fills=(f1,)
    )
    order = e.reconcile_order(KEY, i.intent_id, now=NOW)
    assert order.status == "partially_filled" and order.reserved_cash == Decimal("5.005")
    assert read(j).cash == Decimal("994.995")
    e.reconcile_order(KEY, i.intent_id, now=NOW)
    assert read(j).cash == Decimal("994.995")
    f2 = f1.changed(fill_id="mock-f2")
    t.observations[i.intent_id] = Observation(
        status="filled", broker_order_id=order.broker_order_id, fills=(f1, f2)
    )
    cancel = a.changed(
        approval_id="mock-cancel",
        intent_hash=digest({"cancel": i.digest(), "account_key": KEY, "epoch": 0}),
    )
    order = e.cancel(KEY, i.intent_id, mock_sign(cancel), now=NOW)
    assert order.status == "filled" and order.filled_quantity == 2 and order.reserved_cash == 0
    state = read(j)
    assert state.cash == Decimal("989.99") and state.holdings[0].average_cost == Decimal("5.005")
    assert state.reserved_cash == 0 and state.paused
    assert e.reconcile_account(KEY, cash=state.cash, holdings=state.holdings, now=NOW)
    assert not read(j).resumed
    c.resume(mock_sign(resume_fixture(read(j))), now=NOW)
    assert read(j).resumed


def test_cancellation_confirmation_is_distinct_and_revocation_does_not_cancel(system):
    j, c, e, t = system
    i, a = approved(system)
    e.dispatch(i, a.approval_id, now=NOW)
    c.revoke(KEY, now=NOW)
    assert t.calls == [("submit", i.intent_id)] and read(j).reserved_cash > 0
    cancel = a.changed(
        approval_id="mock-cancel",
        epoch=1,
        intent_hash=digest({"cancel": i.digest(), "account_key": KEY, "epoch": 1}),
    )
    assert e.cancel(KEY, i.intent_id, mock_sign(cancel), now=NOW).status == "cancelled"
    assert read(j).reserved_cash == 0
    with pytest.raises(Denied):
        e.cancel(KEY, i.intent_id, mock_sign(cancel), now=NOW)


def test_restart_requires_reconciliation_and_new_resume_consent(system):
    j, c, e, t = system
    i, a = approved(system)
    resume = mock_sign(resume_fixture(read(j)))
    e.reserve(i, a.approval_id, now=NOW)
    other = MockExecutor(j, t, boot_id="new-boot", clock=lambda: NOW)
    other.startup(KEY, now=NOW)
    assert not read(j).resumed and read(j).reserved_cash > 0
    with pytest.raises(Denied):
        c.resume(resume, now=NOW)
    with pytest.raises(Denied):
        other.dispatch_reserved(KEY, i.intent_id, now=NOW)
    assert not other.reconcile_account(KEY, cash=read(j).cash, holdings=(), now=NOW)
    assert t.calls == []


def test_audit_failure_before_wire_rolls_back_and_poisoned_instance_cannot_retry(
    system, monkeypatch
):
    j, c, e, t = system
    i, a = approved(system)
    e.reserve(i, a.approval_id, now=NOW)

    def fail(*args, **kwargs):
        raise RuntimeError("fictional audit outage")

    monkeypatch.setattr(j, "event", fail)
    with pytest.raises(RuntimeError):
        e.dispatch_reserved(KEY, i.intent_id, now=NOW)
    assert t.calls == []
    with pytest.raises(Denied):
        e.dispatch_reserved(KEY, i.intent_id, now=NOW)
    with j.transaction() as conn:
        assert not j.order(conn, i.intent_id, KEY).dispatch_started


def test_reconciliation_difference_preserves_local_history_and_blocks_resume(system):
    j, c, e, t = system
    before = read(j)
    assert not e.reconcile_account(KEY, cash=Decimal(999), holdings=(), now=NOW)
    after = read(j)
    assert after.cash == before.cash and after.reconciliation.status == "failed"
    with pytest.raises(Denied):
        c.resume(mock_sign(resume_fixture(after)), now=NOW)
    with j.transaction() as conn:
        kinds = (
            conn.execute(select(m6_audit.c.event_type).order_by(m6_audit.c.sequence))
            .scalars()
            .all()
        )
        assert "mock_reconciliation_difference" in kinds


def test_non_fake_transport_and_synthetic_tokens_cannot_create_live_authority(system):
    j, c, e, t = system

    class Other(FakeTransport):
        pass

    with pytest.raises(Denied):
        MockExecutor(j, Other(account_key=KEY), boot_id="bad")
    grant = verify(read(j).authorization, Grant)
    assert grant.domain == "M6_MOCK_ONLY"
    with pytest.raises(ValueError):
        grant.changed(domain="LIVE")


def test_trusted_clock_is_checked_after_durable_reservation(system):
    j, c, e, t = system
    i, a = approved(system)
    e.clock = lambda: NOW + timedelta(seconds=61)
    with pytest.raises(Denied):
        e.dispatch(i, a.approval_id, now=NOW)
    assert t.calls == [] and read(j).reserved_cash > 0


def test_response_persistence_failure_never_replays_a_possible_submission(system, monkeypatch):
    j, c, e, t = system
    i, a = approved(system)
    event = j.event

    def fail_response(conn, state, at, kind, payload):
        if kind == "mock_broker_observed":
            raise RuntimeError("fictional post-response audit outage")
        return event(conn, state, at, kind, payload)

    monkeypatch.setattr(j, "event", fail_response)
    with pytest.raises(RuntimeError):
        e.dispatch(i, a.approval_id, now=NOW)
    assert t.calls == [("submit", i.intent_id)]
    with pytest.raises(Denied):
        e.dispatch_reserved(KEY, i.intent_id, now=NOW)
    monkeypatch.setattr(j, "event", event)
    restarted = MockExecutor(j, t, boot_id="recover", clock=lambda: NOW)
    restarted.startup(KEY, now=NOW)
    with j.transaction() as conn:
        assert j.order(conn, i.intent_id, KEY).status == "unknown"
        assert j.state(conn, KEY).reserved_cash > 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("eligible", False),
        ("tradable", False),
        ("regular_session", False),
        ("asset_class", "unsupported"),
    ],
)
def test_unverified_instrument_capabilities_deny(system, field, value):
    j, c, e, t = system
    i, a = approved(system)
    state = read(j)
    with j.transaction() as conn:
        j.save(conn, state.changed(quote=state.quote.changed(**{field: value})))
    with pytest.raises(Denied):
        e.dispatch(i, a.approval_id, now=NOW)
    assert t.calls == []


def test_invalid_fill_evidence_is_preserved_and_cannot_change_accounting(system):
    import json

    j, c, e, t = system
    i, a = approved(system)
    order = e.dispatch(i, a.approval_id, now=NOW)
    before = read(j)
    bad = Fill(
        fill_id="bad-price",
        order_id=i.intent_id,
        account_key=KEY,
        instrument=i.instrument,
        side="buy",
        quantity=Decimal(1),
        price=Decimal(6),
        fee=Decimal(".005"),
        at=NOW,
    )
    t.observations[i.intent_id] = Observation(
        status="acknowledged", broker_order_id=order.broker_order_id, fills=(bad,)
    )
    with pytest.raises(Denied):
        e.reconcile_order(KEY, i.intent_id, now=NOW)
    state = read(j)
    assert (
        state.cash == before.cash and state.reserved_cash == before.reserved_cash and state.paused
    )
    with j.transaction() as conn:
        row = conn.execute(
            select(m6_audit.c.payload).where(m6_audit.c.event_type == "mock_observation_rejected")
        ).scalar_one()
        assert json.loads(row)["observation"]["fills"][0]["fill_id"] == "bad-price"
        assert j.order(conn, i.intent_id, KEY).status == "manual_review"


def test_mock_money_is_independent_of_ambient_decimal_context(system):
    from decimal import ROUND_UP, localcontext

    j, c, e, t = system
    i, a = approved(system)
    with localcontext() as context:
        context.prec = 3
        context.rounding = ROUND_UP
        order = e.dispatch(i, a.approval_id, now=NOW)
        assert order.reserved_cash == Decimal("10.01")
    assert read(j).reserved_cash == Decimal("10.01")


def test_expired_owner_grant_and_per_intent_revocation_deny(system):
    import json

    j, c, e, t = system
    i, a = approved(system)
    c.revoke(KEY, approval_id=a.approval_id, now=NOW)
    with pytest.raises(Denied):
        e.dispatch(i, a.approval_id, now=NOW)
    state = read(j)
    cfg = json.loads(state.config_json)
    cfg["live"]["authorization_expires_at"] = NOW.isoformat()
    grant = verify(state.authorization, Grant).changed(expires_at=NOW)
    state = state.changed(config_json=json.dumps(cfg), authorization=mock_sign(grant))
    report = evaluate(state, now=NOW, intent=i, approval=a)
    assert not next(x for x in report.checks if x.name == "unexpired_owner_authorization").satisfied
    assert t.calls == []


def test_buy_sell_round_trip_accounts_for_entry_and_exit_fees_once(system):
    j, c, e, t = system
    i, a = approved(system)
    order = e.dispatch(i, a.approval_id, now=NOW)
    buy = Fill(
        fill_id="roundtrip-buy",
        order_id=i.intent_id,
        account_key=KEY,
        instrument=i.instrument,
        side="buy",
        quantity=Decimal(2),
        price=Decimal(5),
        fee=Decimal(".01"),
        at=NOW,
    )
    t.observations[i.intent_id] = Observation(
        status="filled", broker_order_id=order.broker_order_id, fills=(buy,)
    )
    e.reconcile_order(KEY, i.intent_id, now=NOW)
    state = read(j)
    assert e.reconcile_account(KEY, cash=state.cash, holdings=state.holdings, now=NOW)
    c.resume(mock_sign(resume_fixture(read(j))), now=NOW)
    state = read(j)
    sell = intent_fixture(state, suffix="sell").changed(side="sell", target_weight=Decimal(0))
    approval = approval_fixture(state, sell)
    c.approve(sell, mock_sign(approval), now=NOW)
    order = e.dispatch(sell, approval.approval_id, now=NOW)
    sellfill = buy.changed(fill_id="roundtrip-sell", order_id=sell.intent_id, side="sell")
    t.observations[sell.intent_id] = Observation(
        status="filled", broker_order_id=order.broker_order_id, fills=(sellfill,)
    )
    e.reconcile_order(KEY, sell.intent_id, now=NOW)
    state = read(j)
    assert state.cash == Decimal("999.98") and state.holdings[0].realized_pnl == Decimal("-.02")
    assert e.reconcile_account(KEY, cash=state.cash, holdings=(), now=NOW)


def test_small_profile_and_unsigned_package_preserve_zero_live_defaults():
    import json
    from pathlib import Path

    from trading_agent.config.loading import load_config
    from trading_agent.supervised.package import unsigned_package

    cfg = load_config("config/pilot.simulation.yaml", env={})
    assert cfg.paper.initial_cash_usd == 1000 and cfg.backtest.initial_cash_usd == 1000
    assert cfg.app.mode.value == "simulation" and not cfg.live.enabled
    assert cfg.live.approved_capital_usd == 0 and cfg.live.owner_authorization_ref is None
    assert not cfg.universe.live_instrument_allowlist and cfg.authority() == "LIVE_NOT_AUTHORIZED"
    assert (
        json.loads(Path("docs/supervised_activation_package.unsigned.json").read_text())
        == unsigned_package()
    )


def test_reused_boot_label_does_not_bypass_monotonic_executor_fence(system):
    j, c, old, t = system
    new = MockExecutor(j, t, boot_id="fixture-boot", clock=lambda: NOW)
    new.startup(KEY, now=NOW)
    c.resume(mock_sign(resume_fixture(read(j))), now=NOW)
    i, a = approved((j, c, new, t))
    with pytest.raises(Denied, match="generation"):
        old.reserve(i, a.approval_id, now=NOW)
    assert new.dispatch(i, a.approval_id, now=NOW).status == "acknowledged"
    assert t.calls == [("submit", i.intent_id)]
