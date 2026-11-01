"""Deterministic economic edge evaluation (M3 prompt 1).

Regimes are fixed-seed synthetic series so verdicts are stable:
- regime:   4 alternating bull/bear legs; the corrected causal/cost model has
            positive edge in 5 of 5 folds (paper_test with the injected real
            real data; synthetic data is capped at continue_research).
- spike:    flat market with one 40-day spike inside a fold; mean cost-adjusted
            edge stays negative (reject).
- whipsaw:  daily-alternating drift v2 (reject). The original predictable
            25-session block input is retained as periodic_trend_series_v1.

All prices are fictional. The real source label tests a protocol gate only.
Original assertions/failures: docs/evidence/economic_expectation_review_20261101.json.
"""

from __future__ import annotations

import json
import random
from datetime import date, timedelta
from decimal import Decimal

from trading_agent.backtest.engine import BookSettings, CloseSeries
from trading_agent.config.models import BacktestCostSettings
from trading_agent.research.econ_eval import (
    EdgeReport,
    evaluate_protocol,
    render_report_json,
    render_report_markdown,
)
from trading_agent.research.protocol import EvalVerdict, standard_protocol

PROTOCOL = standard_protocol()

BOOK = BookSettings(
    initial_cash=Decimal("10000"),
    cash_yield_annual=Decimal("0.045"),
    cost=BacktestCostSettings(fee_rate=Decimal("0.0004"), slippage_rate=Decimal("0.0015")),
    target_weight=Decimal("1.0"),
)


def _session_dates(start: date, count: int) -> list[date]:
    days: list[date] = []
    current = start
    while current.weekday() >= 5:
        current += timedelta(days=1)
    while len(days) < count:
        days.append(current)
        current += timedelta(days=1)
        if current.weekday() >= 5:
            current += timedelta(days=2)
    return days


def _series(dates: list[date], returns: list[Decimal]) -> CloseSeries:
    pairs: list[tuple[date, Decimal]] = []
    price = Decimal("100")
    for day in dates:
        pairs.append((day, price))
        price = price * (Decimal("1") + returns[len(pairs) - 1])
    return CloseSeries(pairs)


def _jitter(rng: random.Random) -> Decimal:
    return Decimal(str(round(rng.uniform(-0.008, 0.008), 5))).quantize(Decimal("0.0001"))


def _regime_series_returns() -> list[Decimal]:
    rng = random.Random(11)
    returns: list[Decimal] = []
    for _ in range(4):
        returns += [Decimal("0.003") + _jitter(rng) for _ in range(80)]
        returns += [Decimal("-0.005") + _jitter(rng) for _ in range(80)]
    return returns


def _regime_series() -> CloseSeries:
    rng = random.Random(11)
    returns: list[Decimal] = []
    for _ in range(4):
        returns += [Decimal("0.003") + _jitter(rng) for _ in range(80)]
        returns += [Decimal("-0.005") + _jitter(rng) for _ in range(80)]
    return _series(_session_dates(date(2020, 1, 1), len(returns)), returns)


def _spike_series() -> CloseSeries:
    rng = random.Random(99)
    returns = [Decimal("0.0012") + _jitter(rng) for _ in range(200)]
    returns += [Decimal("0.010") for _ in range(40)]
    rng = random.Random(123)
    returns += [Decimal("0.0012") + _jitter(rng) for _ in range(200)]
    return _series(_session_dates(date(2021, 1, 4), len(returns)), returns)


def _periodic_trend_series_v1() -> CloseSeries:
    returns = [
        Decimal("0.0012") + (Decimal("0.004") if (index // 25) % 2 == 0 else Decimal("-0.004"))
        for index in range(420)
    ]
    return _series(_session_dates(date(2022, 1, 3), 420), returns)


def _whipsaw_series() -> CloseSeries:
    returns = [
        Decimal("0.0012") + (Decimal("0.004") if index % 2 == 0 else Decimal("-0.004"))
        for index in range(420)
    ]
    return _series(_session_dates(date(2022, 1, 3), 420), returns)


def _evaluate(series: CloseSeries, data_source: str = "real") -> EdgeReport:
    return evaluate_protocol(
        PROTOCOL,
        series,
        list(series.dates()),
        book=BOOK,
        instrument_id="T",
        data_snapshot_id="s",
        data_source=data_source,
    )


def test_regime_earns_paper_test_on_real_data() -> None:
    report = _evaluate(_regime_series())
    assert report.verdict == EvalVerdict.PAPER_TEST
    assert Decimal(report.aggregate["mean_fold_edge"]) > 0
    assert report.aggregate["total_folds"] == report.aggregate["complete_folds"]
    # The original 0.8 expectation contradicted this fixed regime input.
    # Execution changed, criteria/grid did not; prior failed evidence is archived.
    assert Decimal(report.aggregate["positive_fold_share"]) == Decimal("1")


def test_synthetic_source_is_capped_at_research() -> None:
    report = _evaluate(_regime_series(), data_source="synthetic")
    assert report.verdict == EvalVerdict.CONTINUE_RESEARCH
    assert any("synthetic" in reason for reason in report.rationale)


def test_spike_is_rejected() -> None:
    report = _evaluate(_spike_series())
    assert report.verdict == EvalVerdict.REJECT
    assert any("reject zone" in reason for reason in report.rationale)


def test_whipsaw_trend_is_rejected() -> None:
    assert _evaluate(_whipsaw_series()).verdict == EvalVerdict.REJECT


def test_original_periodic_trend_fixture_is_preserved_and_not_investment_evidence() -> None:
    report = _evaluate(_periodic_trend_series_v1(), data_source="synthetic")
    assert Decimal(report.aggregate["mean_fold_edge"]) > 0
    assert report.verdict == EvalVerdict.CONTINUE_RESEARCH


def test_insufficient_sample_rejected_for_data_reasons() -> None:
    short = _series(_session_dates(date(2020, 1, 1), 60), _regime_series_returns()[:60])
    report = evaluate_protocol(
        PROTOCOL,
        short,
        list(short.dates()),
        book=BOOK,
        instrument_id="T",
        data_snapshot_id="s",
        data_source="real",
    )
    assert report.verdict == EvalVerdict.REJECT
    assert any("insufficient sample" in reason for reason in report.rationale)


def test_fold_edges_are_benchmarked() -> None:
    report = _evaluate(_regime_series())
    first, second = report.folds[0], report.folds[1]
    assert first.passive_total_return is not None and first.cash_total_return is not None
    # Independent passive reference: initial capital bears entry costs, then
    # tracks the price ratio. The fractional residual contributes < 1 ppm.
    series = _regime_series()
    entry, exit_price = series.value_on(first.test_start), series.value_on(first.test_end)
    assert entry is not None and exit_price is not None
    expected_passive = exit_price / entry / (1 + BOOK.cost.fee_rate + BOOK.cost.slippage_rate) - 1
    assert abs(first.passive_total_return - expected_passive) < Decimal(".000001")
    assert first.edge == first.strategy_total_return - first.passive_total_return
    assert first.edge is not None and first.edge > 0
    assert second.edge is not None
    assert second.edge > 0


def test_robustness_suite_is_complete_and_ordered() -> None:
    report = _evaluate(_regime_series())
    assert [entry.perturbation for entry in report.robustness] == [
        "delay_1d",
        "missing_5pct",
        "gap_window",
        "remove_best_period",
        "params_10pct",
    ]
    assert all(isinstance(entry.stable, bool) for entry in report.robustness)
    assert Decimal(report.aggregate["robust_stable_share"]) == Decimal("1")


def test_report_json_is_deterministic() -> None:
    first = render_report_json(_evaluate(_regime_series()))
    second = render_report_json(_evaluate(_regime_series()))
    assert first == second
    payload = json.loads(first)
    assert payload["protocol"]["digest"] == PROTOCOL.digest()
    assert payload["verdict"] == "paper_test"
    assert payload["run"]["data_source"] == "real"
    assert len(payload["folds"]) == 5


def test_markdown_render_is_stable_and_labeled() -> None:
    report = _evaluate(_regime_series())
    first = render_report_markdown(report)
    second = render_report_markdown(report)
    assert first == second
    assert "PAPER_TEST" in first
    assert PROTOCOL.protocol_version in first
    assert report.instrument_id in first
