"""Property tests for configuration and risk invariants (build plan section 20)."""

from __future__ import annotations

import copy
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tests.conftest import VALID_CONFIG
from trading_agent.config.models import RiskSettings, TradingConfig

fractions = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("1"),
    places=4,
    allow_nan=False,
    allow_infinity=False,
)


@settings(max_examples=60, suppress_health_check=[HealthCheck.too_slow])
@given(
    max_position=fractions,
    max_gross=fractions,
    max_order=fractions,
    max_pending=fractions,
    min_cash=fractions,
)
def test_risk_limit_invariants_hold_for_random_fractions(
    max_position: Decimal,
    max_gross: Decimal,
    max_order: Decimal,
    max_pending: Decimal,
    min_cash: Decimal,
) -> None:
    settings_dict: dict[str, Any] = {
        "max_position_nav_fraction": str(max_position),
        "max_gross_nav_fraction": str(max_gross),
        "max_order_nav_fraction": str(max_order),
        "max_pending_entry_nav_fraction": str(max_pending),
        "min_cash_nav_fraction": str(min_cash),
    }
    consistent = (
        max_order <= max_position
        and max_pending <= max_gross
        and max_gross + min_cash <= Decimal(1)
    )
    if consistent:
        settings = RiskSettings(**settings_dict)
        assert settings.max_gross_nav_fraction + settings.min_cash_nav_fraction <= Decimal(1)
    else:
        with pytest.raises(Exception):  # noqa: B017 - any rejection is the invariant under test
            RiskSettings(**settings_dict)


@settings(max_examples=30, suppress_health_check=[HealthCheck.too_slow])
@given(
    capital=st.decimals(
        min_value=Decimal("0"),
        max_value=Decimal("1000000"),
        places=2,
        allow_nan=False,
        allow_infinity=False,
    ),
    mode=st.sampled_from(
        ["simulation", "paper", "shadow", "supervised_live", "bounded_autonomous_live"]
    ),
)
def test_full_config_roundtrip_never_authorizes_live(capital: Decimal, mode: str) -> None:
    data = copy.deepcopy(VALID_CONFIG)
    data["app"]["mode"] = mode
    data["live"]["approved_capital_usd"] = str(capital)
    if mode in ("supervised_live", "bounded_autonomous_live"):
        # A complete live profile still cannot become a usable path: either
        # config validation requires the full gate inputs, or the gate denies.
        data["live"]["enabled"] = capital > 0
        data["live"]["owner_authorization_ref"] = "owner-auth-test"
        data["live"]["authorization_expires_at"] = "2027-01-01T00:00:00+00:00"
        data["broker"]["provider"] = "robinhood"
        data["broker"]["approved_account_id"] = "alias-test"
        data["universe"]["live_instrument_allowlist"] = ["SPY"]
    try:
        config = TradingConfig.model_validate(data)
    except Exception:
        return  # failing clearly is the other acceptable outcome
    from trading_agent.execution.factory import build_broker_adapter
    from trading_agent.gates.live_activation import evaluate_live_activation

    decision = evaluate_live_activation(config, build_broker_adapter(config))
    assert not decision.authorized
    assert decision.authority == "LIVE_NOT_AUTHORIZED"


def test_money_parsing_roundtrip() -> None:
    from trading_agent.money import format_money, parse_money

    for raw in ["0", "100000", "0.05", "1234.5678", "-1.5"]:
        parsed = parse_money(raw, field="x", allow_negative=True)
        assert format_money(parsed) == str(parsed.normalize())
    with pytest.raises(ValueError):
        parse_money("1.2.3", field="x")
    with pytest.raises(ValueError):
        parse_money(True, field="x")
    with pytest.raises(ValueError):
        parse_money("abc", field="x")
