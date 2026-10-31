"""Invalid financial configuration must fail clearly (Prompt 1 acceptance).

Direct model validation surfaces a pydantic ``ValidationError`` carrying every
violation; ``load_config`` re-wraps those as a classified ``ConfigError``.
Both paths fail loudly with actionable messages — never silently.
"""

from __future__ import annotations

import copy
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from tests.conftest import VALID_CONFIG
from trading_agent.config.models import TradingConfig, TradingMode, is_live_mode
from trading_agent.exceptions import ConfigError


def _config(data: dict[str, Any] | None = None) -> TradingConfig:
    merged = copy.deepcopy(VALID_CONFIG)
    for section, values in (data or {}).items():
        merged[section] = {**merged.get(section, {}), **values}
    return TradingConfig.model_validate(merged)


def _violation_text(data: dict[str, Any]) -> str:
    merged = copy.deepcopy(VALID_CONFIG)
    for section, values in data.items():
        merged[section] = {**merged.get(section, {}), **values}
    with pytest.raises(ValidationError) as exc:
        TradingConfig.model_validate(merged)
    return str(exc.value)


def _config_error_text(data: dict[str, Any], tmp_path: Any) -> str:
    import yaml

    from trading_agent.config.loading import load_config

    merged = copy.deepcopy(VALID_CONFIG)
    for section, values in data.items():
        merged[section] = {**merged.get(section, {}), **values}
    file = tmp_path / "config.yaml"
    file.write_text(yaml.safe_dump(merged))
    with pytest.raises(ConfigError) as exc:
        load_config(path=file, env={})
    return exc.value.format()


def test_simulation_defaults_load() -> None:
    config = _config()
    assert config.app.mode is TradingMode.SIMULATION
    assert not is_live_mode(config.app.mode)
    assert config.live.approved_capital_usd == Decimal("0")
    assert config.authority() == "LIVE_NOT_AUTHORIZED"


def test_live_mode_with_zero_capital_fails() -> None:
    text = _violation_text({"app": {"mode": "supervised_live"}, "live": {"enabled": True}})
    assert "approved_capital_usd" in text


def test_live_flag_without_live_mode_fails() -> None:
    text = _violation_text({"live": {"enabled": True}})
    assert "live flags require a live mode" in text


def test_live_mode_without_flag_fails() -> None:
    text = _violation_text({"app": {"mode": "bounded_autonomous_live"}})
    assert "live.enabled=true" in text


def test_live_requires_owner_authorization_and_expiry() -> None:
    text = _violation_text(
        {
            "app": {"mode": "supervised_live"},
            "live": {"enabled": True, "approved_capital_usd": "1000"},
            "broker": {"provider": "robinhood", "approved_account_id": "my-agent-account"},
            "universe": {"live_instrument_allowlist": ["SPY"]},
        }
    )
    assert "owner_authorization_ref" in text
    assert "authorization_expires_at" in text


def test_live_mode_fully_populated_passes_config_validation() -> None:
    # Config validation accepts a complete live configuration; the activation
    # gate (test_live_activation_gate.py) still denies it in M0.
    config = _config(
        {
            "app": {"mode": "supervised_live"},
            "live": {
                "enabled": True,
                "approved_capital_usd": "1000",
                "owner_authorization_ref": "owner-auth-2026-11",
                "authorization_expires_at": "2026-12-31T00:00:00+00:00",
            },
            "broker": {
                "provider": "robinhood",
                "approved_account_id": "my-agent-account",
                "allowlisted_tool_schema_digest": "sha256:abc123",
            },
            "universe": {"live_instrument_allowlist": ["SPY", "QQQ"]},
        }
    )
    assert config.live.enabled
    assert config.live.approved_capital_usd > 0


def test_negative_capital_fails() -> None:
    text = _violation_text({"live": {"approved_capital_usd": "-5"}})
    assert "negative" in text


def test_nan_capital_fails() -> None:
    text = _violation_text({"live": {"approved_capital_usd": "nan"}})
    assert "non-finite" in text


def test_malformed_capital_fails() -> None:
    text = _violation_text({"live": {"approved_capital_usd": "1,000"}})
    assert "not a valid decimal" in text


def test_test_symbol_rejected_from_live_allowlist() -> None:
    text = _violation_text({"universe": {"live_instrument_allowlist": ["SPY", "TEST_A"]}})
    assert "TEST_A" in text
    assert "synthetic" in text


def test_synthetic_live_overlap_rejected() -> None:
    text = _violation_text(
        {
            "paper": {"synthetic_fixture_universe": ["TEST_A", "QQQ"]},
            "universe": {"live_instrument_allowlist": ["QQQ"]},
        }
    )
    assert "overlap" in text


def test_cloud_fallback_true_rejected() -> None:
    text = _violation_text({"llm": {"allow_cloud_fallback": True}})
    assert "cloud fallback" in text


def test_non_loopback_llm_url_rejected() -> None:
    text = _violation_text({"llm": {"base_url": "https://api.openai.com/v1"}})
    assert "not a loopback" in text


def test_non_loopback_web_host_rejected() -> None:
    text = _violation_text({"app": {"web_host": "0.0.0.0"}})
    assert "loopback" in text


def test_unknown_top_level_section_rejected() -> None:
    data = copy.deepcopy(VALID_CONFIG)
    data["mystery"] = {"x": 1}
    with pytest.raises(ValidationError):
        TradingConfig.model_validate(data)


def test_unknown_section_key_rejected() -> None:
    data = copy.deepcopy(VALID_CONFIG)
    data["app"]["mystery_key"] = 1
    with pytest.raises(ValidationError):
        TradingConfig.model_validate(data)


def test_order_larger_than_position_rejected() -> None:
    text = _violation_text({"risk": {"max_order_nav_fraction": "0.10"}})
    assert "max_order_nav_fraction must not exceed" in text


def test_gross_plus_min_cash_over_unity_rejected() -> None:
    text = _violation_text({"risk": {"min_cash_nav_fraction": "0.90"}})
    assert "must not exceed 1.0" in text


def test_emergency_liquidation_true_rejected() -> None:
    text = _violation_text({"risk": {"emergency_liquidation_enabled": True}})
    assert "emergency_liquidation_enabled" in text


def test_paid_subscription_requires_positive_budget() -> None:
    text = _violation_text({"costs": {"allow_paid_subscriptions": True}})
    assert "paid" in text.lower()


def test_live_auto_promotion_true_rejected() -> None:
    text = _violation_text({"learning": {"live_auto_promotion_enabled": True}})
    assert "live_auto_promotion_enabled" in text


def test_authorized_config_summary_never_contains_secret() -> None:
    data = copy.deepcopy(VALID_CONFIG)
    data["llm"]["auth_token"] = "super-secret-token"
    config = TradingConfig.model_validate(data)
    summary_text = repr(config.sanitized_summary())
    assert "super-secret-token" not in summary_text
    assert config.sanitized_summary()["llm"]["auth_token_configured"] is True


def test_load_config_wraps_violations_as_config_error(tmp_path: Any) -> None:
    text = _config_error_text(
        {
            "live": {"approved_capital_usd": "-1"},
            "llm": {"allow_cloud_fallback": True},
        },
        tmp_path,
    )
    assert "CONFIGURATION ERROR" in text
    assert "negative" in text
    assert "cloud fallback" in text
