"""Conservative execution model: latency, limits, partials, halts, costs."""

from datetime import date
from decimal import Decimal

import pytest

from trading_agent.evaluation.execution_model import (
    ConservativeExecutionModel,
    ExecutionCosts,
    Order,
    OrderSide,
    OrderType,
    PendingQueue,
    SessionObservation,
)

D1, D2, D3, D4 = date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 6), date(2024, 1, 7)

SIG = SessionObservation(
    D1, Decimal("100"), Decimal("100.5"), Decimal("101"), Decimal("99.5"), Decimal("1_000_000")
)


def _bar(day: date, close, open_=None, high=None, low=None, volume=Decimal("1_000_000")):
    return SessionObservation(day, close, open_, high, low, volume)


def _model(costs=None, obs=None):
    costs = costs if costs is not None else ExecutionCosts()
    if obs is None:
        obs = {
            "T": {
                D1: SIG,
                D2: _bar(D2, Decimal("100.2"), Decimal("100.4"), Decimal("101"), Decimal("99.4")),
                D3: _bar(D3, Decimal("101"), Decimal("100.5"), Decimal("101.5"), Decimal("100")),
                D4: _bar(D4, Decimal("101.2"), Decimal("101"), Decimal("101.6"), Decimal("100.8")),
            }
        }
    return ConservativeExecutionModel(obs, costs)


def _limit_order(model=None, qty=Decimal("1000")):
    model = model if model is not None else _model()
    return Order.from_signal(
        instrument="T",
        side=OrderSide.BUY,
        quantity=qty,
        signal_session=D1,
        ref_price=Decimal("100"),
        costs=model.costs,
        order_type=OrderType.LIMIT,
    )


def test_same_session_fill_forbidden():
    model = _model()
    order = _limit_order(model)
    with pytest.raises(ValueError, match="same-session"):
        model.attempt_fill(order, D1)


def test_next_session_open_fill_with_itemized_costs():
    model = _model()
    order = Order.from_signal(
        instrument="T",
        side=OrderSide.BUY,
        quantity=Decimal("1000"),
        signal_session=D1,
        ref_price=Decimal("100"),
        costs=model.costs,
    )
    fill = model.attempt_fill(order, D2)
    assert fill is not None
    assert fill.session == D2
    assert fill.price > Decimal("100.4")
    assert fill.price < Decimal("100.4") * Decimal("1.05")
    assert fill.fee > 0 and fill.spread_cost > 0 and fill.slippage_cost > 0


def test_limit_fills_only_when_reached():
    model = _model()
    order = _limit_order(model)
    assert order.limit_price == Decimal("99.500000")
    assert model.attempt_fill(order, D2) is not None
    model_high = _model(
        obs={
            "T": {
                D1: SIG,
                D2: _bar(D2, Decimal("101"), Decimal("100.6"), Decimal("102"), Decimal("100.5")),
            }
        }
    )
    assert model_high.attempt_fill(order, D2) is None


def test_limit_gap_through_fills_at_open():
    model = _model(
        obs={
            "T": {
                D1: SIG,
                D2: _bar(D2, Decimal("100.2"), Decimal("99.3"), Decimal("101"), Decimal("99.3")),
            }
        }
    )
    order = _limit_order(model)
    fill = model.attempt_fill(order, D2)
    assert fill is not None
    # filled at the (more favorable) open of 99.3, plus per-share costs
    assert fill.price > Decimal("99.3")
    assert fill.price < Decimal("100")


def test_partial_fill_capped_by_volume_participation():
    model = _model()
    order = _limit_order(model, qty=Decimal("200_000"))
    queue = PendingQueue(model)
    queue.submit(order)
    fills = queue.process_session(D2)
    assert len(fills) == 1
    assert fills[0].status.value == "partial"
    assert fills[0].quantity == Decimal("100000")
    assert queue.pending()[0].quantity == Decimal("100000")


def test_halted_session_never_fills_then_cancellation():
    costs = ExecutionCosts(pending_max_sessions=1)
    model = _model(
        costs=costs,
        obs={
            "T": {
                D1: SIG,
                D2: _bar(D2, Decimal("100.2"), Decimal("100.4"), Decimal("101"), Decimal("99.99")),
                D3: _bar(D3, Decimal("101"), Decimal("100.5"), Decimal("101.5"), Decimal("100.5")),
                D4: _bar(D4, Decimal("101.2"), Decimal("101"), Decimal("101.6"), Decimal("101")),
            }
        },
    )
    queue = PendingQueue(model)
    queue.submit(_limit_order(model))
    assert queue.process_session(D2) == []
    assert queue.process_session(D3) == []
    assert queue.process_session(D4) == []
    assert len(queue.cancellations) == 1
    assert queue.pending() == []


def test_realized_pnl_is_net_of_all_costs():
    model = _model()
    order = Order(
        instrument="T",
        side=OrderSide.SELL,
        quantity=Decimal("1000"),
        signal_session=D1,
        ref_price=Decimal("100"),
        order_type=OrderType.MARKET,
    )
    fill = model.attempt_fill(order, D2)
    assert fill is not None
    gross = (fill.price - Decimal("100")) * Decimal("1000")
    assert fill.realized_pnl() == gross - fill.total_cost


def test_close_only_source_uses_next_close():
    model = _model(obs={"T": {D1: SIG, D2: _bar(D2, Decimal("100.9"))}})
    order = Order.from_signal(
        instrument="T",
        side=OrderSide.SELL,
        quantity=Decimal("100"),
        signal_session=D1,
        ref_price=Decimal("100"),
        costs=model.costs,
    )
    fill = model.attempt_fill(order, D2)
    assert fill is not None
    assert fill.price < Decimal("100.9")
