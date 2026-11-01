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
        # M4: real shadow-mode gateway. Construction never opens a network
        # session; the first shadow cycle does that and fails closed.
        return RobinhoodMcpBrokerAdapter(config, session=session)
    return SimulatorBrokerAdapter(
        config,
        run_id=run_id,
        session=session,
        account_alias=account_alias,
        initial_cash=initial_cash,
    )


def build_shadow_adapter(
    config: TradingConfig, *, session: Session | None = None, phrase: str | None = None
) -> BrokerAdapter:
    """Adapter for the persistent shadow gateway (plan section 17).

    Honors ``broker.shadow_provider``; when unset it falls back to the
    engine's provider. Execution is disabled in every returned adapter:
    the simulator adapter rejects orders in live mode, and the Robinhood
    adapter refuses them in every mode.
    """
    provider = config.broker.shadow_provider or config.broker.provider
    if provider == "robinhood":
        if phrase is None:
            raise ConfigError(
                [
                    "broker: robinhood shadow gateway requires the credential vault phrase "
                    "(set TRADING_AGENT_CREDENTIAL_PHRASE or pass phrase=)"
                ]
            )
        return RobinhoodMcpBrokerAdapter(config, session=session, phrase=phrase)
    return SimulatorBrokerAdapter(config, session=session)
