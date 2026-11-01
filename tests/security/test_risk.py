from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from tests.security.conftest import NOW
from trading_agent.contracts.decision import Decision, DecisionAction, RiskOutcome
from trading_agent.contracts.market import Quote
from trading_agent.contracts.orders import OrderIntent, OrderSide, TimeInForce
from trading_agent.risk.engine import RiskEngine, RiskState


def inputs(config):
    decision = Decision(
        "decision",
        "run",
        "local-sim",
        "simulation",
        "TEST_A",
        NOW,
        NOW + timedelta(minutes=1),
        DecisionAction.ENTER,
        Decimal("0.05"),
        "momentum-v1",
        None,
        "fixture",
        "fixture",
        risk_policy_version="paper-policy-v1",
    )
    intent = OrderIntent(
        "intent",
        "run",
        decision.decision_id,
        "local-sim",
        "TEST_A",
        OrderSide.BUY,
        Decimal(1000),
        Decimal(100),
        TimeInForce.DAY,
        "client",
        NOW,
        "paper-policy-v1",
        "momentum-v1",
    )
    state = RiskState(
        nav=Decimal(100000),
        cash=Decimal(100000),
        reserved_cash=Decimal(0),
        volumes={"TEST_A": Decimal(100000000)},
        marks={"TEST_A": Decimal(100)},
        quote_age_seconds={"TEST_A": Decimal(0)},
        sessions_since={"TEST_A": 0},
        account_as_of=NOW,
        day_start_nav=Decimal(100000),
        high_water_mark=Decimal(100000),
    )
    return decision, intent, state, Quote("TEST_A", Decimal(100), NOW)


def test_reduced_quantity_is_the_quantity_returned_to_execution(review_config):
    decision, intent, state, quote = inputs(review_config)
    result, quantity = RiskEngine(review_config, exchange_timezone="America/New_York").evaluate(
        decision, intent, state, quote, now=NOW
    )
    assert result.passed
    assert quantity <= Decimal(20)
    assert quantity < intent.quantity


def test_protective_flag_cannot_exempt_a_buy_from_limits(review_config):
    decision, intent, state, quote = inputs(review_config)
    result, quantity = RiskEngine(review_config, exchange_timezone="America/New_York").evaluate(
        decision, intent, state, quote, now=NOW, is_protective_exit=True
    )
    assert result.outcome == RiskOutcome.REJECT and quantity == 0


def test_stale_future_expired_paused_and_wrong_account_inputs_are_rejected(review_config):
    decision, intent, state, quote = inputs(review_config)
    engine = RiskEngine(review_config, exchange_timezone="America/New_York")
    cases = [
        (replace(decision, expires_at=NOW), intent, state, quote),
        (decision, replace(intent, account_alias="outside"), state, quote),
        (decision, intent, replace(state, account_as_of=NOW - timedelta(seconds=11)), quote),
        (decision, intent, replace(state, paused=True), quote),
        (decision, intent, state, replace(quote, as_of=NOW + timedelta(seconds=2))),
        (decision, intent, state, replace(quote, as_of=NOW - timedelta(seconds=6))),
        (decision, intent, replace(state, high_water_mark=Decimal(0)), quote),
    ]
    for d, i, s, q in cases:
        result, quantity = engine.evaluate(d, i, s, q, now=NOW)
        assert result.outcome == RiskOutcome.REJECT and quantity == 0


def test_pending_entries_are_included_in_gross_exposure(review_config):
    decision, intent, state, quote = inputs(review_config)
    state = replace(
        state,
        positions={"TEST_B": Decimal(240)},
        marks={"TEST_A": Decimal(100), "TEST_B": Decimal(100)},
        pending_entry_value=Decimal(4000),
    )
    result, quantity = RiskEngine(review_config, exchange_timezone="America/New_York").evaluate(
        decision, intent, state, quote, now=NOW
    )
    assert result.outcome == RiskOutcome.REJECT and quantity == 0
