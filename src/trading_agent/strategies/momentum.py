"""Trend-momentum strategy v1 (rules: docs/strategy_momentum_v1.md).

Fully deterministic given the data snapshot and configuration. The rule is
documented *before* tuning per plan section 11; the M1 code must match the
document exactly.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from ..config.models import TradingConfig
from ..contracts.decision import Decision, DecisionAction
from ..contracts.market import Instrument, QualityFlag, Quote
from ..contracts.orders import OrderIntent, OrderSide, TimeInForce
from ..data.provider import MarketDataProvider
from ..money import round_qty

_DECISION_VALIDITY = timedelta(seconds=60)


@dataclass(frozen=True)
class DecisionContext:
    """Point-in-time inputs for one instrument-level decision."""

    run_id: str
    account_alias: str
    mode: str
    instrument: Instrument
    decision_at: datetime
    nav: Decimal
    position_quantity: Decimal
    position_value: Decimal
    quote: Quote | None
    provider: MarketDataProvider
    data_snapshot_id: str


@dataclass(frozen=True)
class StrategyOutput:
    """A decision plus its sized orders (empty for HOLD)."""

    decision: Decision
    orders: tuple[OrderIntent, ...] = ()


class MomentumStrategy:
    """The first deterministic strategy: 20-session momentum, long-only."""

    name = "trend-momentum"

    def __init__(self, config: TradingConfig) -> None:
        self._config = config
        self.version = config.strategy.version
        self._lookback = config.strategy.lookback_days
        self._entry = config.strategy.entry_momentum
        self._exit = config.strategy.exit_momentum
        self._target = config.strategy.target_weight
        self._slice = config.strategy.order_slice_weight
        self._spread_bps = config.engine.spread_bps
        self._tz = ZoneInfo(config.app.exchange_timezone)

    # ------------------------------------------------------------------

    def decide(self, ctx: DecisionContext) -> StrategyOutput:
        quote = ctx.quote
        closes = ctx.provider.recent_session_closes(
            ctx.instrument.instrument_id,
            ctx.decision_at.astimezone(self._tz).date(),
            self._lookback,
        )

        if len(closes) < self._lookback:
            return self._hold(
                ctx,
                f"insufficient history: {len(closes)}/{self._lookback} "
                "completed sessions (warm-up)",
                invalidation=("history-acquires",),
            )

        if quote is None or getattr(quote, "quality", None) is QualityFlag.STALE:
            return self._hold(
                ctx,
                "stale or missing market data; the strategy abstains rather than "
                "trade on old prices",
                invalidation=("data-refreshes",),
            )

        last_price = quote.price
        reference = closes[0].close  # 20-session return ending at the latest price
        momentum = last_price / reference - 1  # feature-space float-free Decimal

        has_position = ctx.position_quantity > 0
        if has_position:
            if momentum < self._exit:
                return self._exit_position(
                    ctx,
                    f"momentum {momentum:+.2%} < exit threshold {self._exit:+.2%}; position exited",
                )
            return self._hold(
                ctx,
                f"momentum {momentum:+.2%} within no-trade band "
                f"[{self._exit:+.2%}, {self._entry:+.2%}) while holding; HOLD",
            )

        if momentum > self._entry:
            return self._enter(
                ctx, last_price, f"momentum {momentum:+.2%} > entry threshold {self._entry:+.2%}"
            )

        return self._hold(
            ctx,
            f"momentum {momentum:+.2%} below entry threshold {self._entry:+.2%}; no position; HOLD",
        )

    # ------------------------------------------------------------- actions

    def _hold(
        self, ctx: DecisionContext, rationale: str, invalidation: tuple[str, ...] = ()
    ) -> StrategyOutput:
        return StrategyOutput(
            decision=self._decision(
                ctx, DecisionAction.HOLD, Decimal("0"), rationale, invalidation
            ),
            orders=(),
        )

    def _enter(self, ctx: DecisionContext, ref_price: Decimal, rationale: str) -> StrategyOutput:
        decision = self._decision(ctx, DecisionAction.ENTER, self._target, rationale, ())
        delta = self._target * ctx.nav - ctx.position_value
        if delta <= 0:
            return StrategyOutput(
                decision=self._decision(
                    ctx,
                    DecisionAction.HOLD,
                    Decimal("0"),
                    "target already met; HOLD",
                    (),
                ),
                orders=(),
            )
        orders = self._size_orders(ctx, decision, DecisionAction.ENTER, ref_price, delta)
        return StrategyOutput(decision=decision, orders=orders)

    def _exit_position(self, ctx: DecisionContext, rationale: str) -> StrategyOutput:
        decision = self._decision(ctx, DecisionAction.EXIT, Decimal("0"), rationale, ())
        if ctx.position_quantity <= 0:
            return StrategyOutput(
                decision=self._decision(
                    ctx,
                    DecisionAction.HOLD,
                    Decimal("0"),
                    "no position to exit; HOLD",
                    (),
                ),
                orders=(),
            )
        ref_price = ctx.quote.price if ctx.quote is not None else Decimal("0")
        delta = ctx.position_value
        if ref_price <= 0:
            return StrategyOutput(
                decision=decision, orders=()
            )  # cannot price an exit; risk will reject
        orders = self._size_orders(ctx, decision, DecisionAction.EXIT, ref_price, delta)
        return StrategyOutput(decision=decision, orders=orders)

    # ---------------------------------------------------------------- sizing

    def _size_orders(
        self,
        ctx: DecisionContext,
        decision: Decision,
        action: DecisionAction,
        ref_price: Decimal,
        delta_value: Decimal,
    ) -> tuple[OrderIntent, ...]:
        if ref_price <= 0:
            return ()
        precision = ctx.instrument.quantity_precision
        one_share_value = Decimal(1).scaleb(-precision) * ref_price
        orders: list[OrderIntent] = []
        remaining = delta_value
        index = 0
        while remaining >= one_share_value:
            slice_value = min(self._slice * ctx.nav, remaining)
            quantity = round_qty(slice_value / ref_price, precision)
            if quantity <= 0:
                break
            if action is DecisionAction.ENTER:
                limit = _round_price_up(
                    ref_price * (1 + self._spread_bps / Decimal(10_000)),
                    ctx.instrument.price_decimals,
                )
                side = OrderSide.BUY
            else:
                quantity = min(quantity, ctx.position_quantity)
                if quantity <= 0:
                    break
                limit = _round_price_down(
                    ref_price * (1 - self._spread_bps / Decimal(10_000)),
                    ctx.instrument.price_decimals,
                )
                side = OrderSide.SELL
            intent_id = _hash_id("intent", ctx.run_id, decision.decision_id, str(index))
            orders.append(
                OrderIntent(
                    intent_id=intent_id,
                    run_id=ctx.run_id,
                    decision_id=decision.decision_id,
                    account_alias=ctx.account_alias,
                    instrument_id=ctx.instrument.instrument_id,
                    side=side,
                    quantity=quantity,
                    limit_price=limit,
                    time_in_force=TimeInForce.DAY,
                    client_order_id=_hash_id("coi", ctx.run_id, intent_id),
                    created_at=ctx.decision_at,
                    policy_version=self._config.risk.policy_version,
                    strategy_version=self.version,
                )
            )
            remaining -= slice_value
            index += 1
            if index > 50:  # pathological safeguard; documented rules cannot exceed this
                break
        return tuple(orders)

    def _decision(
        self,
        ctx: DecisionContext,
        action: DecisionAction,
        target_weight: Decimal,
        rationale: str,
        invalidation: tuple[str, ...],
    ) -> Decision:
        decision_id = _hash_id(
            "decision",
            ctx.run_id,
            ctx.instrument.instrument_id,
            ctx.decision_at.isoformat(),
            self.version,
        )
        return Decision(
            decision_id=decision_id,
            run_id=ctx.run_id,
            account_alias=ctx.account_alias,
            mode=ctx.mode,
            instrument_id=ctx.instrument.instrument_id,
            decision_at=ctx.decision_at,
            expires_at=ctx.decision_at + _DECISION_VALIDITY,
            action=action,
            target_weight=target_weight,
            strategy_version=self.version,
            model_version=None,  # deterministic decision; no model in M1
            data_snapshot_id=ctx.data_snapshot_id,
            rationale=rationale,
            invalidation_conditions=invalidation,
            risk_policy_version=self._config.risk.policy_version,
        )


def _hash_id(prefix: str, *parts: str) -> str:
    return f"{prefix}-{hashlib.sha256('|'.join(parts).encode('utf-8')).hexdigest()[:32]}"


def _round_price_up(value: Decimal, decimals: int) -> Decimal:
    from decimal import ROUND_UP

    return value.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_UP)


def _round_price_down(value: Decimal, decimals: int) -> Decimal:
    from decimal import ROUND_DOWN

    return value.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_DOWN)
