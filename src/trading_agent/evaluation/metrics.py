"""Performance metrics with statistical discipline.

Plan section 15.3 — never report a Sharpe without: a t-statistic (flag if
< 2), a bootstrap confidence interval, and the number of trades. Ratios are
computed in Decimal where possible and converted to float only at the
boundary, per the repo-wide Decimal-precision rule.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from trading_agent.evaluation.accounting import ClosedTrade


def _to_float(value: Decimal) -> float:
    return float(value)


def mean(returns: list[Decimal]) -> float:
    if not returns:
        return 0.0
    return _to_float(sum(returns, Decimal(0)) / Decimal(len(returns)))


def stdev(returns: list[Decimal]) -> float:
    if len(returns) < 2:
        return 0.0
    m = sum(returns, Decimal(0)) / Decimal(len(returns))
    variance = sum(((r - m) ** 2 for r in returns), Decimal(0)) / Decimal(len(returns) - 1)
    return math.sqrt(_to_float(variance)) if variance > 0 else 0.0


def sharpe(returns: list[Decimal], periods_per_year: int = 252) -> float:
    s = stdev(returns)
    if s == 0:
        return 0.0
    return mean(returns) / s * math.sqrt(periods_per_year)


def sortino(returns: list[Decimal], periods_per_year: int = 252) -> float:
    downside = [r for r in returns if _to_float(r) < 0]
    if not downside:
        return 0.0 if mean(returns) <= 0 else math.inf
    m = mean(returns)
    downside_var = sum((r**2 for r in downside), Decimal(0)) / Decimal(len(returns))
    if downside_var <= 0:
        return 0.0 if m <= 0 else math.inf
    return m / math.sqrt(_to_float(downside_var)) * math.sqrt(periods_per_year)


def calmar(total_return: Decimal, max_drawdown: Decimal, years: Decimal) -> float:
    if years <= 0 or max_drawdown <= 0:
        return 0.0
    cagr = (Decimal(1) + total_return) ** (Decimal(1) / years) - 1
    return _to_float(cagr) / _to_float(max_drawdown)


def mean_t_statistic(returns: list[Decimal]) -> float:
    """t-statistic for the mean return; |t| < 2 => not distinguishable from zero."""
    n = len(returns)
    if n < 2:
        return 0.0
    m = mean(returns)
    s = stdev(returns)
    if s == 0:
        return 0.0
    return m / (s / math.sqrt(n))


def bootstrap_interval(
    returns: list[Decimal],
    statistic: Callable[[list[Decimal]], float],
    samples: int = 500,
    confidence: float = 0.95,
    rng_seed: int = 13,
) -> tuple[float, float]:
    """Resample daily returns (with replacement) to bracket a statistic.

    Deterministic seed keeps backtests reproducible — a requirement for
    fair A/B comparison between strategy versions.
    """
    import random

    if len(returns) < 5:
        point = statistic(returns)
        return (point, point)
    rng = random.Random(rng_seed)
    values = []
    for _ in range(samples):
        sample = [returns[rng.randrange(len(returns))] for _ in range(len(returns))]
        values.append(statistic(sample))
    values.sort()
    lo = values[int((1 - confidence) / 2 * samples)]
    hi = values[int((1 + confidence) / 2 * samples)]
    return (lo, hi)


@dataclass(frozen=True)
class PerformanceMetrics:
    total_return: Decimal
    cagr: float
    sharpe: float
    sharpe_t_stat: float
    sharpe_ci_low: float
    sharpe_ci_high: float
    sortino: float
    calmar: float
    max_drawdown: Decimal
    cost_ratio: Decimal
    n_trades: int
    n_sessions: int
    is_significant: bool

    def summary(self) -> str:
        flag = "significant" if self.is_significant else "NOT SIGNIFICANT (|t|<2)"
        return (
            f"return {_to_float(self.total_return):+.2%} "
            f"cagr {self.cagr:+.2%} "
            f"sharpe {self.sharpe:.2f} (t={self.sharpe_t_stat:.2f}, "
            f"95% CI [{self.sharpe_ci_low:.2f}, {self.sharpe_ci_high:.2f}], {flag}) "
            f"sortino {self.sortino:.2f} calmar {self.calmar:.2f} "
            f"mdd {_to_float(self.max_drawdown):.2%} "
            f"costs {_to_float(self.cost_ratio):.2%} of NAV "
            f"trades {self.n_trades} sessions {self.n_sessions}"
        )


def compute_metrics(
    daily_returns: list[Decimal],
    total_return: Decimal,
    max_drawdown: Decimal,
    cost_ratio: Decimal,
    trades: list[ClosedTrade],
    periods_per_year: int = 252,
    bootstrap_samples: int = 500,
) -> PerformanceMetrics:
    n = len(daily_returns)
    years = Decimal(n) / Decimal(periods_per_year)
    cagr = 0.0
    if years > 0:
        cagr = (float(Decimal(1) + total_return) ** (1.0 / _to_float(years))) - 1.0
    t_stat = mean_t_statistic(daily_returns)
    ci_low, ci_high = bootstrap_interval(daily_returns, sharpe, samples=bootstrap_samples)
    return PerformanceMetrics(
        total_return=total_return,
        cagr=cagr,
        sharpe=sharpe(daily_returns, periods_per_year),
        sharpe_t_stat=t_stat,
        sharpe_ci_low=ci_low,
        sharpe_ci_high=ci_high,
        sortino=sortino(daily_returns, periods_per_year),
        calmar=calmar(total_return, max_drawdown, years),
        max_drawdown=max_drawdown,
        cost_ratio=cost_ratio,
        n_trades=len(trades),
        n_sessions=n,
        is_significant=abs(t_stat) >= 2.0,
    )
