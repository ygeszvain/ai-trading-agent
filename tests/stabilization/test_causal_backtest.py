from datetime import date, timedelta
from decimal import Decimal

from trading_agent.backtest.engine import BookSettings, CloseSeries, MomentumRule, run_single_book
from trading_agent.config.models import BacktestCostSettings


def test_signal_cannot_fill_on_its_own_close_or_capture_that_price_jump():
    days = [date(2026, 1, 5) + timedelta(days=i) for i in range(4)]
    series = CloseSeries(list(zip(days, map(Decimal, ("100", "200", "300", "300")), strict=True)))
    book = BookSettings(
        Decimal(1000),
        Decimal(0),
        BacktestCostSettings(fee_rate=Decimal(0), slippage_rate=Decimal(0)),
        Decimal(1),
    )
    result = run_single_book(
        series,
        days,
        MomentumRule(1, Decimal(".1"), Decimal(0), Decimal(1)),
        book,
        instrument_id="MOCK",
    )
    assert result.fills[0][0] == days[2] and result.fills[0][2] == 300
    assert result.curve[1][1] == 1000 and result.final_equity <= 1000


def test_missing_execution_bar_expires_pending_order_without_backdating():
    days = [date(2026, 1, 5) + timedelta(days=i) for i in range(3)]
    series = CloseSeries([(days[0], Decimal(100)), (days[1], Decimal(200))])
    book = BookSettings(Decimal(1000), Decimal(0), BacktestCostSettings(), Decimal(1))
    result = run_single_book(
        series,
        days,
        MomentumRule(1, Decimal(".1"), Decimal(0), Decimal(1)),
        book,
        instrument_id="MOCK",
    )
    assert not result.fills and result.data_gaps == 1


def test_whole_share_feasibility_cannot_use_implicit_fractional_quantities():
    from dataclasses import replace

    days = [date(2026, 1, 5) + timedelta(days=i) for i in range(4)]
    series = CloseSeries([(day, Decimal(100) + i) for i, day in enumerate(days)])
    book = BookSettings(
        Decimal(500), Decimal(0), BacktestCostSettings(), Decimal(".01"), Decimal(1)
    )
    rule = MomentumRule(1, Decimal(0), Decimal(0), Decimal(".01"))
    whole = run_single_book(series, days, rule, book, instrument_id="MOCK")
    fractional = run_single_book(
        series, days, rule, replace(book, quantity_step=Decimal(".00000001")), instrument_id="MOCK"
    )
    assert not whole.fills and fractional.fills


def test_first_observation_cost_is_a_loss_and_calendar_span_sets_annualization():
    from trading_agent.backtest.engine import compute_metrics

    start = date(2026, 1, 1)
    fee_only = compute_metrics([(start, Decimal(98))], Decimal(100))
    assert fee_only["total_return"] == Decimal("-.020000")
    assert fee_only["max_drawdown"] == Decimal(".020000")
    annual = compute_metrics(
        [(start, Decimal(100)), (start + timedelta(days=364), Decimal(110))], Decimal(100)
    )
    assert Decimal(".099") < annual["cagr"] < Decimal(".101")
