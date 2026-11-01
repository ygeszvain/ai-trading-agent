"""Benchmark comparison under identical cost assumptions.

Plan section 15.2 — a strategy is only evaluated against a benchmark that
suffers the same execution costs (same next-session latency, same slippage
model). A 3%-of-NAV cost drag that the strategy pays but the benchmark
doesn't flatters the strategy; this guarantees parity: the benchmark is a
simple buy-and-hold of the index re-entered once at the start, filled by
the *same* ConservativeExecutionModel the strategy uses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from trading_agent.evaluation.accounting import AccountingEngine
from trading_agent.evaluation.execution_model import (
    ConservativeExecutionModel,
    Order,
    OrderSide,
    OrderType,
    PendingQueue,
    base_price,
)
from trading_agent.evaluation.metrics import PerformanceMetrics, compute_metrics


@dataclass(frozen=True)
class BenchmarkResult:
    benchmark_symbol: str
    metrics: PerformanceMetrics
    final_nav: Decimal
    observations: dict = field(default_factory=dict)  # not part of comparison


def run_benchmark(
    observations: dict[str, dict],
    benchmark_symbol: str,
    capital: Decimal,
    execution: ConservativeExecutionModel,
    bootstrap_samples: int = 500,
) -> BenchmarkResult:
    sessions = sorted(observations.get(benchmark_symbol, ()))
    if len(sessions) < 2:
        raise ValueError(f"benchmark {benchmark_symbol} has < 2 sessions")
    engine = AccountingEngine(observations, capital, sessions[0])
    queue = PendingQueue(execution)
    price = base_price(benchmark_symbol, sessions[0], observations)
    # invest 95% at the start, like a lazy buy-and-hold (5% cash buffer)
    quantity = (capital * Decimal("0.95")) / price
    quantity = quantity // Decimal("1")  # whole shares
    if quantity > 0:
        order = Order(
            instrument=benchmark_symbol,
            side=OrderSide.BUY,
            quantity=quantity,
            signal_session=sessions[0],
            ref_price=price,
            order_type=OrderType.MARKET,
        )
        queue.submit(order)
    for session in sessions[1:]:
        for fill in queue.process_session(session):
            engine.apply_fill(fill)
        engine.mark(session)
    nav_points = engine.nav_series()
    final_nav = nav_points[-1].nav
    metrics = compute_metrics(
        engine.daily_returns(),
        engine.total_return(),
        engine.max_drawdown(),
        engine.cost_ratio(),
        engine.closed_trades,
        bootstrap_samples=bootstrap_samples,
    )
    return BenchmarkResult(
        benchmark_symbol=benchmark_symbol,
        metrics=metrics,
        final_nav=final_nav,
    )
