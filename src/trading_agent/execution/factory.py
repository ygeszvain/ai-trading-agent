"""Broker provider factory. Unknown providers fail closed."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from ..config.models import TradingConfig
from ..exceptions import ConfigError
from .broker_interface import BrokerAdapter
from .robinhood_mcp import RobinhoodMcpBrokerAdapter
from .simulator import SimulatorBrokerAdapter

PROVIDERS: dict[str, type[BrokerAdapter]] = {
    "simulator": SimulatorBrokerAdapter,
    "robinhood": RobinhoodMcpBrokerAdapter,
}


def build_broker_adapter(
    config: TradingConfig,
    *,
    run_id: str | None = None,
    session: Session | None = None,
    account_alias: str | None = None,
    initial_cash: Decimal | None = None,
) -> BrokerAdapter:
    provider = config.broker.provider
    if provider not in PROVIDERS:
        raise ConfigError(
            [
                f"broker.provider: {provider!r} is unknown; "
                f"supported providers: {', '.join(sorted(PROVIDERS))}"
            ]
        )
    if provider == "robinhood":
        return RobinhoodMcpBrokerAdapter(
            mcp_url=config.broker.robinhood_mcp_url,
            approved_account_id=config.broker.approved_account_id,
            allowlisted_tool_schema_digest=config.broker.allowlisted_tool_schema_digest,
        )
    return SimulatorBrokerAdapter(
        config,
        run_id=run_id,
        session=session,
        account_alias=account_alias,
        initial_cash=initial_cash,
    )
