"""Walk-forward backtest engine (M3, plan section 11 + docs/strategy_momentum_v1.md).

Deterministic, point-in-time, Decimal-denominated. Conventions (repeated in
the rendered report's provenance section):

- One decision per session, at the session close, using only closes dated at
  or before the decision session. Insufficient history (fewer than
  ``lookback`` trailing closes) means no trade — never extrapolated.
- Signal: trailing-window momentum ``m = close[t] / close[t - lookback] - 1``.
  Long-only, one position per instrument: enter at ``m >= entry_momentum``,
  exit at ``m <= exit_momentum``. Orders execute no earlier than the next
  listed session close. A missing execution bar expires the pending order.
- Costs: ``fee_rate + slippage_rate`` on every fill's traded notional.
- Idle cash accrues the documented annual yield, daily-compounded with the
  same fixed-precision factor as the paper ledger.
- Data gaps: a session with no observation marks the position at its last
  known close; gaps are counted, never interpolated.
- Walk-forward: chronological folds. A fold's rule is fitted only on sessions
  strictly before the fold; the fold's test window never touches the fit.
  Each fold deploys fresh initial capital (standard walk-forward convention);
  fold curves concatenate into the instrument curve.
- Benchmarks on identical capital: cash (yield only) and per-instrument
  passive buy-and-hold (one fill, costs included).

The engine is deterministic: fixed Decimal arithmetic, fixed yield factor,
sorted iteration, and explicit ties broken by grid order.
"""

from __future__ import annotations

import bisect
import hashlib
import math
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_DOWN, Decimal

from .. import __version__
from ..config.models import (
    BacktestCostSettings,
    BacktestSettings,
    TradingConfig,
    WalkForwardSettings,
)
from ..data.provider import MarketDataProvider
from ..money import round_money
from ..strategies.baselines import daily_yield_factor

_QUANTITY_EXP = Decimal("0.00000001")
EXECUTION_VERSION = "next-session-close-initial-capital-v3"


class LeakageError(RuntimeError):
    """Raised when an observation series violates the point-in-time contract."""


@dataclass(frozen=True)
class MomentumRule:
    lookback: int
    entry_momentum: Decimal
    exit_momentum: Decimal
    target_weight: Decimal

    def digest(self) -> str:
        payload = (
            f"{self.lookback}|{self.entry_momentum.normalize()}|"
            f"{self.exit_momentum.normalize()}|{self.target_weight.normalize()}"
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def describe(self) -> str:
        return (
            f"lookback={self.lookback} entry>={self.entry_momentum.normalize()} "
            f"exit<={self.exit_momentum.normalize()} weight={self.target_weight.normalize()}"
        )


@dataclass(frozen=True)
class BookSettings:
    initial_cash: Decimal
    cash_yield_annual: Decimal
    cost: BacktestCostSettings
    target_weight: Decimal
    quantity_step: Decimal = _QUANTITY_EXP

    def __post_init__(self) -> None:
        if self.quantity_step not in {Decimal(1).scaleb(-i) for i in range(9)}:
            raise ValueError("quantity precision must be a supported power of ten")


class CloseSeries:
    """Indexed point-in-time view of one instrument's session closes."""

    def __init__(self, pairs: list[tuple[date, Decimal]]) -> None:
        dates = [obs_date for obs_date, _ in pairs]
        if any(dates[i] > dates[i + 1] for i in range(len(dates) - 1)):
            raise LeakageError("observation series is not chronologically sorted")
        if len(set(dates)) != len(dates):
            duplicate = next(d for i, d in enumerate(dates) if i and d == dates[i - 1])
            raise LeakageError(f"duplicate observation date {duplicate}")
        self._dates: tuple[date, ...] = tuple(dates)
        self._closes: tuple[Decimal, ...] = tuple(value for _, value in pairs)
        self._by_date = dict(pairs)

    def __len__(self) -> int:
        return len(self._dates)

    def dates(self) -> tuple[date, ...]:
        return self._dates

    def up_to(self, as_of: date, count: int | None = None) -> list[tuple[date, Decimal]]:
        """Observations dated at or before ``as_of`` (point-in-time slice)."""
        index = bisect.bisect_right(self._dates, as_of)
        low = max(0, index - count) if count is not None else 0
        return list(zip(self._dates[low:index], self._closes[low:index], strict=False))

    def value_on(self, session: date) -> Decimal | None:
        return self._by_date.get(session)

    def value_through(self, as_of: date) -> Decimal | None:
        index = bisect.bisect_right(self._dates, as_of)
        return self._closes[index - 1] if index else None


def momentum_over_window(window: list[tuple[date, Decimal]], lookback: int) -> Decimal | None:
    if len(window) < lookback + 1:
        return None
    oldest = window[0][1]
    if oldest <= 0:
        return None
    return window[-1][1] / oldest - Decimal(1)


def compute_metrics(
    curve: list[tuple[date, Decimal]], initial_cash: Decimal | None = None
) -> dict[str, Decimal | float]:
    """Total return, CAGR, Sharpe (rf=0, 252-day annualized), max drawdown."""
    if not curve:
        return {}
    first = initial_cash if initial_cash is not None else curve[0][1]
    last = curve[-1][1]
    if first <= 0 or last < 0:
        raise ValueError("performance requires positive starting capital and nonnegative NAV")
    years = max((curve[-1][0] - curve[0][0]).days + 1, 1) / 365.25
    cagr = (
        Decimal("-1")
        if last == 0
        else Decimal(str(round(math.exp(math.log(float(last / first)) / years) - 1.0, 12)))
    )
    returns = [
        curve[i][1] / curve[i - 1][1] - 1 for i in range(1, len(curve)) if curve[i - 1][1] > 0
    ]
    if initial_cash is not None:
        returns.insert(0, curve[0][1] / first - 1)
    if len(returns) >= 2:
        mean = sum(returns, Decimal("0")) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
        std = math.sqrt(float(variance))
        sharpe = (
            Decimal(str(round(float(mean) / std * math.sqrt(252.0), 8)))
            if std > 0
            else Decimal("0")
        )
    else:
        sharpe = Decimal("0")
    running_max = first
    max_drawdown = Decimal("0")
    for _, equity in curve:
        running_max = max(running_max, equity)
        if running_max > 0:
            max_drawdown = max(max_drawdown, 1 - equity / running_max)
    return {
        "total_return": (last / first - 1).quantize(Decimal("0.000001")),
        "cagr": cagr,
        "sharpe": sharpe,
        "max_drawdown": max_drawdown.quantize(Decimal("0.000001")),
        "final_equity": round_money(last),
    }


@dataclass
class SingleBookResult:
    instrument_id: str
    rule: MomentumRule
    curve: list[tuple[date, Decimal]] = field(default_factory=list)
    fills: list[tuple[date, str, Decimal, Decimal, Decimal]] = field(default_factory=list)
    cost_paid: Decimal = Decimal("0")
    data_gaps: int = 0
    final_equity: Decimal = Decimal("0")
    metrics: dict[str, Decimal | float] = field(default_factory=dict)


def run_single_book(
    series: CloseSeries,
    sessions: list[date],
    rule: MomentumRule,
    settings: BookSettings,
    *,
    instrument_id: str,
) -> SingleBookResult:
    """One long-only momentum book on one instrument over ``sessions``.

    Every decision slices ``series.up_to(session)`` — the as-of cutoff is
    enforced in code, and an unsorted/duplicate series raises at construction.
    """
    factor = Decimal(1) + daily_yield_factor(settings.cash_yield_annual)
    cost_rate = settings.cost.fee_rate + settings.cost.slippage_rate
    cash = settings.initial_cash
    quantity = Decimal("0")
    pending: str | None = None
    pending_budget = Decimal(0)
    result = SingleBookResult(instrument_id=instrument_id, rule=rule)
    for session in sessions:
        mark = series.value_on(session)
        stale = mark is None
        if mark is None:
            result.data_gaps += 1
            mark = series.value_through(session)  # stale mark; gap counted, never filled
            if mark is None:
                continue  # warm-up before the first observation
        if not stale:
            if pending == "sell" and quantity > 0:
                gross = quantity * mark
                fee = round_money(gross * cost_rate)
                cash += gross - fee
                result.cost_paid += fee
                result.fills.append((session, "sell", mark, quantity, fee))
                quantity = Decimal("0")
            elif pending == "buy" and quantity == 0:
                notional = min(cash, pending_budget)
                # Size on net-of-fee capacity: price*(1 + cost_rate) <= cash,
                # otherwise the fee check below can never pass and no entry
                # fill ever occurs.
                candidate = (notional / (Decimal(1) + cost_rate) / mark).quantize(
                    settings.quantity_step, rounding=ROUND_DOWN
                )
                if candidate * mark + round_money(candidate * mark * cost_rate) > notional:
                    candidate = max(Decimal(0), candidate - settings.quantity_step)
                if candidate > 0:
                    price = candidate * mark
                    fee = round_money(price * cost_rate)
                    if cash >= price + fee:
                        cash -= price + fee
                        quantity = candidate
                        result.cost_paid += fee
                        result.fills.append((session, "buy", mark, candidate, fee))
        pending = None
        if not stale:
            momentum = momentum_over_window(series.up_to(session, rule.lookback + 1), rule.lookback)
            if quantity > 0 and momentum is not None and momentum <= rule.exit_momentum:
                pending = "sell"
            elif quantity == 0 and momentum is not None and momentum >= rule.entry_momentum:
                pending = "buy"
                pending_budget = cash * settings.target_weight
        cash = round_money(cash * factor)  # daily yield accrual (paper-ledger convention)
        result.curve.append((session, round_money(cash + quantity * mark)))
    result.final_equity = result.curve[-1][1] if result.curve else settings.initial_cash
    result.metrics = compute_metrics(result.curve, settings.initial_cash)
    return result


def run_cash_benchmark(
    sessions: list[date], initial_cash: Decimal, cash_yield_annual: Decimal
) -> list[tuple[date, Decimal]]:
    factor = Decimal(1) + daily_yield_factor(cash_yield_annual)
    cash = initial_cash
    curve: list[tuple[date, Decimal]] = []
    for session in sessions:
        cash = round_money(cash * factor)
        curve.append((session, cash))
    return curve


def run_passive_benchmark(
    series: CloseSeries,
    sessions: list[date],
    initial_cash: Decimal,
    cash_yield_annual: Decimal,
    cost: BacktestCostSettings,
    quantity_step: Decimal = _QUANTITY_EXP,
) -> list[tuple[date, Decimal]]:
    """Buy-and-hold of one instrument: one fill at its first observed close."""
    factor = Decimal(1) + daily_yield_factor(cash_yield_annual)
    cost_rate = cost.fee_rate + cost.slippage_rate
    cash = initial_cash
    quantity = Decimal("0")
    curve: list[tuple[date, Decimal]] = []
    for session in sessions:
        mark = series.value_on(session)
        if mark is None:
            mark = series.value_through(session)
            if mark is None:
                continue
        if quantity == 0 and series.value_on(session) is not None:
            quantity = (cash / (mark * (Decimal(1) + cost_rate))).quantize(
                quantity_step, rounding=ROUND_DOWN
            )
            fee = round_money(quantity * mark * cost_rate)
            cash = max(Decimal("0"), cash - quantity * mark - fee)
        cash = round_money(cash * factor)
        curve.append((session, round_money(cash + quantity * mark)))
    return curve


def _build_rule_grid(wf: WalkForwardSettings, target_weight: Decimal) -> list[MomentumRule]:
    grid: list[MomentumRule] = []
    for lookback in sorted(set(wf.lookback_candidates)):
        for entry in wf.entry_candidates:
            for exit_momentum in wf.exit_candidates:
                grid.append(
                    MomentumRule(
                        lookback=lookback,
                        entry_momentum=entry,
                        exit_momentum=exit_momentum,
                        target_weight=target_weight,
                    )
                )
    return grid


def _fit_rule(
    candidates: list[MomentumRule],
    series: CloseSeries,
    train_sessions: list[date],
    settings: BookSettings,
    instrument_id: str,
    score_name: str,
) -> tuple[MomentumRule, Decimal]:
    best_rule = candidates[0]
    best_score = Decimal("-Infinity")
    for rule in candidates:
        run = run_single_book(series, train_sessions, rule, settings, instrument_id=instrument_id)
        score = run.metrics.get(score_name)
        if not isinstance(score, Decimal) or score == Decimal("-Infinity") or score.is_nan():
            continue
        if score > best_score:  # strict comparison: earlier grid entry wins ties (deterministic)
            best_rule, best_score = rule, score
    return best_rule, best_score


def _fold_sessions(sessions: list[date], fold_days: int) -> list[list[date]]:
    folds: list[list[date]] = []
    current: list[date] = []
    fold_start: date | None = None
    for session in sessions:
        if fold_start is None:
            fold_start, current = session, [session]
        elif (session - fold_start).days >= fold_days:
            folds.append(current)
            fold_start, current = session, [session]
        else:
            current.append(session)
    if current:
        folds.append(current)
    return folds


@dataclass
class WalkForwardFold:
    fold_index: int
    train_start: date
    train_end: date
    test_start: date
    test_end: date
    chosen_rule: MomentumRule
    train_score: Decimal
    curve: list[tuple[date, Decimal]]
    metrics: dict[str, Decimal | float]


@dataclass
class WalkForwardResult:
    instrument_id: str
    folds: list[WalkForwardFold]
    curve: list[tuple[date, Decimal]]
    final_equity: Decimal
    metrics: dict[str, Decimal | float]
    data_gaps: int
    cost_paid: Decimal
    fills: list[tuple[date, str, Decimal, Decimal, Decimal]] = field(default_factory=list)


def _close_pairs(
    provider: MarketDataProvider, instrument_id: str, range_start: date, range_end: date
) -> list[tuple[date, Decimal]]:
    pairs = [
        (close.session, close.close)
        for close in provider.recent_session_closes(instrument_id, range_end, 10**9)
        if range_start <= close.session <= range_end
    ]
    return pairs


def walk_forward_instrument(
    provider: MarketDataProvider,
    instrument_id: str,
    range_start: date,
    range_end: date,
    book: BookSettings,
    wf: WalkForwardSettings,
) -> WalkForwardResult:
    """Time-ordered walk-forward evaluation for one instrument (no lookahead)."""
    warmup_days = max(30, 3 * max(wf.lookback_candidates))
    warmup_start = date.fromordinal(range_start.toordinal() - warmup_days)
    pairs = [
        (close.session, close.close)
        for close in provider.recent_session_closes(instrument_id, range_end, 10**9)
        if warmup_start <= close.session <= range_end
    ]
    series = CloseSeries(pairs)
    sessions = [session for session in provider.sessions() if range_start <= session <= range_end]
    grid = _build_rule_grid(wf, book.target_weight)
    folds = _fold_sessions(sessions, wf.fold_days)
    fold_results: list[WalkForwardFold] = []
    curve: list[tuple[date, Decimal]] = []
    all_fills: list[tuple[date, str, Decimal, Decimal, Decimal]] = []
    total_gaps = 0
    total_cost = Decimal("0")
    for index, fold_sessions in enumerate(folds):
        train_sessions = [s for s in sessions if s < fold_sessions[0]]
        if len(train_sessions) < wf.min_train_days:
            chosen, score = grid[0], Decimal("-Infinity")  # documented: not enough fitted history
        else:
            chosen, score = _fit_rule(grid, series, train_sessions, book, instrument_id, wf.score)
        run = run_single_book(series, fold_sessions, chosen, book, instrument_id=instrument_id)
        fold_results.append(
            WalkForwardFold(
                fold_index=index,
                train_start=train_sessions[0] if train_sessions else fold_sessions[0],
                train_end=train_sessions[-1] if train_sessions else fold_sessions[0],
                test_start=fold_sessions[0],
                test_end=fold_sessions[-1],
                chosen_rule=chosen,
                train_score=score,
                curve=run.curve,
                metrics=run.metrics,
            )
        )
        scale = curve[-1][1] / book.initial_cash if curve else Decimal(1)
        curve.extend((day, round_money(equity * scale)) for day, equity in run.curve)
        all_fills.extend(run.fills)
        total_gaps += run.data_gaps
        total_cost += run.cost_paid
    return WalkForwardResult(
        instrument_id=instrument_id,
        folds=fold_results,
        curve=curve,
        final_equity=curve[-1][1] if curve else book.initial_cash,
        metrics=compute_metrics(curve, book.initial_cash),
        data_gaps=total_gaps,
        cost_paid=total_cost,
        fills=all_fills,
    )


@dataclass
class BenchmarkResult:
    key: str
    curve: list[tuple[date, Decimal]]
    metrics: dict[str, Decimal | float]


def _aggregate_equal_weight(
    curves: list[list[tuple[date, Decimal]]], sessions: list[date]
) -> list[tuple[date, Decimal]]:
    """Equal-weight composite of independent books (same total capital)."""
    if not curves:
        return []
    by_session: dict[date, list[Decimal]] = {}
    for curve in curves:
        for obs_date, value in curve:
            by_session.setdefault(obs_date, []).append(value)
    count = Decimal(len(curves))
    return [
        (session, round_money(sum(by_session[session], Decimal("0")) / count))
        for session in sessions
        if len(by_session.get(session, [])) == len(curves)
    ]


@dataclass
class BacktestRun:
    backtest_id: str
    config_digest: str
    config_path: str
    code_version: str
    spec_digest: str
    data_snapshot_id: str
    data_source: str
    range_start: date
    range_end: date
    sessions: list[date]
    instrument_ids: list[str]
    settings: BacktestSettings
    books: list[WalkForwardResult]
    benchmarks: list[BenchmarkResult]
    portfolio_metrics: dict[str, Decimal | float]
    provenance: dict[str, str]


def run_backtest(
    config: TradingConfig,
    providers: dict[str, MarketDataProvider],
    *,
    config_path: str,
    spec_digest: str,
    config_digest: str,
) -> BacktestRun:
    """Orchestrate the walk-forward backtest over every provided source."""
    bt = config.backtest
    if bt is None:
        raise ValueError("config has no [backtest] section")
    all_sessions = sorted(
        {session for provider in providers.values() for session in provider.sessions()}
    )
    sessions = [s for s in all_sessions if bt.range_start <= s <= bt.range_end]
    if not sessions:
        raise ValueError(
            f"no data sessions inside {bt.range_start}..{bt.range_end}; widen the config "
            f"backtest range or fetch deeper history"
        )
    providers_sorted = [
        provider
        for _, provider in sorted(
            providers.items(), key=lambda item: (item[1].data_snapshot_id(), item[0])
        )
    ]
    instrument_ids = [
        instrument.instrument_id
        for provider in providers_sorted
        for instrument in provider.instruments()
    ]
    if not instrument_ids:
        raise ValueError("no instruments to backtest")
    book = BookSettings(
        initial_cash=bt.initial_cash_usd,
        cash_yield_annual=bt.cash_yield_annual,
        cost=bt.cost,
        target_weight=Decimal(config.strategy.target_weight),
        quantity_step=_QUANTITY_EXP if config.universe.allow_fractional_orders else Decimal(1),
    )
    books = [
        walk_forward_instrument(
            provider, instrument.instrument_id, bt.range_start, bt.range_end, book, bt.walk_forward
        )
        for provider in providers_sorted
        for instrument in provider.instruments()
    ]
    common = set.intersection(*(set(day for day, _ in b.curve) for b in books))
    sessions = [day for day in sessions if day in common]
    if not sessions:
        raise ValueError("no common out-of-sample sessions for comparison")
    per_book_cash = bt.initial_cash_usd  # curves are averaged, so each starts with the same capital
    benchmarks: list[BenchmarkResult] = []
    for provider in providers_sorted:
        for instrument in provider.instruments():
            series = CloseSeries(
                _close_pairs(provider, instrument.instrument_id, bt.range_start, bt.range_end)
            )
            curve = run_passive_benchmark(
                series, sessions, per_book_cash, bt.cash_yield_annual, bt.cost, book.quantity_step
            )
            benchmarks.append(
                BenchmarkResult(
                    f"passive:{instrument.instrument_id}",
                    curve,
                    compute_metrics(curve, per_book_cash),
                )
            )
    cash_curve = run_cash_benchmark(sessions, bt.initial_cash_usd, bt.cash_yield_annual)
    momentum_composite = _aggregate_equal_weight([b.curve for b in books], sessions)
    passive_composite = _aggregate_equal_weight(
        [b.curve for b in benchmarks if b.key.startswith("passive:")], sessions
    )
    benchmarks += [
        BenchmarkResult("cash", cash_curve, compute_metrics(cash_curve, bt.initial_cash_usd)),
        BenchmarkResult(
            "momentum-composite",
            momentum_composite,
            compute_metrics(momentum_composite, bt.initial_cash_usd),
        ),
        BenchmarkResult(
            "passive-composite",
            passive_composite,
            compute_metrics(passive_composite, bt.initial_cash_usd),
        ),
    ]
    has_real = any(not i.is_synthetic for p in providers_sorted for i in p.instruments())
    has_synthetic = any(i.is_synthetic for p in providers_sorted for i in p.instruments())
    data_source = "mixed" if has_real and has_synthetic else ("real" if has_real else "synthetic")
    run_id = hashlib.sha256(
        (
            config_digest
            + spec_digest
            + bt.range_start.isoformat()
            + bt.range_end.isoformat()
            + "|".join(b.instrument_id for b in books)
            + ",".join(b.key for b in benchmarks)
            + str(bt.initial_cash_usd)
            + __version__
            + EXECUTION_VERSION
        ).encode("utf-8")
    ).hexdigest()[:32]
    return BacktestRun(
        backtest_id=run_id,
        config_digest=config_digest,
        config_path=config_path,
        code_version=__version__,
        spec_digest=spec_digest,
        data_snapshot_id=",".join(sorted({p.data_snapshot_id() for p in providers_sorted})),
        data_source=data_source,
        range_start=bt.range_start,
        range_end=bt.range_end,
        sessions=sessions,
        instrument_ids=instrument_ids,
        settings=bt,
        books=books,
        benchmarks=benchmarks,
        portfolio_metrics=compute_metrics(momentum_composite, bt.initial_cash_usd),
        provenance={
            "decision_timing": "one decision per session, at the session close",
            "execution": EXECUTION_VERSION + "; missing execution bar expires order",
            "quantity_step": str(book.quantity_step),
            "comparison_period": sessions[0].isoformat() + ".." + sessions[-1].isoformat(),
            "fold_composite": (
                "chain-linked research index of independently reset folds; not a live cash ledger"
            ),
            "composite_gaps": "missing component sessions omitted, never valued at zero",
            "costs": (
                f"fee {bt.cost.fee_rate} + slippage {bt.cost.slippage_rate} per fill notional"
            ),
            "cash_yield": (
                f"annual {bt.cash_yield_annual}, daily-compounded (paper-ledger convention)"
            ),
            "walk_forward": (
                f"fold_days={bt.walk_forward.fold_days} "
                f"min_train_days={bt.walk_forward.min_train_days} score={bt.walk_forward.score}"
            ),
            "leakage": "point-in-time slicing; unsorted/duplicate series raise "
            "LeakageError; folds fit on strictly earlier sessions",
            "determinism": (
                f"code {__version__}, spec {spec_digest}, config {config_digest}; Decimal "
                f"arithmetic with fixed factors"
            ),
            "data": (
                f"snapshots: {','.join(sorted({p.data_snapshot_id() for p in providers_sorted}))}"
            ),
        },
    )
