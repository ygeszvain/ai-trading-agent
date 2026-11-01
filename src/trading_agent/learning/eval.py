"""Legacy fold diagnostics. Canonical bounded research lives in workflow.py.

Evaluation never creates a champion or grants activation authority.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from ..backtest.engine import (
    BookSettings,
    CloseSeries,
    momentum_over_window,
    run_single_book,
)
from ..config.models import BacktestCostSettings, PaperSettings
from .challenger import Challenger
from .labels import LearningError
from .memory import Champion

_BPS = Decimal("10000")
_DEFAULT_FEE_RATE = Decimal("0.0005")  # 5 bps of traded notional
_DEFAULT_SLIPPAGE_RATE = Decimal("0.0015")  # 15 bps of traded notional
_CASH_YIELD = Decimal("0.02")


@dataclass(frozen=True)
class LearningGates:
    """Promotion gates.  All bounds are inclusive; ``None`` disables a gate."""

    max_drawdown_bps: Decimal | None = Decimal("1500")
    decision_hit_rate_min: Decimal | None = Decimal("0.5")
    cost_bps_max: Decimal | None = Decimal("20")
    min_trades: int | None = 5
    fold_min: int = 3

    @classmethod
    def from_settings(cls, settings: Any) -> LearningGates:
        # The v1 configuration contract carries no gate thresholds; the
        # code defaults (above) apply and every gate stays enforced.
        return LearningGates()


def gates_from_config(settings: Any) -> LearningGates:
    """Gate defaults from the top-level config object (fail-closed on garbage)."""
    gates = LearningGates.from_settings(settings)
    if gates.max_drawdown_bps is not None and gates.max_drawdown_bps < 0:
        raise LearningError("max_drawdown_bps must be >= 0")
    if gates.decision_hit_rate_min is not None and not (
        Decimal("0") <= gates.decision_hit_rate_min <= Decimal("1")
    ):
        raise LearningError("decision_hit_rate_min must be in [0, 1]")
    if gates.cost_bps_max is not None and gates.cost_bps_max < 0:
        raise LearningError("cost_bps_max must be >= 0")
    if gates.min_trades is not None and gates.min_trades < 1:
        raise LearningError("min_trades must be >= 1")
    if gates.fold_min < 1:
        raise LearningError("fold_min must be >= 1")
    return gates


@dataclass(frozen=True)
class ChallengerDecision:
    session: date
    decision_id: str
    action: str
    target_weight: Decimal


@dataclass(frozen=True)
class FoldResult:
    fold_index: int
    start: date
    end: date
    final_equity: Decimal
    total_return: Decimal
    max_drawdown: Decimal
    n_fills: int
    cost_paid: Decimal
    n_decisions: int
    hit_rate: Decimal | None
    gates_ok: bool
    gate_reasons: tuple[str, ...] = ()
    initial_equity: Decimal = Decimal("100000")

    @property
    def fill_count(self) -> int:
        return self.n_fills

    @property
    def traded(self) -> bool:
        return self.n_fills > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "fold_index": self.fold_index,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "final_equity": str(self.final_equity),
            "total_return": str(self.total_return),
            "max_drawdown": str(self.max_drawdown),
            "n_fills": self.n_fills,
            "cost_paid": str(self.cost_paid),
            "n_decisions": self.n_decisions,
            "hit_rate": str(self.hit_rate) if self.hit_rate is not None else None,
            "gates_ok": self.gates_ok,
            "gate_reasons": list(self.gate_reasons),
        }


@dataclass(frozen=True)
class EvaluationReport:
    evaluation_id: str
    challenger_id: str
    rule_digest: str
    seed: int
    folds: tuple[FoldResult, ...]
    gates_passed: bool
    gate_reasons: tuple[str, ...]
    champion: Champion | None
    new_challenger: Challenger | None
    created_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluation_id": self.evaluation_id,
            "challenger_id": self.challenger_id,
            "rule_digest": self.rule_digest,
            "seed": self.seed,
            "folds": [fold.to_dict() for fold in self.folds],
            "gates_passed": self.gates_passed,
            "gate_reasons": list(self.gate_reasons),
            "champion": self.champion.to_dict() if self.champion else None,
            "new_challenger": self.new_challenger.to_dict() if self.new_challenger else None,
            "created_at": self.created_at.isoformat(),
        }


def _cost_rates(cost: BacktestCostSettings | None) -> tuple[Decimal, Decimal]:
    fee_rate = cost.fee_rate if cost is not None else _DEFAULT_FEE_RATE
    slippage_rate = cost.slippage_rate if cost is not None else _DEFAULT_SLIPPAGE_RATE
    return fee_rate, slippage_rate


def _fold_sessions(dates: Sequence[date], fold_size: int) -> list[list[date]]:
    if fold_size < 1:
        raise LearningError("fold_size must be >= 1")
    return [list(dates[i : i + fold_size]) for i in range(0, len(dates), fold_size)]


def _evaluate_fold(
    challenger: Challenger,
    fold: CloseSeries,
    fold_index: int,
    *,
    gates: LearningGates,
    fee_rate: Decimal,
    slippage_rate: Decimal,
    initial_capital: Decimal,
) -> FoldResult:
    sessions = fold.dates()
    rule = challenger.rule
    if len(sessions) < rule.lookback + 2:
        raise LearningError(
            f"fold {fold_index} has {len(sessions)} sessions; needs at least {rule.lookback + 2}"
        )
    settings = BookSettings(
        initial_cash=initial_capital,
        cash_yield_annual=_CASH_YIELD,
        cost=BacktestCostSettings(fee_rate=fee_rate, slippage_rate=slippage_rate),
        target_weight=rule.target_weight,
    )
    result = run_single_book(
        fold, list(sessions), rule, settings, instrument_id=challenger.instrument
    )
    total_return = result.metrics.get("total_return", Decimal("0"))
    max_drawdown = result.metrics.get("max_drawdown", Decimal("0"))
    if not isinstance(total_return, Decimal):
        total_return = Decimal(str(total_return))
    if not isinstance(max_drawdown, Decimal):
        max_drawdown = Decimal(str(max_drawdown))

    # Decision-level gate material: entry signals the rule would have taken.
    decisions: list[tuple[date, Decimal]] = []
    for position, session in enumerate(sessions):
        if position < rule.lookback:
            continue
        momentum = momentum_over_window(fold.up_to(session, rule.lookback + 1), rule.lookback)
        if momentum is None:
            continue
        decisions.append((session, momentum))
    entry_sessions = [
        (session, momentum) for session, momentum in decisions if momentum >= rule.entry_momentum
    ]
    known = 0
    hits = 0
    closes = {session: mark for session, mark in ((s, fold.value_on(s)) for s in sessions) if mark}
    for session, _momentum in entry_sessions:
        entry_price = closes.get(session)
        if entry_price is None or entry_price <= 0:
            continue
        future = [
            closes[future_session]
            for future_session in sessions
            if future_session > session and closes.get(future_session) is not None
        ][:1]
        if not future:
            continue
        known += 1
        if future[0] > entry_price:
            hits += 1
    hit_rate = Decimal(hits) / Decimal(known) if known else None

    reasons: list[str] = []
    drawdown_bps = max_drawdown * _BPS
    if gates.max_drawdown_bps is not None and drawdown_bps > gates.max_drawdown_bps:
        reasons.append(
            f"max_drawdown {drawdown_bps.quantize(Decimal('1'))}bps > {gates.max_drawdown_bps}bps"
        )
    if gates.min_trades is not None and len(result.fills) < gates.min_trades:
        reasons.append(f"fills {len(result.fills)} < min_trades {gates.min_trades}")
    equity_base = result.final_equity + result.cost_paid
    cost_bps = (result.cost_paid / equity_base * _BPS) if equity_base > 0 else Decimal("0")
    if gates.cost_bps_max is not None and cost_bps > gates.cost_bps_max:
        reasons.append(f"cost {cost_bps.quantize(Decimal('1'))}bps > {gates.cost_bps_max}bps")
    if (
        gates.decision_hit_rate_min is not None
        and hit_rate is not None
        and hit_rate < gates.decision_hit_rate_min
    ):
        reasons.append(
            f"hit_rate {hit_rate.quantize(Decimal('0.001'))} < {gates.decision_hit_rate_min}"
        )

    return FoldResult(
        fold_index=fold_index,
        start=sessions[0],
        end=sessions[-1],
        initial_equity=initial_capital,
        final_equity=result.final_equity,
        total_return=total_return,
        max_drawdown=max_drawdown,
        n_fills=len(result.fills),
        cost_paid=result.cost_paid,
        n_decisions=len(entry_sessions),
        hit_rate=hit_rate,
        gates_ok=not reasons,
        gate_reasons=tuple(reasons),
    )


def evaluate_challenger(
    challenger: Challenger,
    series: CloseSeries,
    folds: Sequence[CloseSeries] = (),
    gates: LearningGates | None = None,
    *,
    seed: int = 0,
    cost: BacktestCostSettings | None = None,
    paper: PaperSettings | None = None,
    fold_size: int | None = None,
) -> EvaluationReport:
    """Evaluate a challenger over in-sample series + out-of-sample folds.

    ``fold_size`` partitions every series into consecutive equal folds; when
    omitted, each series is one diagnostic fold. Passing gates never grants
    promotion. Use workflow.run_experiment for chronological bounded evaluation.
    """
    gates = gates or LearningGates()
    if not isinstance(seed, int) or seed < 0 or seed >= 2**32:
        raise LearningError("seed must be an int in [0, 2**32)")
    series_list = [series, *folds]
    if len(series_list) < gates.fold_min and fold_size is None:
        raise LearningError(
            f"need at least {gates.fold_min} folds; got {len(series_list)} "
            "(pass fold_size to partition)"
        )
    fee_rate, slippage_rate = _cost_rates(cost)
    initial_capital = (
        paper.initial_cash_usd if paper is not None else PaperSettings().initial_cash_usd
    )

    partitioned: list[CloseSeries] = []
    for source in series_list:
        dates = source.dates()
        if fold_size is None:
            partitioned.append(source)
        else:
            for chunk in _fold_sessions(dates, fold_size):
                partitioned.append(
                    CloseSeries([(s, v) for s in chunk if (v := source.value_on(s)) is not None])
                )

    fold_results = [
        _evaluate_fold(
            challenger,
            fold,
            index,
            gates=gates,
            fee_rate=fee_rate,
            slippage_rate=slippage_rate,
            initial_capital=initial_capital,
        )
        for index, fold in enumerate(partitioned)
    ]
    if len(fold_results) < gates.fold_min:
        raise LearningError(f"need at least {gates.fold_min} folds; got {len(fold_results)}")

    gate_reasons = tuple(
        f"fold {fold.fold_index}: {reason}" for fold in fold_results for reason in fold.gate_reasons
    )
    gates_passed = not gate_reasons

    # Evaluation only supplies evidence; even a passing shadow candidate cannot
    # create or replace a champion. Activation is outside this research module.
    champion: Champion | None = None
    new_challenger: Challenger | None = challenger

    now = datetime.now(UTC)
    payload = {
        "challenger_id": challenger.challenger_id,
        "rule_digest": challenger.rule_digest,
        "seed": seed,
        "folds": [fold.to_dict() for fold in fold_results],
        "champion": champion.to_dict() if champion else None,
        "now": now.isoformat(),
    }
    evaluation_id = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:24]

    return EvaluationReport(
        evaluation_id=evaluation_id,
        challenger_id=challenger.challenger_id,
        rule_digest=challenger.rule_digest,
        seed=seed,
        folds=tuple(fold_results),
        gates_passed=gates_passed,
        gate_reasons=gate_reasons,
        champion=champion,
        new_challenger=new_challenger,
        created_at=now,
    )


__all__ = [
    "ChallengerDecision",
    "EvaluationReport",
    "FoldResult",
    "LearningGates",
    "evaluate_challenger",
    "gates_from_config",
]
