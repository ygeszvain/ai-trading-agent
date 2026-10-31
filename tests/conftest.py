"""Shared fixtures: a known-good configuration dict and environment."""

from __future__ import annotations

import copy
from typing import Any

import pytest

VALID_CONFIG: dict[str, Any] = {
    "app": {
        "environment": "development",
        "mode": "simulation",
        "display_timezone": "America/Chicago",
        "exchange_timezone": "America/New_York",
        "web_host": "127.0.0.1",
        "web_port": 8000,
    },
    "llm": {
        "provider": "lmstudio",
        "base_url": "http://127.0.0.1:1234/v1",
        "model_id": None,
        "allow_cloud_fallback": False,
    },
    "broker": {
        "provider": "simulator",
        "approved_account_id": None,
    },
    "live": {
        "enabled": False,
        "approved_capital_usd": "0",
        "owner_authorization_ref": None,
    },
    "paper": {
        "initial_cash_usd": "100000",
        "synthetic_fixture_universe": ["TEST_A", "TEST_B"],
    },
    "universe": {
        "live_instrument_allowlist": [],
        "allow_short_sales": False,
        "allow_options": False,
        "allow_crypto": False,
    },
    "risk": {
        "policy_version": "paper-policy-v1",
        "max_position_nav_fraction": "0.05",
        "max_gross_nav_fraction": "0.25",
        "max_positions": 5,
        "max_order_nav_fraction": "0.02",
        "max_pending_entry_nav_fraction": "0.05",
        "min_cash_nav_fraction": "0.75",
        "emergency_liquidation_enabled": False,
    },
    "learning": {
        "enabled": True,
        "live_auto_promotion_enabled": False,
    },
    "costs": {
        "paid_data_budget_usd_per_month": "0",
        "allow_paid_subscriptions": False,
    },
}


@pytest.fixture
def valid_config_dict() -> dict[str, Any]:
    return copy.deepcopy(VALID_CONFIG)


@pytest.fixture
def empty_env() -> dict[str, str]:
    return {}
