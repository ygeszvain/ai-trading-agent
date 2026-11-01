"""Tests for shadow-paper lifecycle simulation."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from tests.test_learning_challenger import make_challenger
from trading_agent.backtest.engine import CloseSeries
from trading_agent.learning import LearningError
from trading_agent.learning.paper import simulate_paper


def uptrend(days: int = 60, step: str = "0.5") -> CloseSeries:
    origin = date(2025, 1, 6)
    prices = [Decimal("100") + Decimal(step) * i for i in range(days)]
    return CloseSeries(
        list(zip((origin + timedelta(days=i) for i in range(days)), prices, strict=True))
    )


def flat(days: int = 60) -> CloseSeries:
    origin = date(2025, 1, 6)
    return CloseSeries([(origin + timedelta(days=i), Decimal("100")) for i in range(days)])


def test_uptrend_produces_entry_trade():
    lifecycle = simulate_paper(
        make_challenger(),
        uptrend(),
        paper_id="p1",
        opened_at=date(2025, 1, 6),
        minimum_trades=1,
        initial_units=Decimal("100"),
    )
    assert lifecycle.status.value == "paper"
    assert len(lifecycle.trades) == 1
    assert lifecycle.trades[0].entry_session >= date(2025, 1, 6)
    assert lifecycle.trades[0].result_kind == "modeled_counterfactual"


def test_flat_series_produces_no_trades():
    lifecycle = simulate_paper(
        make_challenger(),
        flat(),
        paper_id="p1",
        opened_at=date(2025, 1, 6),
        minimum_trades=1,
        initial_units=Decimal("100"),
    )
    assert lifecycle.trades == ()


def test_lifecycle_dict_is_serializable():
    lifecycle = simulate_paper(
        make_challenger(),
        flat(),
        paper_id="p1",
        opened_at=date(2025, 1, 6),
        minimum_trades=1,
        initial_units=Decimal("100"),
    )
    raw = lifecycle.to_dict()
    assert raw["paper_id"] == "p1"
    assert raw["minimum_trades"] == 1


def test_minimum_trades_must_be_positive():
    with pytest.raises(LearningError):
        simulate_paper(
            make_challenger(),
            flat(),
            paper_id="p1",
            opened_at=date(2025, 1, 6),
            minimum_trades=0,
            initial_units=Decimal("100"),
        )
