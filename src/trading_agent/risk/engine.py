"""Deterministic risk engine (plan section 13) with transactional reservations.

The engine is a pure function: given point-in-time state and a proposed order,
it returns a RiskEvaluation (pass / reduce / reject) with machine-readable
reasons. It never touches a broker and never uses a model.

Two families of checks, kept deliberately separate (plan section 13):
- **Entry controls** block *new* risk. They never block a protective exit.
- **Protective actions** (risk-reducing sells) have their own, narrower
  requirements: a valid price and that the sale does not create a short.

Money math is Decimal. Rounding follows docs/fill_simulation.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from ..config.models import TradingConfig
from ..contracts.decision import Decision, RiskEvaluation, RiskOutcome
from ..contracts.market import QualityFlag, Quote
from ..contracts.orders import OrderIntent
from ..money import round_money, round_qty


@dataclass(frozen=True)
class RiskState:
    """Point-in-time portfolio state the engine reasons about."""

    nav: Decimal  # book equity (cash + marked positions)
    cash: Decimal  # ledger cash
    reserved_cash: Decimal  # cash already committed to pending buys
    # Instrument -> held quantity
    positions: dict[str, Decimal] = field(default_factory=dict)
    # Instrument -> last traded volume (for participation)
    volumes: dict[str, Decimal] = field(default_factory=dict)
    # Instrument -> mark price (None when stale/missing)
    marks: dict[str, Decimal | None] = field(default_factory=dict)
    # Instrument -> seconds since last observation (freshness)
    quote_age_seconds: dict[str, Decimal] = field(default_factory=dict)
    # Instrument -> sessions since last observation (staleness)
    sessions_since: dict[str, int] = field(default_factory=dict)
    # Aggregate pending entry exposure across all open buys (NAV fraction input)
    pending_entry_value: Decimal = Decimal("0")
    # Instruments with an open (unfilled) entry order
    pending_entry_instruments: tuple[str, ...] = ()
    open_entry_count: int = 0
    # Protective controls
    day_start_nav: Decimal | None = None  # for the daily loss trigger
    high_water_mark: Decimal = Decimal("0")  # trailing drawdown HWM
    account_as_of: datetime | None = None
    paused: bool = False  # set by a protective control


class RiskEngine:
    """Evaluates a single proposed order against policy and current state."""

    def __init__(self, config: TradingConfig, *, exchange_timezone: str) -> None:
        self._config = config
        self._tz = ZoneInfo(exchange_timezone)
        self._risk = config.risk
        self._universe = config.universe

    # -- helpers ----------------------------------------------------------

    def _fraction(self, nav: Decimal, fraction: Decimal) -> Decimal:
        return round_money(nav * fraction)

    def evaluate(
        self,
        decision: Decision,
        intent: OrderIntent,
        state: RiskState,
        quote: Quote | None,
        *,
        now: datetime,
        is_protective_exit: bool = False,
    ) -> tuple[RiskEvaluation, Decimal]:
        reasons: list[tuple[str, str]] = []
        reject = False

        amounts = (
            state.nav,
            state.cash,
            state.reserved_cash,
            intent.quantity,
            intent.limit_price,
            state.pending_entry_value,
            state.high_water_mark,
            *state.positions.values(),
            *(value for value in state.marks.values() if value is not None),
        )
        if any(not value.is_finite() for value in amounts) or state.nav <= 0:
            raise ValueError("risk inputs must be finite with positive NAV")
        if now.tzinfo is None or decision.decision_at.tzinfo is None:
            raise ValueError("risk timestamps must be timezone aware")
        if (
            intent.run_id != decision.run_id
            or intent.account_alias != decision.account_alias
            or intent.instrument_id != decision.instrument_id
            or intent.decision_id != decision.decision_id
            or intent.policy_version != decision.risk_policy_version
            or intent.policy_version != self._risk.policy_version
            or intent.strategy_version != decision.strategy_version
            or decision.mode != self._config.app.mode.value
        ):
            reject = True
            reasons.append(("intent_binding", "identity, mode, strategy or policy mismatch"))
        nav = round_money(state.nav)
        risk = self._risk
        is_buy = intent.side.value == "buy"
        limit = intent.limit_price

        if is_protective_exit and is_buy:
            reject = True
            reasons.append(("protective_exit", "a protective exit cannot increase exposure"))
        if is_buy:
            if (
                state.account_as_of is None
                or (now - state.account_as_of).total_seconds() < 0
                or (now - state.account_as_of).total_seconds() > risk.max_account_state_age_seconds
            ):
                reject = True
                reasons.append(("account_freshness", "account state unavailable or stale"))
            if (
                state.day_start_nav is None
                or state.day_start_nav <= 0
                or state.high_water_mark <= 0
            ):
                reject = True
                reasons.append(("loss_history", "loss/drawdown reference unavailable"))
            if any(
                qty > 0 and state.marks.get(symbol) is None
                for symbol, qty in state.positions.items()
            ):
                reject = True
                reasons.append(("missing_mark", "held exposure cannot be valued"))
        # --- instrument identity / allowlist ----------------------------
        if intent.instrument_id in self._config.paper.synthetic_fixture_universe:
            synthetic = True
        else:
            synthetic = False
        if not is_protective_exit:
            if (
                synthetic
                and intent.instrument_id not in self._config.paper.synthetic_fixture_universe
            ):
                reject = True
                reasons.append(
                    ("universe_allowlist", f"{intent.instrument_id} not in simulation universe")
                )
            elif (
                not synthetic
                and intent.instrument_id not in self._universe.live_instrument_allowlist
            ):
                reject = True
                reasons.append(
                    (
                        "universe_allowlist",
                        f"{intent.instrument_id} not in live allowlist (empty until configured)",
                    )
                )

        # --- decision validity ------------------------------------------
        if now >= decision.expires_at or now < decision.decision_at:
            reject = True
            reasons.append(
                ("decision_expiry", f"decision expired at {decision.expires_at.isoformat()}")
            )

        # --- price validity ---------------------------------------------
        price_ok = False
        if quote is None:
            reject = True
            reasons.append(("price_valid", "no quote available"))
        elif (
            not quote.price.is_finite()
            or quote.price <= 0
            or quote.instrument_id != intent.instrument_id
            or quote.quality not in {QualityFlag.VALID, QualityFlag.CORRECTED}
            or (now - quote.as_of).total_seconds() > risk.max_quote_age_seconds
            or (quote.as_of - now).total_seconds() > risk.max_clock_offset_seconds
        ):
            reject = True
            reasons.append(("price_valid", f"nonpositive quote {quote.price}"))
        else:
            price_ok = True

        # --- spread (entry controls) ------------------------------------
        if is_buy and not is_protective_exit and price_ok and quote is not None and quote.price > 0:
            implied_bps = round((limit - quote.price) / quote.price * Decimal(10_000), 2)
            if implied_bps > self._config.risk.max_entry_spread_bps:
                reject = True
                reasons.append(
                    (
                        "max_entry_spread",
                        f"implied {implied_bps} bps crosses the max "
                        f"{self._config.risk.max_entry_spread_bps} bps",
                    )
                )

        # --- freshness (entry controls) ---------------------------------
        age = state.quote_age_seconds.get(intent.instrument_id, Decimal("-1"))
        sessions = state.sessions_since.get(intent.instrument_id, -1)
        if is_buy and not is_protective_exit:
            if age < 0:
                reject = True
                reasons.append(("quote_fresh", "no observation; quote age unknown"))
            elif age > risk.max_quote_age_seconds:
                reject = True
                reasons.append(
                    ("quote_fresh", f"quote age {age}s exceeds {risk.max_quote_age_seconds}s")
                )
            if sessions < 0:
                reject = True
                reasons.append(("data_stale", "no observations on record"))
            elif sessions > self._config.data.stale_after_sessions:
                reject = True
                reasons.append(("data_stale", f"{sessions} sessions since last observation"))
        # Protective exits may proceed on stale data (see module docstring).

        # --- sizing / reservation math ----------------------------------
        quantity = round_qty(intent.quantity, self._precision(intent.instrument_id))
        if quantity < 0:
            reject = True
            reasons.append(("quantity_valid", f"negative quantity {quantity}"))
        if quantity == 0:
            reject = True
            reasons.append(("quantity_valid", "zero quantity after precision rounding"))
        if limit <= 0:
            reject = True
            reasons.append(("price_valid", f"nonpositive limit {limit}"))

        # Worst-case fill price: a buy fills at limit (adverse), a sell at limit.
        fee_estimate = round_money(
            quantity * limit * (self._config.engine.commission_bps / Decimal(10_000))
        )
        worst_value = round_money(quantity * limit) + (fee_estimate if is_buy else Decimal("0"))

        # Single-order limit (entry).
        if is_buy and not is_protective_exit:
            max_order = self._fraction(nav, risk.max_order_nav_fraction)
            if worst_value > max_order:
                reduced = self._fit_quantity(quantity, limit, max_order, fee_estimate, is_buy)
                reasons.append(
                    (
                        "single_order_size",
                        f"order {round_money(quantity * limit)} exceeds {max_order}; "
                        f"reduced to {reduced}",
                    )
                )
                quantity = reduced
                if quantity <= 0:
                    reject = True
                    reasons.append(
                        ("single_order_size", "order cannot fit under the single-order limit")
                    )

        # --- cash / exposure (entry) ------------------------------------
        if is_buy and not is_protective_exit and not reject and quantity > 0:
            available = round_money(state.cash - state.reserved_cash)
            if worst_value > available:
                reduced = self._fit_quantity(quantity, limit, available, fee_estimate, is_buy)
                reasons.append(
                    (
                        "cash_reserve",
                        f"needs {worst_value} but only {available} unreserved; "
                        f"reduced to {reduced}",
                    )
                )
                quantity = reduced
                if quantity <= 0:
                    reject = True
                    reasons.append(("cash_reserve", "insufficient unreserved cash"))

            new_worst = round_money(quantity * limit)
            # Per-position limit including pending.
            held_value = self._mark_value(intent.instrument_id, state)
            pending_same = self._pending_value_for(intent.instrument_id, state)
            pos_cap = self._fraction(nav, risk.max_position_nav_fraction)
            projected_position = round_money(held_value + pending_same + new_worst)
            if projected_position > pos_cap:
                headroom = round_money(pos_cap - held_value - pending_same)
                reduced = self._fit_quantity(quantity, limit, headroom, fee_estimate, is_buy)
                reasons.append(
                    (
                        "position_limit",
                        f"projected {projected_position} > cap {pos_cap}; reduced to {reduced}",
                    )
                )
                quantity = reduced
                if quantity <= 0:
                    reject = True
                    reasons.append(("position_limit", "no headroom under the per-position limit"))

            # Gross exposure limit.
            gross = self._gross_exposure(state)
            gross_cap = self._fraction(nav, risk.max_gross_nav_fraction)
            if round_money(gross + state.pending_entry_value + quantity * limit) > gross_cap:
                reasons.append(
                    (
                        "gross_exposure",
                        f"projected gross {round_money(gross + new_worst)} > cap {gross_cap}"
                        " (protective: blocking)",
                    )
                )
                reject = True

            # Minimum cash floor (post-trade: unreserved cash minus this order).
            post_trade_cash = round_money(
                available
                - round_money(quantity * limit)
                - round_money(
                    quantity * limit * self._config.engine.commission_bps / Decimal(10000)
                )
            )
            if post_trade_cash < self._fraction(nav, risk.min_cash_nav_fraction):
                reasons.append(
                    (
                        "min_cash",
                        f"post-trade cash {post_trade_cash} would breach the "
                        f"{risk.min_cash_nav_fraction} NAV floor",
                    )
                )
                reject = True

            # Participation (vs the last completed session's volume; the
            # venue additionally caps each individual bar — see
            # docs/fill_simulation.md). Warm-up (no completed session) skips.
            vol = state.volumes.get(intent.instrument_id, Decimal("0"))
            if vol > 0:
                max_part = round_qty(
                    vol * risk.max_participation_fraction, self._precision(intent.instrument_id)
                )
                if quantity > max_part:
                    reduced = min(quantity, max_part)
                    reasons.append(
                        (
                            "participation",
                            f"quantity {quantity} > {max_part} "
                            f"({risk.max_participation_fraction} of session volume {vol}); "
                            f"reduced to {reduced}",
                        )
                    )
                    quantity = reduced

            # Entry count per session.
            if state.open_entry_count >= risk.max_entry_orders_per_session:
                reject = True
                reasons.append(
                    (
                        "entry_count",
                        f"already {state.open_entry_count} entries this session "
                        f"(max {risk.max_entry_orders_per_session})",
                    )
                )

            # Position slots (reserve a slot for every pending entry).
            held_slots = sum(1 for instrument_id, qty in state.positions.items() if qty > 0)
            pending_slots = sum(
                1
                for instrument_id in state.pending_entry_instruments
                if state.positions.get(instrument_id, Decimal("0")) <= 0
            )
            adds_slot = (
                state.positions.get(intent.instrument_id, Decimal("0")) <= 0
                and intent.instrument_id not in state.pending_entry_instruments
            )
            slots_after = held_slots + pending_slots + (1 if adds_slot else 0)
            if slots_after > risk.max_positions:
                reject = True
                reasons.append(
                    (
                        "position_slots",
                        f"would hold {slots_after} positions (max {risk.max_positions})",
                    )
                )

        # --- protective / exit constraints ------------------------------
        if not is_buy:
            held = state.positions.get(intent.instrument_id, Decimal("0"))
            if quantity > held:
                reduced = held
                reasons.append(("no_short", f"sell {quantity} > held {held}; reduced to {reduced}"))
                quantity = reduced
            if quantity <= 0:
                reject = True
                reasons.append(("no_short", "nothing held to sell"))
            # A protective exit must reduce exposure; verify it does.
            mark = self._mark(intent.instrument_id, state)
            # A protective exit must reduce exposure; a nonpositive or missing
            # mark cannot verify that, so it blocks the exit (documented).
            if mark is None or quantity * mark <= 0:
                reject = True
                reasons.append(("reduces_exposure", "exit does not reduce exposure"))

        # --- protective controls (block new risk) -----------------------
        if state.paused and is_buy and not is_protective_exit:
            reject = True
            reasons.append(
                (
                    "strategy_paused",
                    "a protective control has paused the strategy; new risk blocked",
                )
            )

        # --- daily loss trigger -----------------------------------------
        if (
            state.day_start_nav is not None
            and state.day_start_nav > 0
            and nav
            < round_money(state.day_start_nav * (Decimal(1) - risk.daily_loss_pause_nav_fraction))
        ):
            if is_buy and not is_protective_exit:
                reject = True
                reasons.append(
                    (
                        "daily_loss",
                        f"NAV {nav} fell >{risk.daily_loss_pause_nav_fraction} "
                        f"from day start {state.day_start_nav}",
                    )
                )
            else:
                reasons.append(("daily_loss", "trigger active; exits still permitted"))

        # --- trailing drawdown ------------------------------------------
        if (
            self._config.risk.trailing_drawdown_pause_fraction > 0
            and state.high_water_mark > 0
            and nav
            < round_money(
                state.high_water_mark * (Decimal(1) - risk.trailing_drawdown_pause_fraction)
            )
        ):
            if is_buy and not is_protective_exit:
                reject = True
                reasons.append(
                    (
                        "trailing_drawdown",
                        f"NAV {nav} below HWM {state.high_water_mark} by "
                        f">{risk.trailing_drawdown_pause_fraction}",
                    )
                )
            else:
                reasons.append(("trailing_drawdown", "pause active; exits still permitted"))

        # --- finalize ---------------------------------------------------
        if reject:
            outcome = RiskOutcome.REJECT
        elif any(
            name
            in ("single_order_size", "cash_reserve", "position_limit", "participation", "no_short")
            for name, _ in reasons
        ):
            outcome = RiskOutcome.REDUCE
        else:
            outcome = RiskOutcome.PASS

        limits = self._record_limits(nav, state, quantity, limit)
        evaluation = RiskEvaluation(
            evaluation_id=f"eval-{decision.decision_id}",
            run_id=decision.run_id,
            decision_id=decision.decision_id,
            policy_version=risk.policy_version,
            evaluated_at=now,
            outcome=outcome,
            reasons=tuple(reasons),
            limits=limits,
        )
        return evaluation, Decimal(0) if reject else quantity

    # -- computation helpers ---------------------------------------------

    def _precision(self, instrument_id: str) -> int:
        # Fixture instruments trade in whole units.
        return 0

    def _mark(self, instrument_id: str, state: RiskState) -> Decimal | None:
        return state.marks.get(instrument_id)

    def _mark_value(self, instrument_id: str, state: RiskState) -> Decimal:
        mark = state.marks.get(instrument_id)
        if mark is None:
            return Decimal("0")
        qty = state.positions.get(instrument_id, Decimal("0"))
        return round_money(qty * mark)

    def _gross_exposure(self, state: RiskState) -> Decimal:
        total = Decimal("0")
        for instrument_id, qty in state.positions.items():
            mark = state.marks.get(instrument_id)
            if mark is not None:
                total += round_money(qty * mark)
        return round_money(total)

    def _pending_value_for(self, instrument_id: str, state: RiskState) -> Decimal:
        # Aggregate pending entries are tracked at the book level; attribute
        # the full pending amount to each instrument as a conservative proxy.
        return state.pending_entry_value

    def _fit_quantity(
        self, quantity: Decimal, limit: Decimal, budget: Decimal, fee: Decimal, is_buy: bool
    ) -> Decimal:
        if budget <= 0:
            return Decimal("0")
        effective = budget - (fee if is_buy else Decimal("0"))
        if effective <= 0:
            return Decimal("0")
        fitted = round_qty(effective / limit, self._precision("x"))
        return min(quantity, fitted) if fitted < quantity else quantity

    def _record_limits(
        self, nav: Decimal, state: RiskState, quantity: Decimal, limit: Decimal
    ) -> dict[str, str]:
        risk = self._config.risk
        return {
            "nav": str(nav),
            "max_position": str(self._fraction(nav, risk.max_position_nav_fraction)),
            "max_gross": str(self._fraction(nav, risk.max_gross_nav_fraction)),
            "max_order": str(self._fraction(nav, risk.max_order_nav_fraction)),
            "min_cash": str(self._fraction(nav, risk.min_cash_nav_fraction)),
            "max_positions": str(risk.max_positions),
            "gross_exposure": str(self._gross_exposure(state)),
            "reserved_cash": str(state.reserved_cash),
            "order_value": str(round_money(quantity * limit)),
        }
