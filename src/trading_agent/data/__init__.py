"""Market data access with explicit point-in-time semantics (plan section 8).

Consumers may only see observations whose timestamps are at or before the
as-of instant. Staleness is explicit (quality flags and session counts),
never guessed.
"""

from .provider import MarketDataProvider, SyntheticMarketProvider

__all__ = ["MarketDataProvider", "SyntheticMarketProvider"]
