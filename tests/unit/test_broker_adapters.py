"""Broker adapters must explicitly reject execution; never fabricate success."""

from __future__ import annotations

from decimal import Decimal

import pytest

from trading_agent.config.loading import load_config
from trading_agent.contracts.broker import (
    BrokerError,
    BrokerExecutionDenied,
    BrokerExecutionNotAvailable,
    BrokerStateNotAvailable,
    BrokerUnavailable,
    NormalizedOrderStatus,
    OrderRequest,
    OrderResult,
)
from trading_agent.exceptions import ConfigError
from trading_agent.execution.factory import PROVIDERS, build_broker_adapter


def _request() -> OrderRequest:
    return OrderRequest(
        instrument="TEST_A",
        side="buy",
        quantity=Decimal("10"),
        limit_price=Decimal("100.00"),
        time_in_force="day",
        client_order_id="cli-0001",
    )


@pytest.fixture
def config() -> object:
    return load_config(path=None, env={})  # uses config/simulation.yaml


def test_factory_providers_registered() -> None:
    assert set(PROVIDERS) == {"simulator", "robinhood"}


def test_simulator_reports_local_but_not_executable() -> None:
    # Unbound (no run context): the venue is local code, not a connection to
    # anything; it must advertise that it holds no state and offers no
    # execution, and must never claim to be connected to a broker.
    config = load_config(path=None, env={})
    adapter = build_broker_adapter(config)
    capabilities = adapter.capabilities()
    assert capabilities.provider == "simulator"
    assert capabilities.connected is False
    assert capabilities.reads_enabled is False
    assert capabilities.execution_enabled is False
    assert capabilities.verified_capability_digest is None
    assert any("not bound" in note for note in capabilities.notes)


def test_simulator_rejects_submission_without_executing() -> None:
    config = load_config(path=None, env={})
    adapter = build_broker_adapter(config)
    with pytest.raises(BrokerExecutionNotAvailable) as exc:
        adapter.submit_order(_request())
    message = str(exc.value)
    assert "no run context bound" in message
    assert "not executed" in message


def test_simulator_rejects_cancellation() -> None:
    config = load_config(path=None, env={})
    adapter = build_broker_adapter(config)
    with pytest.raises(BrokerExecutionNotAvailable):
        adapter.cancel_order("ord-unknown")


def test_simulator_never_fabricates_a_snapshot() -> None:
    config = load_config(path=None, env={})
    adapter = build_broker_adapter(config)
    with pytest.raises(BrokerStateNotAvailable):
        adapter.account_snapshot()


def test_robinhood_adapter_reports_not_connected() -> None:
    from trading_agent.execution.robinhood_mcp import RobinhoodMcpBrokerAdapter

    adapter = RobinhoodMcpBrokerAdapter()
    capabilities = adapter.capabilities()
    assert capabilities.connected is False
    assert capabilities.reads_enabled is False
    assert capabilities.execution_enabled is False
    assert capabilities.verified_capability_digest is None


@pytest.mark.parametrize(
    ("method", "error_class"),
    [
        ("submit_order", BrokerUnavailable),
        ("cancel_order", BrokerUnavailable),
        ("account_snapshot", BrokerUnavailable),
    ],
)
def test_robinhood_adapter_rejects_everything_before_transport(
    method: str, error_class: type[BrokerError]
) -> None:
    from trading_agent.execution.robinhood_mcp import RobinhoodMcpBrokerAdapter

    adapter = RobinhoodMcpBrokerAdapter()
    if method == "submit_order":
        with pytest.raises(error_class) as exc:
            adapter.submit_order(_request())
    elif method == "cancel_order":
        with pytest.raises(error_class) as exc:
            adapter.cancel_order("ord-1")
    else:
        with pytest.raises(error_class) as exc:
            adapter.account_snapshot()
    message = str(exc.value)
    assert "LIVE_NOT_AUTHORIZED" in message or "REJECTED" in message


def test_order_result_cannot_claim_success() -> None:
    result = OrderResult()
    assert result.accepted is False
    assert result.status is NormalizedOrderStatus.REJECTED


def test_execution_denied_is_a_classified_broker_error() -> None:
    assert issubclass(BrokerExecutionDenied, BrokerError)


def test_invalid_env_config_fails_at_load(valid_config_dict: dict, tmp_path) -> None:
    import yaml

    bad = valid_config_dict
    bad["live"]["approved_capital_usd"] = "-1"
    file = tmp_path / "bad.yaml"
    file.write_text(yaml.safe_dump(bad))
    with pytest.raises(ConfigError) as exc:
        load_config(path=file, env={})
    assert any("negative" in violation for violation in exc.value.violations)


def test_missing_config_file_fails_clearly(tmp_path) -> None:
    with pytest.raises(ConfigError) as exc:
        load_config(path=tmp_path / "nope.yaml", env={})
    assert any("not found" in violation for violation in exc.value.violations)


def test_malformed_yaml_fails_clearly(tmp_path) -> None:
    file = tmp_path / "broken.yaml"
    file.write_text("app: [unclosed")
    with pytest.raises(ConfigError) as exc:
        load_config(path=file, env={})
    assert any("not valid YAML" in violation for violation in exc.value.violations)
