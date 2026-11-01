"""Data gateway layer (plan section 7): the single market data entry point.

v1 ships the offline synthetic fixture as the only gateway. The interface is
stable; live/vendor gateways slot in behind the same contract.
"""

from .contracts import GatewayNotAvailableError, MarketDataGateway
from .fixture import SyntheticGateway, build_gateway

__all__ = [
    "GatewayNotAvailableError",
    "MarketDataGateway",
    "SyntheticGateway",
    "build_gateway",
]
