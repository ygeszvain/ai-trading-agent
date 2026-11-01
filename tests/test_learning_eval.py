"""Tests for the evaluation protocol: gates, folds, and promotion."""

from datetime import date, timedelta
from decimal import Decimal

from tests.test_learning_challenger import make_challenger
from trading_agent.backtest.engine import CloseSeries
from trading_agent.config.models import BacktestCostSettings
from trading_agent.learning import LearningGates, evaluate_challenger


def series_with(prices: list[Decimal]) -> CloseSeries:
    origin = date(2025, 1, 6)
    return CloseSeries(
        list(zip((origin + timedelta(days=i) for i in range(len(prices))), prices, strict=True))
    )


def uptrend(days: int = 120, step: Decimal = Decimal("0.5")) -> CloseSeries:
    return series_with([Decimal("100") + step * i for i in range(days)])


def flat(days: int = 60) -> CloseSeries:
    return series_with([Decimal("100")] * days)


COST = BacktestCostSettings(fee_rate=Decimal("0.0005"), slippage_rate=Decimal("0.001"))


def test_flat_series_fails_min_trades_gate():
    report = evaluate_challenger(
        make_challenger(),
        flat(),
        [flat()],
        gates=LearningGates(min_trades=1, fold_min=1),
        cost=COST,
    )
    assert report.gates_passed is False
    assert any("min_trades" in reason for reason in report.gate_reasons)
    assert report.new_challenger.status == "shadow"
    assert report.champion is None


def test_healthy_rally_never_promotes_challenger():
    report = evaluate_challenger(
        make_challenger(),
        uptrend(),
        [uptrend()],
        gates=LearningGates(min_trades=1, fold_min=1),
        cost=COST,
    )
    assert report.gates_passed is True
    assert report.gate_reasons == ()
    assert report.new_challenger.status == "shadow"
    assert report.champion is None
    assert len(report.folds) == 2
    assert all(fold.n_fills >= 1 for fold in report.folds)


def test_fold_results_keep_accounting_fields():
    report = evaluate_challenger(
        make_challenger(),
        uptrend(),
        [uptrend()],
        gates=LearningGates(min_trades=1, fold_min=1),
        cost=COST,
    )
    fold = report.folds[0]
    assert fold.fill_count == fold.n_fills
    assert fold.traded is True
    assert fold.initial_equity == Decimal("100000")
    assert len(report.rule_digest) == 64
