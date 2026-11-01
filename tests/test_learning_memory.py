"""Tests for the consolidated decision memory."""

from datetime import date
from decimal import Decimal

from trading_agent.backtest.engine import CloseSeries
from trading_agent.learning import DecisionLabel, DecisionRecord
from trading_agent.learning.memory import from_records


def series() -> CloseSeries:
    return CloseSeries([(date(2025, 1, 6), Decimal("100")), (date(2025, 1, 7), Decimal("100.5"))])


def record() -> DecisionRecord:
    return DecisionRecord(
        decision_id="d1",
        run_id="run1",
        account_alias="acct",
        mode="backtest",
        instrument_id="SPX",
        decision_session=date(2025, 1, 6),
        action="enter",
        target_weight=Decimal("1"),
        strategy_version="v1",
        model_version=None,
        data_snapshot_id="snap1",
        risk_policy_version="rp1",
    )


def test_from_records_builds_entry():
    memory = from_records([record()], None, memory_id="m1")
    assert len(memory) == 1
    entry = memory.get("d1")
    assert entry is not None
    assert entry["action"] == "enter"


def test_upsert_label_overwrites_with_label_fields():
    label = DecisionLabel(
        decision_id="d1",
        instrument_id="SPX",
        action="enter",
        target_weight=Decimal("1"),
        decision_session=date(2025, 1, 6),
        matured=True,
        horizons={1: Decimal("0.005")},
        max_drawdown=Decimal("0"),
        recovered=False,
        gapped=False,
        matured_as_of=date(2025, 1, 7),
    )
    memory = from_records([record()], {"d1": label}, memory_id="m1")
    entry = memory.get("d1")
    assert entry["matured"] is True
    assert entry["label_digest"] == label.label_digest


def test_digest_changes_with_content():
    memory = from_records([record()], None, memory_id="m1")
    first = memory.digest()
    from dataclasses import replace

    memory.upsert_record(replace(record(), decision_id="d2"))
    assert memory.digest() != first


def test_decay_scales_by_age():
    memory = from_records([record()], None, memory_id="m1")
    memory.decay(half_life=Decimal(30), as_of=date(2025, 2, 5))
    assert memory.get("d1")["decay"] < Decimal("1")
