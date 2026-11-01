"""Tests for the decision-record ledger and offline outcome labeling."""

from datetime import date, timedelta
from decimal import Decimal

from trading_agent.backtest.engine import CloseSeries
from trading_agent.learning import DecisionRecord, mature_labels


def uptrend_series(days: int = 30, step: str = "0.5", start: str = "100") -> CloseSeries:
    origin = date(2025, 1, 6)
    prices = [Decimal(start) + Decimal(step) * index for index in range(days)]
    return CloseSeries(
        list(zip((origin + timedelta(days=i) for i in range(days)), prices, strict=True))
    )


def record(session: date | None = None) -> DecisionRecord:
    return DecisionRecord(
        decision_id="d1",
        run_id="run1",
        account_alias="acct",
        mode="backtest",
        instrument_id="SPX",
        decision_session=session or date(2025, 1, 6),
        action="enter",
        target_weight=Decimal("1"),
        strategy_version="v1",
        model_version=None,
        data_snapshot_id="snap1",
        risk_policy_version="rp1",
    )


def test_record_dict_roundtrip():
    raw = record().to_dict()
    assert raw["instrument_id"] == "SPX"
    assert raw["decision_session"] == "2025-01-06"
    restored = DecisionRecord.from_dict(raw)
    assert restored.to_dict() == raw


def test_mature_labels_realizes_forward_return():
    series = uptrend_series()
    labels = mature_labels(
        [record()], {"SPX": series}, as_of=series.dates()[-1], session_calendar=series.dates()
    )
    label = labels["d1"]
    assert label.matured is True
    assert label.to_dict()["horizons"]["1"] == "0.00500000"
    assert label.gapped is False
    assert len(label.label_digest) == 64


def test_unmatured_decision_stays_unmatured():
    series = uptrend_series()
    labels = mature_labels(
        [record()], {"SPX": series}, as_of=series.dates()[0], session_calendar=series.dates()
    )
    assert labels["d1"].matured is False
    assert all(value is None for value in labels["d1"].horizons.values())


def test_label_digest_is_stable():
    series = uptrend_series()
    a = mature_labels(
        [record()], {"SPX": series}, as_of=series.dates()[-1], session_calendar=series.dates()
    )["d1"]
    b = mature_labels(
        [record()], {"SPX": series}, as_of=series.dates()[-1], session_calendar=series.dates()
    )["d1"]
    assert a.label_digest == b.label_digest


def test_explicit_calendar_preserves_missing_target_and_is_required():
    import pytest

    from trading_agent.learning import LearningError

    original = uptrend_series()
    calendar = original.dates()
    gapped = CloseSeries([(d, v) for d, v in original.up_to(calendar[-1]) if d != calendar[1]])
    with pytest.raises(LearningError, match="explicit session calendar"):
        mature_labels([record()], {"SPX": gapped}, as_of=calendar[-1])
    label = mature_labels(
        [record()], {"SPX": gapped}, as_of=calendar[-1], session_calendar=calendar
    )["d1"]
    assert label.horizons[1] is None
    assert label.gapped and not label.matured
