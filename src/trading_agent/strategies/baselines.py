"""Cash and passive baselines (plan section 11: "Baselines first").

Both baselines use the SAME capital, evaluation period, and cost conventions
as the active strategy (docs/strategy_momentum_v1.md). They are comparison
books in the ledger: cash accrues the documented daily yield, and the passive
book buys the fixture universe once at the first session open (with the same
spread/fee conventions) and holds. Baselines are not routed through the risk
engine: they are benchmarks, not trading decisions.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..config.models import TradingConfig
from ..contracts.market import MarketBar
from ..money import round_money

_DAYS_PER_YEAR = Decimal(365)


def daily_yield_factor(cash_yield_annual: Decimal) -> Decimal:
    """Per-session simple-compounding factor: (1 + annual)^(1/365) - 1."""
    # Decimal has no fractional power; use a 28-digit ln/exp approximation
    # kept deterministic via fixed precision.
    import math
    from decimal import Decimal as _D

    annual = float(cash_yield_annual)
    daily = math.exp(math.log(1.0 + annual) / 365.0) - 1.0
    return _D(str(round(daily, 12)))


@dataclass(frozen=True)
class BaselinePlan:
    """The passive baseline's first-session purchase plan."""

    legs: tuple[tuple[str, Decimal, Decimal], ...]  # (instrument, quantity, limit_price)


class CashBaseline:
    """The full capital sits in cash earning the documented yield."""

    key = "cash-baseline"

    def __init__(self, config: TradingConfig) -> None:
        self._config = config
        self._factor = daily_yield_factor(config.engine.cash_yield_annual)

    def accrual(self, cash: Decimal) -> Decimal:
        return round_money(cash * self._factor)


class PassiveBaseline:
    """Equal-weight buy-and-hold of the configured passive basket."""

    key = "passive-baseline"

    def __init__(self, config: TradingConfig) -> None:
        self._config = config
        self._factor = daily_yield_factor(config.engine.cash_yield_annual)
        self._basket = list(config.engine.passive_basket)
        self._spread_bps = config.engine.spread_bps
        self._purchased = False

    def purchase_plan(self, initial_cash: Decimal, open_bars: dict[str, MarketBar]) -> BaselinePlan:
        """Buy equal-weight legs at the first session open (spread + fee embedded)."""
        self._purchased = True
        if not self._basket:
            return BaselinePlan(legs=())
        legs: list[tuple[str, Decimal, Decimal]] = []
        per_leg = round_money(initial_cash / Decimal(len(self._basket)))
        for instrument_id in self._basket:
            bar = open_bars.get(instrument_id)
            if bar is None:
                continue  # missing open data: leave the leg in cash (honest, documented)
            limit = _round_up(bar.open * (1 + self._spread_bps / Decimal(10_000)), 2)
            quantity = (per_leg / limit).to_integral_value(rounding="ROUND_DOWN")
            if quantity > 0:
                legs.append((instrument_id, quantity, limit))
        return BaselinePlan(legs=tuple(legs))

    def accrual(self, cash: Decimal) -> Decimal:
        return round_money(cash * self._factor)

    def mark_bars(self) -> dict[str, MarketBar]:
        return {}


def _round_up(value: Decimal, decimals: int) -> Decimal:
    from decimal import ROUND_UP

    return value.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_UP)
