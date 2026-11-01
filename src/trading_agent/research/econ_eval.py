"""Economic-edge evaluation over a registered protocol (Prompt 6, M3).

Runs an ``EvalProtocol`` against a point-in-time close series and produces a
reproducible verdict report — CONTINUE_RESEARCH, PAPER_TEST, or REJECT —
covering chronological walk-forward folds, a registered robustness suite
(delayed data, missing data, gaps, parameter shifts, and removal of the best
sub-period), a cost/capital break-even view, and benchmark-relative
performance.

Boundaries: no live actions, no automatic capital changes, no paid data.
Selection happens strictly on data before each fold's test window, and the
report quotes the protocol digest so any post-result criterion change is
auditable. Negative findings are valid: REJECT is a normal, honest outcome.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

from .. import __version__
from ..backtest.engine import (
    EXECUTION_VERSION,
    BookSettings,
    CloseSeries,
    MomentumRule,
    compute_metrics,
    run_cash_benchmark,
    run_passive_benchmark,
    run_single_book,
)
from ..money import round_money
from .protocol import EvalProtocol, EvalVerdict

_QUANT = Decimal("0.000001")


def _q(value: Decimal) -> Decimal:
    return value.quantize(_QUANT)


@dataclass(frozen=True)
class FoldOutcome:
    """One walk-forward fold: fit on strictly earlier sessions, test on the fold."""

    fold_index: int
    train_sessions: int
    test_start: date
    test_end: date
    test_sessions: int
    rule_digest: str
    rule_description: str
    fitted: bool
    strategy_total_return: Decimal
    passive_total_return: Decimal
    cash_total_return: Decimal
    edge: Decimal | None
    strategy_max_drawdown: Decimal
    cost_paid: Decimal
    data_gaps: int
    fills: int


@dataclass(frozen=True)
class RobustnessOutcome:
    perturbation: str
    detail: str
    verdict: str
    stable: bool


@dataclass(frozen=True)
class EdgeReport:
    protocol_digest: str
    protocol_version: str
    run_id: str
    code_version: str
    data_snapshot_id: str
    data_source: str
    instrument_id: str
    verdict: EvalVerdict
    rationale: tuple[str, ...]
    folds: tuple[FoldOutcome, ...]
    robustness: tuple[RobustnessOutcome, ...]
    aggregate: dict[str, str]
    cost_view: dict[str, str]
    sample: dict[str, str | int]
    limitations: tuple[str, ...]
    artifacts: dict[str, str] = field(default_factory=dict)


def _build_grid(protocol: EvalProtocol, target_weight: Decimal) -> list[MomentumRule]:
    grid: list[MomentumRule] = []
    for lookback in sorted(set(protocol.lookback_candidates)):
        for entry in protocol.entry_candidates:
            for exit_momentum in protocol.exit_candidates:
                grid.append(
                    MomentumRule(
                        lookback=lookback,
                        entry_momentum=entry,
                        exit_momentum=exit_momentum,
                        target_weight=target_weight,
                    )
                )
    return grid


def _fold_sessions(sessions: list[date], fold_days: int, max_folds: int) -> list[list[date]]:
    folds: list[list[date]] = []
    index = fold_days
    while index < len(sessions) and len(folds) < max_folds:
        folds.append(sessions[index : index + fold_days])
        index += fold_days
    return folds


def _fit_rule(
    grid: list[MomentumRule],
    series: CloseSeries,
    train_sessions: list[date],
    book: BookSettings,
    instrument_id: str,
    score_name: str,
    budget: dict[str, int],
) -> tuple[MomentumRule, Decimal]:
    best_rule = grid[0]
    best_score = Decimal("-Infinity")
    for rule in grid:
        if budget["remaining"] <= 0:
            raise RuntimeError(
                f"grid budget exhausted after {budget['spent']} runs; raise the protocol "
                f"budget or narrow the grid"
            )
        budget["spent"] += 1
        budget["remaining"] -= 1
        run = run_single_book(series, train_sessions, rule, book, instrument_id=instrument_id)
        score = Decimal(str(run.metrics.get(score_name, Decimal("0"))))
        if score > best_score:
            best_rule, best_score = rule, score
    return best_rule, best_score


def _fold_outcome(
    protocol: EvalProtocol,
    series: CloseSeries,
    sessions: list[date],
    fold: list[date],
    book: BookSettings,
    instrument_id: str,
    grid: list[MomentumRule],
    budget: dict[str, int],
    fold_index: int,
) -> FoldOutcome:
    train_sessions = [s for s in sessions if s < fold[0]]
    if len(train_sessions) < protocol.min_train_days:
        rule, _ = grid[0], Decimal("-Infinity")
        fitted = False
    else:
        rule, _ = _fit_rule(
            grid, series, train_sessions, book, instrument_id, protocol.fit_score, budget
        )
        fitted = True
    strategy = run_single_book(series, fold, rule, book, instrument_id=instrument_id)
    budget["spent"] += 1
    budget["remaining"] -= 1
    if budget["remaining"] < 0:
        raise RuntimeError("grid budget exceeded during test folds; widen the protocol budget")
    passive_curve = run_passive_benchmark(
        series, fold, book.initial_cash, book.cash_yield_annual, book.cost, book.quantity_step
    )
    cash_curve = run_cash_benchmark(fold, book.initial_cash, book.cash_yield_annual)
    strategy_metrics = compute_metrics(strategy.curve, book.initial_cash)
    passive_metrics = compute_metrics(passive_curve, book.initial_cash)
    cash_metrics = compute_metrics(cash_curve, book.initial_cash)
    edge: Decimal | None = None
    if strategy_metrics and passive_metrics:
        edge = _q(
            Decimal(strategy_metrics["total_return"]) - Decimal(passive_metrics["total_return"])
        )
    return FoldOutcome(
        fold_index=fold_index,
        train_sessions=len(train_sessions),
        test_start=fold[0],
        test_end=fold[-1],
        test_sessions=len(fold),
        rule_digest=rule.digest(),
        rule_description=rule.describe(),
        fitted=fitted,
        strategy_total_return=_q(Decimal(strategy_metrics.get("total_return", Decimal("0")))),
        passive_total_return=_q(Decimal(passive_metrics.get("total_return", Decimal("0")))),
        cash_total_return=_q(Decimal(cash_metrics.get("total_return", Decimal("0")))),
        edge=edge,
        strategy_max_drawdown=_q(Decimal(strategy_metrics.get("max_drawdown", Decimal("0")))),
        cost_paid=round_money(strategy.cost_paid),
        data_gaps=strategy.data_gaps,
        fills=len(strategy.fills),
    )


def _mean(values: list[Decimal]) -> Decimal:
    return sum(values, Decimal("0")) / Decimal(len(values)) if values else Decimal("0")


def _decide(
    protocol: EvalProtocol,
    folds: list[FoldOutcome],
    robustness: list[RobustnessOutcome],
    data_source: str,
    sample_sessions: int,
) -> tuple[EvalVerdict, tuple[str, ...], dict[str, str]]:
    rationale: list[str] = []
    if sample_sessions < protocol.min_sample_sessions:
        return (
            EvalVerdict.REJECT,
            (
                f"insufficient sample: {sample_sessions} < {protocol.min_sample_sessions} "
                f"sessions — rejected for data reasons, not performance reasons",
            ),
            {},
        )
    complete = [fold for fold in folds if fold.edge is not None]
    if not complete:
        return (
            EvalVerdict.REJECT,
            ("no completed out-of-sample fold (data gaps make the series unevaluable)",),
            {},
        )
    edges = [fold.edge for fold in complete if fold.edge is not None]
    mean_edge = _mean(edges)
    positive_share = Decimal(len([edge for edge in edges if edge > 0])) / Decimal(len(edges))
    max_dd = max((fold.strategy_max_drawdown for fold in complete), default=Decimal("0"))
    stable_share = (
        Decimal(len([r for r in robustness if r.stable])) / Decimal(len(robustness))
        if robustness
        else Decimal("0")
    )
    aggregate = {
        "mean_fold_edge": str(_q(mean_edge)),
        "min_fold_edge": str(_q(min(edges))),
        "max_fold_edge": str(_q(max(edges))),
        "positive_fold_share": str(_q(positive_share)),
        "max_fold_drawdown": str(_q(max_dd)),
        "complete_folds": str(len(complete)),
        "total_folds": str(len(folds)),
        "robust_stable_share": str(_q(stable_share)),
    }
    if max_dd > protocol.max_drawdown_tolerance:
        rationale.append(
            f"risk constraint violated: max fold drawdown {aggregate['max_fold_drawdown']} > "
            f"tolerance {protocol.max_drawdown_tolerance}"
        )
        return EvalVerdict.REJECT, tuple(rationale), aggregate
    if mean_edge <= protocol.reject_max_mean_edge:
        rationale.append(
            f"mean cost-adjusted edge vs passive {aggregate['mean_fold_edge']} is within the "
            f"registered reject zone (<= {protocol.reject_max_mean_edge})"
        )
        return EvalVerdict.REJECT, tuple(rationale), aggregate
    removal_collapses = any(
        item.perturbation == "remove_best_period"
        and EvalVerdict(item.verdict) is EvalVerdict.REJECT
        for item in robustness
    )
    gates = {
        "mean edge": mean_edge >= protocol.paper_min_mean_edge,
        "positive fold share": positive_share >= protocol.min_positive_fold_share,
        "robustness stability": stable_share >= protocol.min_robust_stable_share,
        "best-period removal": not removal_collapses,
    }
    if all(gates.values()):
        verdict = EvalVerdict.PAPER_TEST
        rationale.append(
            "all registered gates pass: "
            + ", ".join(f"{name} ok" for name in gates)
            + (
                f" (mean edge {aggregate['mean_fold_edge']}, "
                f"positive share {aggregate['positive_fold_share']})"
            )
        )
        if data_source != "real":
            verdict = EvalVerdict.CONTINUE_RESEARCH
            rationale.append(
                f"capped at CONTINUE_RESEARCH: data source '{data_source}' — synthetic "
                f"data cannot establish trading performance"
            )
        return verdict, tuple(rationale), aggregate
    failed = ", ".join(f"{name} FAIL" for name, passed in gates.items() if not passed)
    rationale.append(
        f"noisy or incomplete edge: {failed} (mean {aggregate['mean_fold_edge']}, "
        f"positive share {aggregate['positive_fold_share']}, stable share "
        f"{aggregate['robust_stable_share']})"
    )
    return EvalVerdict.CONTINUE_RESEARCH, tuple(rationale), aggregate


def _perturb(
    series: CloseSeries,
    sessions: list[date],
    kind: str,
    protocol: EvalProtocol,
) -> tuple[CloseSeries, list[date], str]:
    dates = series.dates()
    closes = [series._closes[i] for i in range(len(series))]  # noqa: SLF001 - same package family, deterministic
    if kind == "delay_1d":
        pairs = list(zip(dates[1:], closes[:-1], strict=False))
    elif kind == "missing_5pct":
        pairs = [pair for i, pair in enumerate(zip(dates, closes, strict=False)) if i % 20 != 0]
    elif kind == "gap_window":
        skip_start = max(len(dates) // 2 - 10, 0)
        pairs = [
            pair
            for i, pair in enumerate(zip(dates, closes, strict=False))
            if not skip_start <= i < skip_start + 20
        ]
    elif kind == "remove_best_period":
        returns = [
            (closes[i] / closes[i - 1] - 1)
            for i in range(1, min(1 + len(closes) // 4, len(closes)))
        ]
        keep = max(len(closes) // 4, 1)
        drop = sorted(
            (i + 1 for i, _ in sorted(enumerate(returns), key=lambda pair: pair[1])[-keep:]),
        )
        drop_set = set(drop)
        pairs = [(dates[i], closes[i]) for i in range(len(dates)) if i not in drop_set]
    else:
        raise ValueError(f"unknown perturbation {kind}")
    detail = f"{kind}: {len(dates)} -> {len(pairs)} sessions"
    return CloseSeries(pairs), [d for d, _ in pairs], detail


def run_robustness(
    protocol: EvalProtocol,
    series: CloseSeries,
    sessions: list[date],
    base_verdict: EvalVerdict,
    book: BookSettings,
    instrument_id: str,
    data_snapshot_id: str,
    data_source: str,
) -> list[RobustnessOutcome]:
    outcomes: list[RobustnessOutcome] = []
    for kind in ("delay_1d", "missing_5pct", "gap_window", "remove_best_period"):
        perturbed, perturbed_sessions, detail = _perturb(series, sessions, kind, protocol)
        try:
            report = evaluate_protocol(
                protocol,
                perturbed,
                perturbed_sessions,
                book=book,
                instrument_id=instrument_id,
                data_snapshot_id=data_snapshot_id,
                data_source=data_source,
                include_robustness=False,
            )
            verdict = report.verdict
        except (RuntimeError, ValueError):
            detail += " — perturbation run infeasible (treated as unstable)"
            verdict = base_verdict
            outcomes.append(RobustnessOutcome(kind, detail, verdict.value, stable=False))
            continue
        outcomes.append(
            RobustnessOutcome(kind, detail, verdict.value, stable=verdict == base_verdict)
        )
    # Parameter perturbation: a registered 10% shift of the entry/exit grid.
    shifted = EvalProtocol(
        **{
            **protocol.__dict__,
            "entry_candidates": tuple(v * Decimal("1.1") for v in protocol.entry_candidates),
            "exit_candidates": tuple(v * Decimal("1.1") for v in protocol.exit_candidates),
            "protocol_version": f"{protocol.protocol_version}+params10",
        }
    )
    try:
        report = evaluate_protocol(
            shifted,
            series,
            sessions,
            book=book,
            instrument_id=instrument_id,
            data_snapshot_id=data_snapshot_id,
            data_source=data_source,
            include_robustness=False,
        )
        verdict = report.verdict
    except (RuntimeError, ValueError):
        verdict = base_verdict
        outcomes.append(
            RobustnessOutcome(
                "params_10pct",
                "grid scaled x1.1 — run infeasible (treated as unstable)",
                verdict.value,
                False,
            )
        )
    else:
        outcomes.append(
            RobustnessOutcome(
                "params_10pct", "grid scaled x1.1", verdict.value, stable=verdict == base_verdict
            )
        )
    return outcomes


def evaluate_protocol(
    protocol: EvalProtocol,
    series: CloseSeries,
    sessions: list[date],
    *,
    book: BookSettings,
    instrument_id: str,
    data_snapshot_id: str,
    data_source: str,
    include_robustness: bool = True,
) -> EdgeReport:
    """Evaluate one instrument under ``protocol``; deterministic end to end."""
    protocol.validate()
    grid = _build_grid(protocol, book.target_weight)
    budget = {"remaining": protocol.max_grid_runs, "spent": 0}
    folds = [
        _fold_outcome(protocol, series, sessions, fold, book, instrument_id, grid, budget, index)
        for index, fold in enumerate(
            _fold_sessions(sessions, protocol.fold_days, protocol.max_folds)
        )
    ]
    robustness: list[RobustnessOutcome] = []
    if include_robustness:
        probe = _decide(protocol, folds, [], data_source, len(sessions))
        robustness = run_robustness(
            protocol, series, sessions, probe[0], book, instrument_id, data_snapshot_id, data_source
        )
    verdict, rationale, aggregate = _decide(protocol, folds, robustness, data_source, len(sessions))
    complete = [fold for fold in folds if fold.edge is not None]
    total_cost = round_money(sum((fold.cost_paid for fold in folds), Decimal("0")))
    folds_with_cost = max(len(folds), 1)
    cost_drag = _q(total_cost / (book.initial_cash * Decimal(folds_with_cost)))
    mean_edge = _q(Decimal(aggregate.get("mean_fold_edge", "0"))) if complete else Decimal("0")
    cost_view = {
        "total_cost": str(total_cost),
        "initial_cash": str(book.initial_cash),
        "cost_drag_per_fold": str(cost_drag),
        "breakeven_edge_vs_cash": str(_q(cost_drag)),
        "note": (
            "break-even edge is the per-fold return needed just to cover modelled costs "
            "(fee + slippage assumptions, not observed fills)"
        ),
    }
    if complete:
        cost_view["net_edge_vs_passive"] = str(mean_edge)
        cost_view["cost_accounting"] = "fold returns already include costs; no second subtraction"
    limitations: list[str] = [
        f"Execution model {EXECUTION_VERSION}; prior same-close evidence is not comparable.",
        "no live actions: this report is research measurement only",
        "costs are modelled assumptions (fee + slippage per fill notional), not observed fills",
    ]
    if data_source != "real":
        limitations.append(
            f"data source is '{data_source}': synthetic data cannot establish trading performance"
        )
    if len(sessions) < 500:
        limitations.append(f"small sample: {len(sessions)} sessions; prospective evidence required")
    if any(not fold.fitted for fold in folds):
        limitations.append(
            "some folds were not fitted (insufficient training history) — their edges use "
            "the grid default"
        )
    basis = {
        "protocol": protocol.digest(),
        "instrument": instrument_id,
        "snapshot": data_snapshot_id,
        "source": data_source,
        "prices": [(day.isoformat(), str(price)) for day, price in series.up_to(series.dates()[-1])]
        if series.dates()
        else [],
        "sessions": [day.isoformat() for day in sessions],
        "capital": str(book.initial_cash),
        "quantity_step": str(book.quantity_step),
        "target": str(book.target_weight),
        "cash_yield": str(book.cash_yield_annual),
        "costs": book.cost.model_dump(mode="json"),
        "execution": EXECUTION_VERSION,
        "version": __version__,
    }
    run_id = hashlib.sha256(json.dumps(basis, sort_keys=True).encode()).hexdigest()[:32]
    return EdgeReport(
        protocol_digest=protocol.digest(),
        protocol_version=protocol.protocol_version,
        run_id=run_id,
        code_version=__version__,
        data_snapshot_id=data_snapshot_id,
        data_source=data_source,
        instrument_id=instrument_id,
        verdict=verdict,
        rationale=rationale,
        folds=tuple(folds),
        robustness=tuple(robustness),
        aggregate=aggregate,
        cost_view=cost_view,
        sample={
            "sessions": len(series),
            "start": series.dates()[0].isoformat() if series.dates() else "",
            "end": series.dates()[-1].isoformat() if series.dates() else "",
            "data_gaps": sum((fold.data_gaps for fold in folds), 0),
            "total_fills": sum((fold.fills for fold in folds), 0),
        },
        limitations=tuple(limitations),
    )


def _report_dict(report: EdgeReport) -> dict[str, object]:
    return {
        "protocol": {
            "version": report.protocol_version,
            "digest": report.protocol_digest,
        },
        "run": {
            "run_id": report.run_id,
            "code_version": report.code_version,
            "data_snapshot_id": report.data_snapshot_id,
            "data_source": report.data_source,
            "instrument_id": report.instrument_id,
        },
        "verdict": report.verdict.value,
        "rationale": list(report.rationale),
        "folds": [
            {
                "fold_index": fold.fold_index,
                "train_sessions": fold.train_sessions,
                "test_start": fold.test_start.isoformat(),
                "test_end": fold.test_end.isoformat(),
                "test_sessions": fold.test_sessions,
                "rule_digest": fold.rule_digest,
                "rule": fold.rule_description,
                "fitted": fold.fitted,
                "strategy_total_return": str(fold.strategy_total_return),
                "passive_total_return": str(fold.passive_total_return),
                "cash_total_return": str(fold.cash_total_return),
                "edge": None if fold.edge is None else str(fold.edge),
                "strategy_max_drawdown": str(fold.strategy_max_drawdown),
                "cost_paid": str(fold.cost_paid),
                "data_gaps": fold.data_gaps,
            }
            for fold in report.folds
        ],
        "aggregate": dict(report.aggregate),
        "cost_view": dict(report.cost_view),
        "sample": dict(report.sample),
        "robustness": [
            {
                "perturbation": item.perturbation,
                "detail": item.detail,
                "verdict": item.verdict,
                "stable": item.stable,
            }
            for item in report.robustness
        ],
        "limitations": list(report.limitations),
        "artifacts": dict(report.artifacts),
    }


def render_report_json(report: EdgeReport) -> str:
    return json.dumps(_report_dict(report), indent=2, sort_keys=True)


def render_report_markdown(report: EdgeReport) -> str:
    lines = [
        f"# Economic-Edge Evaluation — {report.instrument_id}",
        "",
        f"- **Verdict: {report.verdict.value.upper()}**",
        f"- protocol `{report.protocol_version}` digest `{report.protocol_digest}` — run "
        f"`{report.run_id}` (code {report.code_version})",
        f"- data: snapshot `{report.data_snapshot_id}` ({report.data_source}), "
        f"sample {report.sample['sessions']} sessions "
        f"{report.sample['start']}..{report.sample['end']} "
        f"- data is explicitly **SIMULATION/RESEARCH** — no live actions",
        "Rationale:",
        *[f"- {item}" for item in report.rationale],
        "",
        "Walk-forward folds (fit on strictly earlier sessions):",
        "| fold | test window | sessions | rule | strat ret | passive ret | cash ret | "
        "edge | max dd | cost |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for fold in report.folds:
        lines.append(
            f"| {fold.fold_index} | {fold.test_start}..{fold.test_end} | "
            f"{fold.test_sessions} | `{fold.rule_digest}`"
            f"({'fitted' if fold.fitted else 'default'}) | {fold.strategy_total_return} | "
            f"{fold.passive_total_return}"
            f"| {fold.cash_total_return} | {fold.edge if fold.edge is not None else 'n/a'} "
            f"| {fold.strategy_max_drawdown} | {fold.cost_paid} |"
        )
    lines += ["", "Aggregate / cost view:"]
    lines += [
        f"- {key}: {value}"
        for key, value in list(report.aggregate.items()) + list(report.cost_view.items())
    ]
    lines += ["", "Robustness (verdict stability under registered perturbations):"]
    lines += [
        f"- {item.perturbation} — {item.detail} → {item.verdict} "
        f"({'stable' if item.stable else 'UNSTABLE'})"
        for item in report.robustness
    ]
    lines += ["", "Limitations:"]
    lines += [f"- {item}" for item in report.limitations]
    lines.append("")
    return "\n".join(lines)


def write_report(report: EdgeReport, out_dir: Path) -> EdgeReport:
    """Persist the report artifacts (JSON + Markdown); returns the updated report."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = f"{report.instrument_id}_{report.sample['start']}_{report.sample['end']}"
    json_path = out_dir / f"econ_eval_{stamp}_{report.run_id}.json"
    md_path = out_dir / f"econ_eval_{stamp}_{report.run_id}.md"
    json_path.write_text(render_report_json(report), encoding="utf-8")
    md_path.write_text(render_report_markdown(report), encoding="utf-8")
    return EdgeReport(
        **{
            **report.__dict__,
            "artifacts": {"json": str(json_path), "markdown": str(md_path)},
        }
    )
