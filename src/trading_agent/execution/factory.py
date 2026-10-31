"""Broker provider factory. Unknown providers fail closed."""

from __future__ import annotations

from ..config.models import TradingConfig
from ..exceptions import ConfigError
from .broker_interface import BrokerAdapter
from .robinhood_mcp import RobinhoodMcpBrokerAdapter
from .simulator import SimulatorBrokerAdapter

PROVIDERS: dict[str, type[BrokerAdapter]] = {
    "simulator": SimulatorBrokerAdapter,
    "robinhood": RobinhoodMcpBrokerAdapter,
}


def build_broker_adapter(config: TradingConfig) -> BrokerAdapter:
    provider = config.broker.provider
    try:
        adapter_class = PROVIDERS[provider]
    except KeyError:
        raise ConfigError(
            [
                f"broker.provider: {provider!r} is unknown; "
                f"supported providers: {', '.join(sorted(PROVIDERS))}"
            ]
        ) from None
    if provider == "robinhood":
        return RobinhoodMcpBrokerAdapter(
            mcp_url=config.broker.robinhood_mcp_url,
            approved_account_id=config.broker.approved_account_id,
            allowlisted_tool_schema_digest=config.broker.allowlisted_tool_schema_digest,
        )
    return adapter_class()
