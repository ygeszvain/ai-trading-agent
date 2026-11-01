"""Registered evaluation protocol: validation, versioning, digest stability (M3 prompt 1)."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from trading_agent.exceptions import ConfigError
from trading_agent.research.protocol import EvalVerdict, standard_protocol


def test_standard_protocol_is_valid_and_sealed() -> None:
    protocol = standard_protocol()
    protocol.validate()
    assert protocol.protocol_version == "1.0"
    assert protocol.objective == "cost_adjusted_edge_vs_passive"
    assert set(protocol.benchmarks) == {"cash", "passive"}
    assert protocol.fit_score in {"sharpe", "cagr"}
    # The reject zone must sit strictly below the paper threshold.
    assert protocol.reject_max_mean_edge < protocol.paper_min_mean_edge


def test_digest_is_stable_and_sensitive() -> None:
    assert standard_protocol().digest() == standard_protocol().digest()
    assert len(standard_protocol().digest()) == 32
    assert standard_protocol().digest() != replace(standard_protocol(), fold_days=100).digest()
    assert (
        standard_protocol().digest()
        != replace(standard_protocol(), paper_min_mean_edge=Decimal("0.01")).digest()
    )


def test_verdict_ranking_orders_the_decision_ladder() -> None:
    assert (
        EvalVerdict.CONTINUE_RESEARCH.rank < EvalVerdict.PAPER_TEST.rank < EvalVerdict.REJECT.rank
    )


@pytest.mark.parametrize(
    "overrides",
    [
        # Reject zone must never cross the paper threshold.
        {"paper_min_mean_edge": Decimal("0.01"), "reject_max_mean_edge": Decimal("0.02")},
        # Degenerate splits.
        {"fold_days": 5},
        {"min_train_days": 5},
        # Shares must stay within [0, 1].
        {"min_positive_fold_share": Decimal("1.5")},
        {"min_robust_stable_share": Decimal("-0.2")},
        # Drawdown tolerance is bounded.
        {"max_drawdown_tolerance": Decimal("1.5")},
        # Unknown objective or fit score.
        {"fit_score": "returns"},
        {"objective": "maximize_returns"},
        # Both required benchmarks must be named.
        {"benchmarks": ("cash",)},
        # Grid must fit the registered compute budget.
        {"max_folds": 100},
        # Lookback candidates need at least 2 sessions.
        {"lookback_candidates": (1, 10)},
    ],
)
def test_invalid_protocols_are_rejected(overrides: dict) -> None:
    with pytest.raises(ConfigError):
        replace(standard_protocol(), **overrides).validate()
