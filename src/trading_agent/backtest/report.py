"""Backtest report package rendering (JSON + Markdown + CSV + SVG).

Deterministic: fixed field order, quantized decimals, chronological rows.
"""

from __future__ import annotations

import csv
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from .engine import BacktestRun

_FX = Decimal("0.000001")


def _money(value: Decimal | None) -> str:
    return f"{value.quantize(Decimal('0.01'))}" if value is not None else None


def _num(value: Decimal | float | None) -> str | None:
    if value is None:
        return None
    return f"{Decimal(str(value)).quantize(_FX)}"


def run_to_dict(run: BacktestRun) -> dict:
    """JSON-ready snapshot of a run (Decimal -> string, fixed ordering)."""
    return {
        "backtest_id": run.backtest_id,
        "config_digest": run.config_digest,
        "config_path": run.config_path,
        "code_version": run.code_version,
        "spec_digest": run.spec_digest,
        "data_snapshot_id": run.data_snapshot_id,
        "data_source": run.data_source,
        "range": {"start": run.range_start.isoformat(), "end": run.range_end.isoformat()},
        "sessions": len(run.sessions),
        "instruments": list(run.instrument_ids),
        "settings": {
            "initial_cash_usd": _money(run.settings.initial_cash_usd),
            "cash_yield_annual": str(run.settings.cash_yield_annual),
            "cost": {"fee_rate": str(run.settings.cost.fee_rate), "slippage_rate": str(run.settings.cost.slippage_rate)},
            "walk_forward": {
                "fold_days": run.settings.walk_forward.fold_days,
                "min_train_days": run.settings.walk_forward.min_train_days,
                "score": run.settings.walk_forward.score,
                "lookback_candidates": run.settings.walk_forward.lookback_candidates,
                "entry_candidates": [str(v) for v in run.settings.walk_forward.entry_candidates],
                "exit_candidates": [str(v) for v in run.settings.walk_forward.exit_candidates],
            },
        },
        "portfolio_metrics": {
            "total_return": _num(run.portfolio_metrics.get("total_return")),
            "cagr": _num(run.portfolio_metrics.get("cagr")),
            "sharpe": _num(run.portfolio_metrics.get("sharpe")),
            "max_drawdown": _num(run.portfolio_metrics.get("max_drawdown")),
            "final_equity": _money(run.portfolio_metrics.get("final_equity")),
        },
        "books": [
            {
                "instrument_id": book.instrument_id,
                "metrics": {
                    "total_return": _num(book.metrics.get("total_return")),
                    "cagr": _num(book.metrics.get("cagr")),
                    "sharpe": _num(book.metrics.get("sharpe")),
                    "max_drawdown": _num(book.metrics.get("max_drawdown")),
                    "final_equity": _money(book.final_equity),
                },
                "data_gaps": book.data_gaps,
                "cost_paid": _money(book.cost_paid),
                "folds": [
                    {
                        "fold_index": fold.fold_index,
                        "train": [fold.train_start.isoformat(), fold.train_end.isoformat()],
                        "test": [fold.test_start.isoformat(), fold.test_end.isoformat()],
                        "chosen_rule": fold.chosen_rule.describe(),
                        "chosen_rule_digest": fold.chosen_rule.digest(),
                        "train_score": _num(fold.train_score) if fold.train_score.is_finite() else None,
                        "total_return": _num(fold.metrics.get("total_return")),
                        "sharpe": _num(fold.metrics.get("sharpe")),
                        "max_drawdown": _num(fold.metrics.get("max_drawdown")),
                    }
                    for fold in book.folds
                ],
            }
            for book in run.books
        ],
        "benchmarks": [
            {
                "key": benchmark.key,
                "metrics": {
                    "total_return": _num(benchmark.metrics.get("total_return")),
                    "cagr": _num(benchmark.metrics.get("cagr")),
                    "sharpe": _num(benchmark.metrics.get("sharpe")),
                    "max_drawdown": _num(benchmark.metrics.get("max_drawdown")),
                    "final_equity": _money(benchmark.metrics.get("final_equity")),
                },
            }
            for benchmark in run.benchmarks
        ],
        "provenance": dict(sorted(run.provenance.items())),
        "curve": {
            "momentum_composite": [
                [session.isoformat(), _money(value)] for session, value in _composite_curve(run, "momentum-composite")
            ],
            "passive_composite": [
                [session.isoformat(), _money(value)] for session, value in _composite_curve(run, "passive-composite")
            ],
            "cash": [[session.isoformat(), _money(value)] for session, value in _composite_curve(run, "cash")],
        },
    }


def _composite_curve(run: BacktestRun, key: str):
    for benchmark in run.benchmarks:
        if benchmark.key == key:
            return benchmark.curve
    return []


def write_report_package(run: BacktestRun, directory: Path) -> list[Path]:
    """Render results.json, report.md, equity.csv, fills.csv, equity_curve.svg."""
    directory.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    results_path = directory / "results.json"
    results_path.write_text(json.dumps(run_to_dict(run), indent=2, sort_keys=False) + "\n", encoding="utf-8")
    written.append(results_path)

    equity_path = directory / "equity.csv"
    with equity_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["session", "momentum_composite", "passive_composite", "cash", *[f"book_{i.split(':')[-1]}" for i in run.instrument_ids]]
        )
        momentum = {s: v for s, v in _composite_curve(run, "momentum-composite")}
        passive = {s: v for s, v in _composite_curve(run, "passive-composite")}
        cash = {s: v for s, v in _composite_curve(run, "cash")}
        books = {book.instrument_id: {s: v for s, v in book.curve} for book in run.books}
        for session in run.sessions:
            row = [session.isoformat(), _money(momentum.get(session)), _money(passive.get(session)), _money(cash.get(session))]
            row += [_money(books[instrument_id].get(session)) for instrument_id in run.instrument_ids]
            writer.writerow(row)
    written.append(equity_path)

    fills_path = directory / "fills.csv"
    with fills_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["session", "instrument_id", "side", "price", "quantity", "fee"])
        for book in run.books:
            for fill_session, side, price, quantity, fee in sorted(book.fills):
                writer.writerow(
                    [fill_session.isoformat(), book.instrument_id, side, _money(price), f"{quantity}", _money(fee)]
                )
    written.append(fills_path)

    md_path = directory / "report.md"
    md_path.write_text(render_markdown(run), encoding="utf-8")
    written.append(md_path)

    svg_path = directory / "equity_curve.svg"
    svg_path.write_text(render_svg(run), encoding="utf-8")
    written.append(svg_path)
    return written


def render_markdown(run: BacktestRun) -> str:
    lines: list[str] = []
    add = lines.append
    add(f"# Backtest Report — {run.backtest_id}")
    add("")
    add(f"- Data source: **{run.data_source}** (snapshots: `{run.data_snapshot_id}`)")
    add(f"- Range: {run.range_start} .. {run.range_end} ({len(run.sessions)} sessions)")
    add(f"- Instruments: {', '.join(run.instrument_ids)}")
    add(f"- Capital: {run.settings.initial_cash_usd} per book; cash yield {run.settings.cash_yield_annual} annual (daily-compounded)")
    add(f"- Costs: fee {run.settings.cost.fee_rate} + slippage {run.settings.cost.slippage_rate} per fill notional")
    add(f"- Determinism: code `{run.code_version}` · spec `{run.spec_digest}` · config `{run.config_digest}`")
    add("")
    add("## Momentum composite vs benchmarks")
    add("")
    add("| Strategy | Total return | CAGR | Sharpe | Max drawdown | Final equity |")
    add("|---|---|---|---|---|---|")
    for key in ("momentum-composite", "passive-composite", "cash"):
        benchmark = next((b for b in run.benchmarks if b.key == key), None)
        if benchmark is None:
            continue
        m = benchmark.metrics
        add(
            f"| {key} | {_pct(m.get('total_return'))} | {_pct(m.get('cagr'))} | {_num(m.get('sharpe'))} | {_pct(m.get('max_drawdown'))} | ${_money(m.get('final_equity'))} |"
        )
    add("")
    add("## Per-instrument books (walk-forward pooled)")
    add("")
    add("| Instrument | Total return | CAGR | Sharpe | Max drawdown | Data gaps | Costs paid |")
    add("|---|---|---|---|---|---|---|")
    for book in run.books:
        m = book.metrics
        add(
            f"| {book.instrument_id} | {_pct(m.get('total_return'))} | {_pct(m.get('cagr'))} | {_num(m.get('sharpe'))} | {_pct(m.get('max_drawdown'))} | {book.data_gaps} | ${_money(book.cost_paid)} |"
        )
    add("")
    add("## Walk-forward folds")
    add("")
    for book in run.books:
        add(f"### {book.instrument_id}")
        add("")
        add("| Fold | Train window | Test window | Chosen rule | Train score | Test return | Test Sharpe |")
        add("|---|---|---|---|---|---|---|")
        for fold in book.folds:
            train = f"{fold.train_start} .. {fold.train_end}" if fold.train_start < fold.train_end else "(none)"
            score = _num(fold.train_score) if fold.train_score.is_finite() else "n/a"
            add(
                f"| {fold.fold_index} | {train} | {fold.test_start} .. {fold.test_end} | {fold.chosen_rule.describe()} | {score} "
                f"| {_pct(fold.metrics.get('total_return'))} | {_num(fold.metrics.get('sharpe'))} |"
            )
        add("")
    add("## Provenance (conventions)")
    add("")
    for key, value in sorted(run.provenance.items()):
        add(f"- **{key}**: {value}")
    add("")
    add("## Files")
    add("")
    add("- `results.json` — full machine-readable run snapshot")
    add("- `equity.csv` — per-session equity for all curves")
    add("- `fills.csv` — every fill with session, side, price, quantity, fee")
    add("- `equity_curve.svg` — normalized equity comparison")
    add("")
    if run.data_source != "real":
        add("> **Note**: this run used synthetic data and is a pipeline demonstration only; it must never be read as a performance forecast.")
        add("")
    return "\n".join(lines) + "\n"


def _pct(value: Decimal | float | None) -> str:
    if value is None:
        return "n/a"
    return f"{float(Decimal(str(value))) * 100:.2f}%"


def render_svg(run: BacktestRun, width: int = 900, height: int = 420) -> str:
    """Dependency-free normalized equity chart (log scale, first session = 1.0)."""
    import math as _math

    left, bottom, top, right = 60, 30, 16, 16
    series: dict[str, list[tuple[date, Decimal]]] = {}
    for key in ("momentum-composite", "passive-composite", "cash"):
        curve = _composite_curve(run, key)
        if curve:
            series[key] = curve
    all_sessions = sorted({session for curve in series.values() for session, _ in curve})
    if not all_sessions or not series:
        return "<svg xmlns='http://www.w3.org/2000/svg'/>"
    s0, s1 = all_sessions[0], all_sessions[-1]
    spans = {key: [(value / curve[0][1]) for _, value in curve] for key, curve in series.items()}
    min_log = min(_math.log(v) for values in spans.values() for v in values if v > 0)
    max_log = max(_math.log(v) for values in spans.values() for v in values if v > 0)
    span = max(max_log - min_log, 1e-9)

    def x(session: date) -> float:
        total = (s1 - s0).days or 1
        return left + (session - s0).days / total * (width - left - right)

    def y(value: Decimal) -> float:
        log_v = _math.log(float(value))
        return top + (1 - (log_v - min_log) / span) * (height - top - bottom)

    colors = {"momentum-composite": "#1d4ed8", "passive-composite": "#b45309", "cash": "#6b7280"}
    parts = [
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}' viewBox='0 0 {width} {height}'>",
        f"<rect width='{width}' height='{height}' fill='white'/>",
        f"<text x='{left}' y='14' font-family='sans-serif' font-size='12' fill='#111'>{run.backtest_id} — normalized equity (log scale) · {run.data_source} data</text>",
    ]
    # y-axis gridlines (2x, 1x, 0.5x)
    for label, factor in (("2.0x", 2.0), ("1.0x", 1.0), ("0.5x", 0.5)):
        log_v = _math.log(factor)
        if min_log <= log_v <= max_log:
            gy = y(Decimal(str(factor)))
            parts.append(f"<line x1='{left}' y1='{gy:.1f}' x2='{width - right}' y2='{gy:.1f}' stroke='#e5e7eb'/>")
            parts.append(f"<text x='{left - 8}' y='{gy + 4:.1f}' font-family='sans-serif' font-size='10' fill='#6b7280' text-anchor='end'>{label}</text>")
    for key in sorted(series):
        points = " ".join(f"{x(s):.1f},{y(v):.1f}" for s, v in series[key])
        parts.append(f"<polyline points='{points}' fill='none' stroke='{colors.get(key, '#111')}' stroke-width='1.6'/>")
    x0, x1 = x(s0), x(s1)
    parts.append(f"<line x1='{x0:.1f}' y1='{bottom}' x2='{x1:.1f}' y2='{bottom}' stroke='#9ca3af'/>")
    parts.append(f"<text x='{x0:.1f}' y='{height - 8}' font-family='sans-serif' font-size='10' fill='#6b7280'>{s0}</text>")
    parts.append(f"<text x='{x1:.1f}' y='{height - 8}' font-family='sans-serif' font-size='10' fill='#6b7280' text-anchor='end'>{s1}</text>")
    legend_x = left
    for key in sorted(series):
        parts.append(f"<rect x='{legend_x}' y='{height - 24}' width='10' height='3' fill='{colors.get(key, '#111')}'/>")
        label = key.replace("momentum-composite", "momentum").replace("passive-composite", "passive")
        parts.append(f"<text x='{legend_x + 13}' y='{height - 20}' font-family='sans-serif' font-size='10' fill='#374151'>{label}</text>")
        legend_x += 13 + len(label) * 6 + 18
    parts.append("</svg>")
    return "\n".join(parts)
