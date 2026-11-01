"""Deterministic synthetic market fixtures (no network, plan section 8).

Fixtures are engineering inputs only: fictional ``TEST_*`` instruments,
seeded price paths, explicit missing-data scenarios. Synthetic data is never
live data and never enters the live allowlist.
"""

from .synthetic import SyntheticMarket, build_synthetic_market

__all__ = ["SyntheticMarket", "build_synthetic_market"]
