"""No usable live execution path exists in M0 (Prompt 1 acceptance)."""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import Any

import pytest

from tests.conftest import VALID_CONFIG
from trading_agent.config.loading import load_config
from trading_agent.config.models import TradingConfig
from trading_agent.contracts.broker import BrokerCapabilities
from trading_agent.exceptions import ConfigError
from trading_agent.execution.broker_interface import BrokerAdapter
from trading_agent.execution.factory import build_broker_adapter
from trading_agent.gates.live_activation import (
    NOT_AUTHORIZED,
    evaluate_live_activation,
)

NOW = datetime(2026, 10, 31, 12, 0, 0, tzinfo=UTC)


def _config(data: dict[str, Any] | None = None) -> TradingConfig:
    merged = copy.deepcopy(VALID_CONFIG)
    for section, values in (data or {}).items():
        merged[section] = {**merged.get(section, {}), **values}
    return TradingConfig.model_validate(merged)


def test_simulation_config_denied_and_reports_gaps() -> None:
    config = load_config(path=None, env={})
    decision = evaluate_live_activation(config, build_broker_adapter(config), now=NOW)
    assert decision.authorized is False
    assert decision.authority == NOT_AUTHORIZED
    assert len(decision.unmet) >= 10
    names = {check.name for check in decision.unmet}
    assert {
        "live_enabled_flag",
        "mode_is_live",
        "approved_capital_nonzero",
        "reconciliation_healthy",
        "strategy_active",
    } <= names


def test_perfect_live_config_still_denied_in_m0() -> None:
    """Even a fully populated live profile cannot activate in M0."""
    config = _config(
        {
            "app": {"mode": "supervised_live"},
            "live": {
                "enabled": True,
                "approved_capital_usd": "1000",
                "owner_authorization_ref": "owner-auth-2026-11",
                "authorization_expires_at": "2027-01-01T00:00:00+00:00",
            },
            "broker": {
                "provider": "robinhood",
                "approved_account_id": "my-agent-account",
                "allowlisted_tool_schema_digest": "sha256:abc123",
            },
            "universe": {"live_instrument_allowlist": ["SPY"]},
        }
    )
    decision = evaluate_live_activation(config, build_broker_adapter(config), now=NOW)
    assert decision.authorized is False
    assert decision.authority == NOT_AUTHORIZED
    names = {check.name for check in decision.unmet}
    # The config-side checks pass; the runtime-side checks cannot be satisfied
    # in M0 (no connection, no strategy, no reconciliation).
    assert "broker_connected" in names
    assert "broker_capabilities_verified" in names
    assert "reconciliation_healthy" in names
    assert "strategy_active" in names
    assert "live_enabled_flag" not in names


def test_single_env_flag_cannot_activate() -> None:
    # A lone LIVE_TRADING_ENABLED flag without a live mode is rejected at load
    # time; even if it somehow loaded, the gate would still deny activation.
    with pytest.raises(ConfigError) as exc:
        load_config(path=None, env={"LIVE_TRADING_ENABLED": "true"})
    assert any("live" in violation for violation in exc.value.violations)


class _VerifiedBroker(BrokerAdapter):
    """Counterfactual: a hypothetical future fully-verified gateway."""

    provider = "robinhood"

    def capabilities(self) -> BrokerCapabilities:
        return BrokerCapabilities(
            provider="robinhood",
            connected=True,
            reads_enabled=True,
            execution_enabled=True,
            verified_capability_digest="sha256:abc123",
        )

    def account_snapshot(self) -> None:  # pragma: no cover - gate must not read state
        raise AssertionError("gate must not read state")

    def submit_order(self, request) -> None:  # pragma: no cover
        raise AssertionError("gate must not submit")

    def cancel_order(self, broker_order_id: str) -> None:  # pragma: no cover
        raise AssertionError("gate must not cancel")


def test_gate_rejects_even_a_hypothetical_verified_gateway_in_m0() -> None:
    config = _config(
        {
            "app": {"mode": "supervised_live"},
            "live": {
                "enabled": True,
                "approved_capital_usd": "1000",
                "owner_authorization_ref": "owner-auth-2026-11",
                "authorization_expires_at": "2027-01-01T00:00:00+00:00",
            },
            "broker": {
                "provider": "robinhood",
                "approved_account_id": "my-agent-account",
                "allowlisted_tool_schema_digest": "sha256:abc123",
            },
            "universe": {"live_instrument_allowlist": ["SPY"]},
        }
    )
    decision = evaluate_live_activation(config, _VerifiedBroker(), now=NOW)
    assert decision.authorized is False
    names = {check.name for check in decision.unmet}
    assert names == {"reconciliation_healthy", "strategy_active"}


def test_expired_authorization_is_unmet() -> None:
    config = _config(
        {
            "live": {
                "enabled": False,
                "authorization_expires_at": "2020-01-01T00:00:00+00:00",
            }
        }
    )
    decision = evaluate_live_activation(config, build_broker_adapter(config), now=NOW)
    check = next(c for c in decision.checks if c.name == "authorization_unexpired")
    assert check.satisfied is False
    assert "expired" in check.detail


def test_summary_names_unmet_prerequisites() -> None:
    config = load_config(path=None, env={})
    decision = evaluate_live_activation(config, build_broker_adapter(config), now=NOW)
    summary = decision.summary()
    assert NOT_AUTHORIZED in summary
    assert "unmet" in summary
