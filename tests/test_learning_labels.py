"""Tests for the decision-record ledger and offline outcome labeling."""
from datetime import date, timedelta
from decimal import Decimal

from trading_agent.backtest.engine import CloseSeries
from trading_agent.learning import DecisionRecord, mature_labels


def uptrend_series(days: int = 30, step: str = "0.5", start: str = "100") -> CloseSeries:
    origin = date(2025, 1, 6)
    prices = [Decimal(start) + Decimal(step) * index for index in range(days)]
    return CloseSeries(list(zip((origin + timedelta(days=i) for i in range(days)), prices)))


def record(session: date | None = None) -> DecisionRecord:
    return DecisionRecord(
        decision_id="d1", run_id="run1", account_id="acct", mode="backtest",
        instrument_id="SPX", session=session or date(2025, 1, 6), action="enter",
        target_weight=Decimal("1"), rule_version="v1", prompt_version=None,
        model_snapshot_id="snap1", rule_protocol_id="rp1",
    )


def test_record_dict_roundtrip():
    raw = record().to_dict()
    assert raw["instrument_id"] == "SPX"
    assert raw["session"] == "2025-01-06"
    restored = DecisionRecord.from_dict(raw)
    assert restored.to_dict() == raw


def test_mature_labels_realizes_forward_return():
    series = uptrend_series()
    labels = mature_labels([record()], {"SPX": series}, as_of=series.dates()[-1])
    label = labels["d1"]
    assert label.matured is True
    assert label.to_dict()["horizons"]["1"] == "0.00500000"
    assert label.gapped is False
    assert len(label.label_digest) == 64


def test_unmatured_decision_stays_unmatured():
    series = uptrend_series()
    labels = mature_labels([record()], {"SPX": series}, as_of=series.dates()[0])
    assert labels["d1"].matured is False
    assert labels["d1"].horizons == {}


def test_label_digest_is_stable():
    series = uptrend_series()
    a = mature_labels([record()], {"SPX": series}, as_of=series.dates()[-1])["d1"]
    b = mature_labels([record()], {"SPX": series}, as_of=series.dates()[-1])["d1"]
    assert a.label_digest == b.label_digest
