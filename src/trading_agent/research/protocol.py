"""Versioned economic-edge evaluation protocol (Prompt 6, M3).

A protocol registers, BEFORE any selection happens, everything that decides
the verdict: hypothesis, scope, parameter grid, walk-forward splits, compute
budget, objective, benchmarks, risk constraints, and rejection criteria.

An ``EvalProtocol`` is immutable and carries a content digest. The evaluation
runner must quote that digest in its report, and any criterion changed after
results are visible requires a new protocol version — never a silent edit.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, fields
from decimal import Decimal
from enum import StrEnum

from ..exceptions import ConfigError


class EvalVerdict(StrEnum):
    """The three verdicts a reproducible report may recommend."""

    CONTINUE_RESEARCH = "continue_research"
    PAPER_TEST = "paper_test"
    REJECT = "reject"

    @property
    def rank(self) -> int:
        return _VERDICT_RANK[self]


_VERDICT_RANK = {
    EvalVerdict.CONTINUE_RESEARCH: 0,
    EvalVerdict.PAPER_TEST: 1,
    EvalVerdict.REJECT: 2,
}


@dataclass(frozen=True)
class EvalProtocol:
    """One registered, versioned economic-edge evaluation protocol."""

    protocol_version: str
    hypothesis: str
    strategy: str
    # Parameter grid (registered before selection; never widened after).
    lookback_candidates: tuple[int, ...]
    entry_candidates: tuple[Decimal, ...]
    exit_candidates: tuple[Decimal, ...]
    fit_score: str  # "sharpe" | "cagr"
    # Splits and budget.
    fold_days: int
    min_train_days: int
    max_folds: int
    max_grid_runs: int
    min_sample_sessions: int
    # Objective and benchmarks (same starting capital per fold).
    objective: str
    benchmarks: tuple[str, ...]
    # Risk constraints and rejection criteria (registered before results).
    max_drawdown_tolerance: Decimal
    min_positive_fold_share: Decimal
    min_robust_stable_share: Decimal
    paper_min_mean_edge: Decimal
    reject_max_mean_edge: Decimal

    def grid_size(self) -> int:
        return (
            len(self.lookback_candidates) * len(self.entry_candidates) * len(self.exit_candidates)
        )

    def validate(self) -> None:
        violations: list[str] = []
        if not self.hypothesis.strip():
            violations.append("hypothesis is empty")
        if not self.lookback_candidates or any(
            lookback < 2 for lookback in self.lookback_candidates
        ):
            violations.append("lookback_candidates must be non-empty and >= 2")
        if not self.entry_candidates or not self.exit_candidates:
            violations.append("entry/exit candidate grids must be non-empty")
        if self.fold_days < 10 or self.min_train_days < 10:
            violations.append("fold_days and min_train_days must be >= 10")
        if self.max_folds < 1 or self.max_grid_runs < 1:
            violations.append("max_folds / max_grid_runs must be >= 1")
        if self.max_folds * self.grid_size() > self.max_grid_runs:
            violations.append(
                f"budget: max_folds*grid ({self.max_folds} x {self.grid_size()}) exceeds "
                f"max_grid_runs {self.max_grid_runs}"
            )
        if self.min_sample_sessions < 10:
            violations.append("min_sample_sessions must be >= 10")
        if not (Decimal("-1") <= self.max_drawdown_tolerance <= Decimal("1")):
            violations.append("max_drawdown_tolerance must be within [-1, 1]")
        if not (Decimal("0") <= self.min_positive_fold_share <= Decimal("1")):
            violations.append("min_positive_fold_share must be within [0, 1]")
        if not (Decimal("0") <= self.min_robust_stable_share <= Decimal("1")):
            violations.append("min_robust_stable_share must be within [0, 1]")
        if self.reject_max_mean_edge > self.paper_min_mean_edge:
            violations.append("reject_max_mean_edge must not exceed paper_min_mean_edge")
        if self.fit_score not in ("sharpe", "cagr"):
            violations.append("fit_score must be 'sharpe' or 'cagr'")
        if self.objective != "cost_adjusted_edge_vs_passive":
            violations.append("objective must be 'cost_adjusted_edge_vs_passive' (v1)")
        if "passive" not in self.benchmarks or "cash" not in self.benchmarks:
            violations.append("benchmarks must include 'passive' and 'cash'")
        if violations:
            raise ConfigError(violations)

    def digest(self) -> str:
        payload = json.dumps(
            {
                name: value
                for name, value in (
                    (
                        field.name,
                        [str(v) for v in value]
                        if isinstance(value, tuple)
                        else value
                        if isinstance(value, (int, str, type(None)))
                        else str(value),
                    )
                    for field in fields(self)
                    for value in [getattr(self, field.name)]
                )
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def standard_protocol() -> EvalProtocol:
    """The registered v1.0 default protocol for momentum_v1 (Prompt 6).

    Thresholds are conservative on purpose: a strategy that cannot clear a
    cost-adjusted, benchmark-relative edge across most out-of-sample folds
    does not merit prospective testing, and noisy edges stay in research.
    """
    return EvalProtocol(
        protocol_version="1.0",
        hypothesis=(
            "A long-only, close-decided momentum rule retains a cost-adjusted edge versus "
            "buy-and-hold on the eligible instrument, measured on out-of-sample "
            "walk-forward folds."
        ),
        strategy="momentum_v1",
        lookback_candidates=(10, 20, 40),
        entry_candidates=(Decimal("0.01"), Decimal("0.02"), Decimal("0.04")),
        exit_candidates=(Decimal("-0.01"), Decimal("0.00"), Decimal("0.01")),
        fit_score="sharpe",
        fold_days=126,
        min_train_days=126,
        max_folds=8,
        max_grid_runs=648,
        min_sample_sessions=260,
        objective="cost_adjusted_edge_vs_passive",
        benchmarks=("cash", "passive"),
        max_drawdown_tolerance=Decimal("0.35"),
        min_positive_fold_share=Decimal("0.50"),
        min_robust_stable_share=Decimal("0.75"),
        paper_min_mean_edge=Decimal("0.005"),
        reject_max_mean_edge=Decimal("-0.01"),
    )
