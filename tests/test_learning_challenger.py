"""Tests for the challenger model: validation, digest, serialization."""
from datetime import date
from decimal import Decimal

import pytest

from trading_agent.learning import LearningError
from trading_agent.learning import Challenger


def make_challenger(**overrides) -> Challenger:
    base = dict(
        challenger_id="c1",
        name="mom",
        description="d",
        strategy="trend-momentum",
        lookback=10,
        entry_momentum=Decimal("0.01"),
        exit_momentum=Decimal("-0.01"),
        target_weight=Decimal("1"),
        origin="hand",
        source_dataset_digest=None,
        protocol_digest=None,
        created_at="2025-01-06T00:00:00+00:00",
        status="shadow",
        instrument="SPX",
    )
    base.update(overrides)
    return Challenger(**base)


def test_validation_rejects_entry_below_exit():
    with pytest.raises(LearningError):
        make_challenger(entry_momentum=Decimal("-0.01"), exit_momentum=Decimal("0.01"))


def test_validation_rejects_zero_lookback_and_zero_weight():
    with pytest.raises(LearningError):
        make_challenger(lookback=0)
    with pytest.raises(LearningError):
        make_challenger(target_weight=Decimal("0"))


def test_digest_is_stable_and_content_sensitive():
    a = make_challenger()
    b = make_challenger()
    assert a.digest() == b.digest()
    assert len(a.digest()) == 64
    assert a.digest() != make_challenger(lookback=20).digest()
    assert a.digest() != make_challenger(instrument="ES").digest()


def test_dict_roundtrip_preserves_fields():
    challenger = make_challenger()
    raw = challenger.to_dict()
    assert raw["instrument"] == "SPX"
    assert raw["status"] == "shadow"
    assert Challenger.from_dict(raw) == challenger
