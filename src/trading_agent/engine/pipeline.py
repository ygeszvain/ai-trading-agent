"""The end-to-end deterministic trading pipeline (plan sections 10, 14, 16, 17).

One session = one database transaction:

    bars -> [per instrument: decision -> risk -> reservation -> intent ->
    order -> submission] -> fills (decision bar) -> fills (close bar) ->
    session end (unknown reconciliation, working-order cancels, DAY
    settlement, reservation resolution, ledger-vs-venue reconciliation,
    accruals, baseline purchase, snapshots, activity events) -> COMMIT

Crash safety and idempotency:
- A crash (or Ctrl-C) rolls back the partial session; every row of a session
  commits together, so the database never contains a half-processed session.
- A session is "done" when the strategy book has a portfolio snapshot within
  that session's bounds. A restarted ``demo`` skips done sessions, so running
  it twice is a no-op: the same deterministic run id exists and everything it
  produced is already durable (no duplicated orders, fills, or cash flows).
- ``--reset`` explicitly deletes the run's rows and re-executes it.
- Every timestamp comes from the fixture exchange clock (never the wall
  clock), so a ``--reset`` re-run reproduces identical rows.

No model inference and no broker network calls happen anywhere in this path:
the strategy is deterministic and the venue is the local simulator
(docs/fill_simulation.md).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from ..config.models import TradingConfig
from ..contracts.broker import OrderRequest
from ..contracts.decision import Decision, DecisionAction
from ..contracts.market import MarketBar, QualityFlag
from ..contracts.orders import (
    EventOrigin,
    Fill,
    Order,
    OrderIntent,
    OrderSide,
    OrderType,
    ReservationKind,
    ReservationStatus,
)
from ..data.provider import SyntheticMarketProvider
from ..db.engine import create_app_engine, open_session
from ..db.migrate import run_migrations
from ..db.schema import (
    activity_events,
    broker_orders,
    decisions,
    fills,
    instruments,
    ledger_events,
    market_bars,
    order_events,
    order_intents,
    portfolio_snapshots,
    reconciliation_runs,
    reservations,
    risk_evaluations,
    runs,
    submission_attempts,
)
from ..exceptions import TradingAgentError
from ..execution.reconciliation import ReconciliationService
from ..execution.simulator import SimulatorBrokerAdapter
from ..fixtures.synthetic import FIXTURE_MODEL_VERSION, SyntheticMarket, build_synthetic_market
from ..ledger import Ledger
from ..money import round_money
from ..risk.engine import RiskEngine, RiskState
from ..strategies.baselines import CashBaseline, PassiveBaseline
from ..strategies.momentum import DecisionContext, MomentumStrategy
from .clock import ExchangeClock

ACCOUNT_ALIAS = "local-sim"
STRATEGY_BOOK = "strategy"
CASH_BOOK = "cash-baseline"
PASSIVE_BOOK = "passive-baseline"
BOOKS = (STRATEGY_BOOK, CASH_BOOK, PASSIVE_BOOK)

FEE_BPS_DENOMINATOR = Decimal("10000")


@dataclass
class RunResult:
    """Summary of a completed demo run (for the CLI and tests)."""

    run_id: str
    status: str
    resumed: bool
    sessions: int = 0
    decisions: int = 0
    holds: int = 0
    entries: int = 0
    exits: int = 0
    risk_rejections: int = 0
    orders: int = 0
    fills: int = 0
    partially_filled_orders: int = 0
    cancelled_orders: int = 0
    expired_orders: int = 0
    unknown_resolved: int = 0
    equity: dict[str, Decimal] = field(default_factory=dict)
    positions: dict[str, Decimal] = field(default_factory=dict)
    reconciliation: str = "unverified"
    report_path: str | None = None
    authority: str = "LIVE_NOT_AUTHORIZED"


class PipelineError(TradingAgentError):
    """A pipeline step failed; the session transaction was rolled back."""


class TradingPipeline:
    """Runs the deterministic offline demo end-to-end against the local database."""

    def __init__(self, config: TradingConfig) -> None:
        self._config = config
        self._engine = create_app_engine(config)
        run_migrations(config)
        self._clock = ExchangeClock(config.app.exchange_timezone, ())
        self._market_cache: SyntheticMarket | None = None

    # ------------------------------------------------------------- run id

    def _market(self) -> SyntheticMarket:
        if self._market_cache is None:
            self._market_cache = build_synthetic_market(self._config)
        return self._market_cache

    def run_id(self) -> str:
        """Deterministic run identity: covers everything that shapes the run.

        Includes the fixture model version, so a generator-shape change yields
        a new run id (a stale row in a reused database can never masquerade
        as the same run).
        """
        config = self._config
        basis = json.dumps(
            {
                "fixture": FIXTURE_MODEL_VERSION,
                "snapshot": self._market().data_snapshot_id,
                "universe": sorted(config.paper.synthetic_fixture_universe),
                "strategy": config.strategy.version,
                "policy": config.risk.policy_version,
                "capital": str(config.paper.initial_cash_usd),
                "commission_bps": str(config.engine.commission_bps),
                "spread_bps": str(config.engine.spread_bps),
                "cash_yield_annual": str(config.engine.cash_yield_annual),
                "scenarios": sorted(config.data.scenarios),
            },
            sort_keys=True,
        )
        return "sim-" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]

    # ----------------------------------------------------------------- run

    def run(self, *, reset: bool = False) -> RunResult:
        run_id = self.run_id()
        session = open_session(self._engine)
        try:
            status_row = session.execute(
                select(runs.c.status).where(runs.c.run_id == run_id)
            ).first()
            existing_status = status_row[0] if status_row is not None else None
            if existing_status == "completed" and not reset:
                result = self._summarize(session, run_id, resumed=False)
                result.status = "already-complete"
                return result
            resumed = existing_status is not None and existing_status != "completed" and not reset
            if existing_status is None or reset:
                self._reset_run(session, run_id)
                self._create_run(session, run_id)
            else:
                session.execute(
                    runs.update().where(runs.c.run_id == run_id).values(status="running")
                )
                session.flush()
            result = self._execute(session, run_id, resumed=resumed)
            session.commit()
            summary = self._summarize(session, run_id, resumed=resumed)
            result.sessions = summary.sessions
            result.decisions = summary.decisions
            result.holds = summary.holds
            result.entries = summary.entries
            result.exits = summary.exits
            result.risk_rejections = summary.risk_rejections
            result.orders = summary.orders
            result.fills = summary.fills
            result.partially_filled_orders = summary.partially_filled_orders
            result.cancelled_orders = summary.cancelled_orders
            result.expired_orders = summary.expired_orders
            result.unknown_resolved = summary.unknown_resolved
            result.equity = summary.equity
            result.reconciliation = summary.reconciliation
            return result
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
            self._engine.dispose()

    def _config_digest(self) -> str:
        payload = json.dumps(self._config.sanitized_summary(), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]

    def _create_run(self, session: Session, run_id: str) -> None:
        first_tick = self._clock.ticks(self._market().sessions[0])[0]
        session.execute(
            runs.insert().values(
                run_id=run_id,
                account_alias=ACCOUNT_ALIAS,
                mode=self._config.app.mode.value,
                config_digest=self._config_digest(),
                strategy_version=self._config.strategy.version,
                risk_policy_version=self._config.risk.policy_version,
                data_source=self._config.data.source,
                data_snapshot_id=self._market().data_snapshot_id,
                initial_cash=self._config.paper.initial_cash_usd,
                status="running",
                created_at=first_tick,
            )
        )
        for instrument_id in self._config.paper.synthetic_fixture_universe:
            session.execute(
                instruments.insert().values(
                    run_id=run_id,
                    instrument_id=instrument_id,
                    symbol=instrument_id,
                    asset_class="synthetic-equity",
                    price_decimals=2,
                    quantity_precision=0,
                    is_synthetic=True,
                    eligible=True,
                    notes=json.dumps([f"synthetic fixture instrument {instrument_id}"]),
                )
            )

    def _reset_run(self, session: Session, run_id: str) -> None:
        """Drop every row belonging to the run (explicit, documented, simulation-only)."""
        for table in (
            activity_events,
            ledger_events,
            portfolio_snapshots,
            reconciliation_runs,
            submission_attempts,
            order_events,
            fills,
            broker_orders,
            order_intents,
            reservations,
            risk_evaluations,
            decisions,
            market_bars,
            instruments,
        ):
            session.execute(delete(table).where(table.c.run_id == run_id))
        session.execute(runs.delete().where(runs.c.run_id == run_id))

    # ------------------------------------------------------------ execute

    def _execute(self, session: Session, run_id: str, *, resumed: bool) -> RunResult:
        config = self._config
        market = self._market()
        self._clock = ExchangeClock(config.app.exchange_timezone, market.sessions)
        provider = SyntheticMarketProvider(
            market, config.app.exchange_timezone, config.data.stale_after_sessions
        )
        strategy = MomentumStrategy(config)
        risk_engine = RiskEngine(config, exchange_timezone=config.app.exchange_timezone)
        cash_baseline = CashBaseline(config)
        passive_baseline = PassiveBaseline(config)

        first_tick = self._clock.ticks(market.sessions[0])[0]
        ledgers = {
            book: Ledger(
                session,
                run_id=run_id,
                portfolio_key=book,
                account_alias=ACCOUNT_ALIAS,
                initial_cash=config.paper.initial_cash_usd,
                initial_ts=first_tick,
            )
            for book in BOOKS
        }
        adapter = SimulatorBrokerAdapter(
            config,
            run_id=run_id,
            session=session,
            account_alias=ACCOUNT_ALIAS,
            initial_cash=config.paper.initial_cash_usd,
        )
        reconciliation = ReconciliationService(session, run_id, ACCOUNT_ALIAS)

        result = RunResult(run_id=run_id, status="running", resumed=resumed)
        # Day-start NAV for the first session is the initial capital; after
        # each completed session it is that session's final strategy equity.
        # On resume, recover it from the persisted snapshots.
        last_session_equity = (
            self._last_equity(session, run_id, STRATEGY_BOOK)
            if resumed
            else config.paper.initial_cash_usd
        )
        passive_purchased = self._passive_purchased(session, run_id) if resumed else False

        for session_date in market.sessions:
            if self._session_done(session, run_id, session_date):
                completed_equity = self._session_equity_at(session, run_id, session_date)
                if completed_equity is not None:
                    last_session_equity = completed_equity
                continue
            ticks = self._clock.ticks(session_date)
            open_ts, decision_ts, close_ts = ticks
            adapter.set_now(decision_ts)
            self._process_session(
                session=session,
                run_id=run_id,
                session_date=session_date,
                open_ts=open_ts,
                decision_ts=decision_ts,
                close_ts=close_ts,
                market=market,
                provider=provider,
                strategy=strategy,
                risk_engine=risk_engine,
                ledgers=ledgers,
                cash_baseline=cash_baseline,
                passive_baseline=passive_baseline,
                adapter=adapter,
                reconciliation=reconciliation,
                last_session_equity=last_session_equity,
                passive_purchased=passive_purchased,
            )
            passive_purchased = True
            equity = self._last_equity(session, run_id, STRATEGY_BOOK)
            if equity is not None:
                last_session_equity = equity
            result.sessions += 1
            session.commit()

        self._finalize(session, run_id, ledgers, adapter, reconciliation, result)
        result.status = "completed"
        return result

    # -------------------------------------------------------- run helpers

    def _session_done(self, session: Session, run_id: str, session_date: date) -> bool:
        start, end = self._clock.session_bounds(session_date)
        count = session.execute(
            select(func.count())
            .select_from(portfolio_snapshots)
            .where(
                portfolio_snapshots.c.run_id == run_id,
                portfolio_snapshots.c.portfolio_key == STRATEGY_BOOK,
                portfolio_snapshots.c.ts >= start,
                portfolio_snapshots.c.ts <= end,
            )
        ).scalar_one()
        return count > 0

    def _session_equity_at(
        self, session: Session, run_id: str, session_date: date
    ) -> Decimal | None:
        start, end = self._clock.session_bounds(session_date)
        row = session.execute(
            select(portfolio_snapshots.c.equity)
            .where(
                portfolio_snapshots.c.run_id == run_id,
                portfolio_snapshots.c.portfolio_key == STRATEGY_BOOK,
                portfolio_snapshots.c.ts >= start,
                portfolio_snapshots.c.ts <= end,
            )
            .order_by(portfolio_snapshots.c.ts.desc())
            .limit(1)
        ).first()
        return row[0] if row is not None else None

    def _last_equity(self, session: Session, run_id: str, book: str) -> Decimal | None:
        row = session.execute(
            select(portfolio_snapshots.c.equity)
            .where(
                portfolio_snapshots.c.run_id == run_id, portfolio_snapshots.c.portfolio_key == book
            )
            .order_by(portfolio_snapshots.c.ts.desc())
            .limit(1)
        ).first()
        return row[0] if row is not None else None

    def _passive_purchased(self, session: Session, run_id: str) -> bool:
        count = session.execute(
            select(func.count())
            .select_from(fills)
            .where(fills.c.run_id == run_id, fills.c.order_id == "passive-plan")
        ).scalar_one()
        return count > 0

    # ------------------------------------------------------- one session

    def _process_session(
        self,
        *,
        session: Session,
        run_id: str,
        session_date: date,
        open_ts: datetime,
        decision_ts: datetime,
        close_ts: datetime,
        market: SyntheticMarket,
        provider: SyntheticMarketProvider,
        strategy: MomentumStrategy,
        risk_engine: RiskEngine,
        ledgers: dict[str, Ledger],
        cash_baseline: CashBaseline,
        passive_baseline: PassiveBaseline,
        adapter: SimulatorBrokerAdapter,
        reconciliation: ReconciliationService,
        last_session_equity: Decimal | None,
        passive_purchased: bool,
    ) -> None:
        config = self._config
        strategy_ledger = ledgers[STRATEGY_BOOK]

        # 1) Persist today's bars (idempotent: composite PK, conflict is a no-op).
        for instrument_id in sorted(config.paper.synthetic_fixture_universe):
            for bar in market.bars.get(instrument_id, ()):
                if self._clock.session_of(bar.ts) != session_date:
                    continue
                insert = postgresql.insert(market_bars).values(
                    run_id=run_id,
                    instrument_id=bar.instrument_id,
                    ts=bar.ts,
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=bar.volume,
                    source_id=bar.source_id,
                    quality=bar.quality.value,
                    exchange_time=bar.exchange_time,
                )
                session.execute(insert.on_conflict_do_nothing())

        # 2) One decision per instrument at the decision tick; risk; orders.
        for instrument_id in sorted(config.paper.synthetic_fixture_universe):
            self._decide_one(
                session=session,
                run_id=run_id,
                instrument_id=instrument_id,
                market=market,
                provider=provider,
                strategy=strategy,
                risk_engine=risk_engine,
                ledger=strategy_ledger,
                adapter=adapter,
                decision_ts=decision_ts,
                last_session_equity=last_session_equity,
            )

        # 3) The venue works orders against the decision bar and the close bar.
        self._apply_bar(
            session=session,
            run_id=run_id,
            tick_ts=decision_ts,
            market=market,
            adapter=adapter,
            ledger=strategy_ledger,
        )
        self._apply_bar(
            session=session,
            run_id=run_id,
            tick_ts=close_ts,
            market=market,
            adapter=adapter,
            ledger=strategy_ledger,
        )

        # 4) Session end: settlement, reconciliation, accruals, snapshots.
        self._end_of_session(
            session=session,
            run_id=run_id,
            session_date=session_date,
            close_ts=close_ts,
            market=market,
            provider=provider,
            ledgers=ledgers,
            cash_baseline=cash_baseline,
            passive_baseline=passive_baseline,
            adapter=adapter,
            reconciliation=reconciliation,
            passive_purchased=passive_purchased,
        )

    # ------------------------------------------------------------ decision

    def _decide_one(
        self,
        *,
        session: Session,
        run_id: str,
        instrument_id: str,
        market: SyntheticMarket,
        provider: SyntheticMarketProvider,
        strategy: MomentumStrategy,
        risk_engine: RiskEngine,
        ledger: Ledger,
        adapter: SimulatorBrokerAdapter,
        decision_ts: datetime,
        last_session_equity: Decimal | None,
    ) -> None:
        config = self._config
        instrument = market.instruments[instrument_id]
        quote = provider.quote(instrument_id, decision_ts)

        # Point-in-time book state for the strategy book.
        marks: dict[str, Decimal | None] = {}
        for iid in config.paper.synthetic_fixture_universe:
            q = provider.quote(iid, decision_ts)
            marks[iid] = q.price if q is not None else None
        equity = self._book_equity(ledger, marks)
        nav = equity if equity is not None else ledger.cash
        pos_state = ledger.position(instrument_id)
        mark = marks[instrument_id]
        position_value = (
            round_money(pos_state.quantity * mark) if mark is not None else Decimal("0")
        )

        ctx = DecisionContext(
            run_id=run_id,
            account_alias=ACCOUNT_ALIAS,
            mode=config.app.mode.value,
            instrument=instrument,
            decision_at=decision_ts,
            nav=nav,
            position_quantity=pos_state.quantity,
            position_value=position_value,
            quote=quote,
            provider=provider,
            data_snapshot_id=provider.data_snapshot_id(),
        )
        output = strategy.decide(ctx)
        decision = output.decision

        session.execute(
            decisions.insert().values(
                decision_id=decision.decision_id,
                run_id=decision.run_id,
                account_alias=decision.account_alias,
                mode=decision.mode,
                instrument_id=decision.instrument_id,
                decision_at=decision.decision_at,
                expires_at=decision.expires_at,
                action=decision.action.value,
                target_weight=decision.target_weight,
                strategy_version=decision.strategy_version,
                model_version=decision.model_version,
                data_snapshot_id=decision.data_snapshot_id,
                rationale=decision.rationale,
                invalidation=json.dumps(list(decision.invalidation_conditions)),
                risk_policy_version=decision.risk_policy_version,
            )
        )
        self._emit(
            session=session,
            run_id=run_id,
            ts=decision_ts,
            origin=EventOrigin.STRATEGY,
            event_type=f"decision_{decision.action.value.lower()}",
            correlation={"decision": decision.decision_id, "instrument": instrument_id},
            payload={
                "action": decision.action.value,
                "rationale": decision.rationale,
                "target_weight": str(decision.target_weight),
                "instrument": instrument_id,
            },
        )

        if decision.action is DecisionAction.HOLD or not output.orders:
            return

        # One risk evaluation per intent, each against the freshest state
        # (sibling intents registered earlier are already pending). The
        # persisted risk_evaluations row is one per decision (schema
        # constraint): it aggregates the intent-level verdicts, worst outcome
        # wins, and reasons carry the intent index for traceability.
        day_start_nav = (
            last_session_equity
            if last_session_equity is not None
            else config.paper.initial_cash_usd
        )
        intent_evaluations: list[tuple[OrderIntent, Any, Decimal]] = []
        for intent in output.orders:
            state = self._risk_state(
                session=session,
                run_id=run_id,
                ledger=ledger,
                adapter=adapter,
                provider=provider,
                now=decision_ts,
                nav=nav,
                day_start_nav=day_start_nav,
            )
            evaluation, reduced_quantity = risk_engine.evaluate(
                decision,
                intent,
                state,
                quote,
                now=decision_ts,
                is_protective_exit=intent.side is OrderSide.SELL,
            )
            intent_evaluations.append((intent, evaluation, reduced_quantity))
            if evaluation.outcome.value == "reject":
                continue
            final_quantity = reduced_quantity if reduced_quantity > 0 else intent.quantity
            if final_quantity <= 0:
                continue
            order = self._materialize_order(intent, final_quantity, decision_ts)
            self._reserve(session, run_id, order, decision_ts)
            session.execute(
                order_intents.insert().values(
                    intent_id=order.intent_id,
                    run_id=order.run_id,
                    decision_id=decision.decision_id,
                    account_alias=order.account_alias,
                    instrument_id=order.instrument_id,
                    side=order.side.value,
                    quantity=final_quantity,
                    limit_price=order.limit_price,
                    time_in_force=order.time_in_force.value,
                    client_order_id=order.client_order_id,
                    created_at=decision_ts,
                    policy_version=intent.policy_version,
                    strategy_version=intent.strategy_version,
                )
            )
            adapter.register_order(order)
            adapter.set_now(decision_ts)
            submission = adapter.submit_order(
                OrderRequest(
                    instrument=order.instrument_id,
                    side=order.side.value,
                    quantity=final_quantity,
                    limit_price=order.limit_price,
                    time_in_force=order.time_in_force.value,
                    client_order_id=order.client_order_id,
                )
            )
            self._emit(
                session=session,
                run_id=run_id,
                ts=decision_ts,
                origin=EventOrigin.EXECUTION,
                event_type="submission_unknown"
                if submission.status.value == "unknown"
                else "order_submitted",
                correlation={
                    "decision": decision.decision_id,
                    "order": order.order_id,
                    "instrument": instrument_id,
                },
                payload={
                    "side": order.side.value,
                    "quantity": str(final_quantity),
                    "limit": str(order.limit_price),
                    "status": submission.status.value,
                    "order": order.order_id,
                    **(
                        {"note": submission.rejection_reason} if submission.rejection_reason else {}
                    ),
                },
            )

        if intent_evaluations:
            self._persist_decision_evaluation(
                session=session,
                run_id=run_id,
                decision=decision,
                instrument_id=instrument_id,
                decision_ts=decision_ts,
                intent_evaluations=intent_evaluations,
            )

    def _persist_decision_evaluation(
        self,
        *,
        session: Session,
        run_id: str,
        decision: Decision,
        instrument_id: str,
        decision_ts: datetime,
        intent_evaluations: list[tuple[OrderIntent, Any, Decimal]],
    ) -> None:
        """Persist the single risk-evaluation row for the decision.

        Aggregates per-intent verdicts: worst outcome wins (reject > reduce >
        pass); reasons are prefixed with the intent index so each check's
        provenance survives the one-row-per-decision constraint.
        """
        severity = {"reject": 2, "reduce": 1, "pass": 0}
        worst = max(intent_evaluations, key=lambda item: severity[item[1].outcome.value])
        _, worst_evaluation, _ = worst
        aggregated_reasons = [
            (f"intent{index}/{name}", detail)
            for index, (_, evaluation, _) in enumerate(intent_evaluations, start=1)
            for name, detail in evaluation.reasons
        ]
        session.execute(
            risk_evaluations.insert().values(
                evaluation_id=f"eval-{decision.decision_id}",
                run_id=run_id,
                decision_id=decision.decision_id,
                policy_version=worst_evaluation.policy_version,
                evaluated_at=decision_ts,
                outcome=worst_evaluation.outcome.value,
                reasons=json.dumps(aggregated_reasons),
                limits=json.dumps(worst_evaluation.limits),
            )
        )
        self._emit(
            session=session,
            run_id=run_id,
            ts=decision_ts,
            origin=EventOrigin.RISK,
            event_type=f"risk_{worst_evaluation.outcome.value}",
            correlation={"decision": decision.decision_id, "instrument": instrument_id},
            payload={
                "outcome": worst_evaluation.outcome.value,
                "intents_evaluated": str(len(intent_evaluations)),
                "reasons": "; ".join(f"{name}: {detail}" for name, detail in aggregated_reasons),
            },
        )

    def _materialize_order(self, intent: OrderIntent, quantity: Decimal, at: datetime) -> Order:
        order_id = hashlib.sha256(intent.intent_id.encode("utf-8")).hexdigest()[:32]
        return Order(
            order_id=order_id,
            run_id=intent.run_id,
            intent_id=intent.intent_id,
            client_order_id=intent.client_order_id,
            account_alias=intent.account_alias,
            instrument_id=intent.instrument_id,
            side=intent.side,
            order_type=OrderType.LIMIT,
            limit_price=intent.limit_price,
            quantity=quantity,
            time_in_force=intent.time_in_force,
            created_at=at,
            expires_at=None,
        )

    # -------------------------------------------------------- reservations

    def _reserve(self, session: Session, run_id: str, order: Order, at: datetime) -> None:
        """Create the transactional reservation before the order goes to the venue."""
        config = self._config
        fee_estimate = round_money(
            order.quantity * order.limit_price * config.engine.commission_bps / FEE_BPS_DENOMINATOR
        )
        if order.side is OrderSide.BUY:
            kind = ReservationKind.CASH
            amount = round_money(order.quantity * order.limit_price) + fee_estimate
        else:
            kind = ReservationKind.POSITION_SLOT
            amount = Decimal("1")
        reservation_id = hashlib.sha256(f"res|{order.order_id}".encode()).hexdigest()[:32]
        session.execute(
            reservations.insert().values(
                reservation_id=reservation_id,
                run_id=run_id,
                kind=kind.value,
                order_id=order.order_id,
                intent_id=order.intent_id,
                instrument_id=order.instrument_id,
                amount=amount,
                status=ReservationStatus.ACTIVE.value,
                reserved_at=at,
                resolved_at=None,
                fencing_token=0,
            )
        )

    def _sync_reservations(
        self,
        session: Session,
        run_id: str,
        order_ids: list[str],
        adapter: SimulatorBrokerAdapter,
        at: datetime,
    ) -> None:
        """Advance reservations with the order lifecycle.

        Full fill -> consumed; cancellation/expiry -> released; a partial fill
        shrinks a cash reservation to the remaining worst case; UNKNOWN and
        SUBMISSION_PENDING keep their reservation until resolved.
        """
        for order_id in dict.fromkeys(order_ids):
            order = adapter.order(order_id)
            if order is None:
                continue
            if order.status.value == "filled":
                self._set_reservation(
                    session, order_id, ReservationStatus.CONSUMED, at, new_amount=None
                )
            elif order.status.value in ("cancelled", "expired", "rejected"):
                self._set_reservation(
                    session, order_id, ReservationStatus.RELEASED, at, new_amount=None
                )
            elif order.side is OrderSide.BUY and order.filled_quantity > 0:
                remaining = order.remaining_quantity()
                fee_estimate = round_money(
                    remaining
                    * order.limit_price
                    * self._config.engine.commission_bps
                    / FEE_BPS_DENOMINATOR
                )
                new_amount = round_money(remaining * order.limit_price) + fee_estimate
                self._set_reservation(
                    session, order_id, ReservationStatus.ACTIVE, at, new_amount=new_amount
                )

    def _set_reservation(
        self,
        session: Session,
        order_id: str,
        status: ReservationStatus,
        at: datetime,
        *,
        new_amount: Decimal | None,
    ) -> None:
        values: dict[str, Any] = {"status": status.value, "resolved_at": at}
        if new_amount is not None:
            values["amount"] = new_amount
        session.execute(
            reservations.update()
            .where(
                reservations.c.order_id == order_id,
                reservations.c.status == ReservationStatus.ACTIVE.value,
            )
            .values(**values)
        )

    def _reserved_cash(self, session: Session, run_id: str) -> Decimal:
        amount: Decimal | None = session.execute(
            select(func.sum(reservations.c.amount)).where(
                reservations.c.run_id == run_id,
                reservations.c.kind == ReservationKind.CASH.value,
                reservations.c.status == ReservationStatus.ACTIVE.value,
            )
        ).scalar_one()
        return round_money(amount) if amount is not None else Decimal("0")

    # ----------------------------------------------------------- risk state

    def _risk_state(
        self,
        *,
        session: Session,
        run_id: str,
        ledger: Ledger,
        adapter: SimulatorBrokerAdapter,
        provider: SyntheticMarketProvider,
        now: datetime,
        nav: Decimal,
        day_start_nav: Decimal,
    ) -> RiskState:
        config = self._config
        positions: dict[str, Decimal] = {}
        marks: dict[str, Decimal | None] = {}
        volumes: dict[str, Decimal] = {}
        quote_age: dict[str, Decimal] = {}
        sessions_since: dict[str, int] = {}
        for instrument_id in config.paper.synthetic_fixture_universe:
            pos = ledger.position(instrument_id)
            if pos.quantity > 0:
                positions[instrument_id] = pos.quantity
            quote = provider.quote(instrument_id, now)
            marks[instrument_id] = quote.price if quote is not None else None
            if quote is not None:
                quote_age[instrument_id] = Decimal(str((now - quote.as_of).total_seconds()))
            sessions_since[instrument_id] = provider.sessions_since_observation(instrument_id, now)
            session_vol = provider.session_volume(instrument_id, now)
            volumes[instrument_id] = session_vol if session_vol is not None else Decimal("0")

        pending_value = Decimal("0")
        pending_instruments: list[str] = []
        open_entry_count = 0
        for order_id in adapter.open_order_ids():
            order = adapter.order(order_id)
            if order is None or order.side is not OrderSide.BUY:
                continue
            open_entry_count += 1
            pending_value += round_money(order.remaining_quantity() * order.limit_price)
            if order.instrument_id not in pending_instruments:
                pending_instruments.append(order.instrument_id)

        high_water_mark = max(nav, self._historical_equity_max(session, run_id))
        return RiskState(
            nav=nav,
            cash=ledger.cash,
            reserved_cash=self._reserved_cash(session, run_id),
            positions=positions,
            volumes=volumes,
            marks=marks,
            quote_age_seconds=quote_age,
            sessions_since=sessions_since,
            pending_entry_value=round_money(pending_value),
            pending_entry_instruments=tuple(pending_instruments),
            open_entry_count=open_entry_count,
            day_start_nav=day_start_nav,
            high_water_mark=high_water_mark,
            paused=False,
        )

    def _historical_equity_max(self, session: Session, run_id: str) -> Decimal:
        maximum: Decimal | None = session.execute(
            select(func.max(portfolio_snapshots.c.equity)).where(
                portfolio_snapshots.c.run_id == run_id,
                portfolio_snapshots.c.portfolio_key == STRATEGY_BOOK,
            )
        ).scalar_one()
        return maximum if maximum is not None else Decimal("0")

    def _book_equity(self, ledger: Ledger, marks: dict[str, Decimal | None]) -> Decimal | None:
        """Book NAV = cash + sum(position value at latest mark).

        A position whose latest mark is unavailable contributes zero (the
        website renders it as MISSING, never a fabricated price).
        """
        total = ledger.cash
        for instrument_id, state in ledger.positions.items():
            if state.quantity <= 0:
                continue
            mark = marks.get(instrument_id)
            if mark is not None:
                total += round_money(state.quantity * mark)
        return round_money(total)

    # ----------------------------------------------------------------- fills

    def _apply_bar(
        self,
        *,
        session: Session,
        run_id: str,
        tick_ts: datetime,
        market: SyntheticMarket,
        adapter: SimulatorBrokerAdapter,
        ledger: Ledger,
    ) -> None:
        for instrument_id in sorted(self._config.paper.synthetic_fixture_universe):
            for bar in market.bars.get(instrument_id, ()):
                if bar.ts != tick_ts:
                    continue
                fills, changed = adapter.on_bar(bar)
                for fill in fills:
                    if ledger.apply_fill(fill, at=fill.ts):
                        ledger.flush()
                        self._emit(
                            session=session,
                            run_id=run_id,
                            ts=fill.ts,
                            origin=EventOrigin.EXECUTION,
                            event_type="fill",
                            correlation={
                                "order": fill.order_id,
                                "instrument": fill.instrument_id,
                                "fill": fill.fill_id,
                            },
                            payload={
                                "side": fill.side.value,
                                "quantity": str(fill.quantity),
                                "price": str(fill.price),
                                "fee": str(fill.fee),
                                "fill": fill.fill_id,
                            },
                        )
                if changed:
                    self._sync_reservations(session, run_id, changed, adapter, tick_ts)
                    for order_id in changed:
                        status = adapter.order_status(order_id)
                        if status is None:
                            continue
                        order = adapter.order(order_id)
                        self._emit(
                            session=session,
                            run_id=run_id,
                            ts=tick_ts,
                            origin=EventOrigin.EXECUTION,
                            event_type=f"order_{status.value}",
                            correlation={"order": order_id},
                            payload={
                                "status": status.value,
                                "filled": str(order.filled_quantity) if order is not None else "0",
                            },
                        )

    # ----------------------------------------------------- session close

    def _end_of_session(
        self,
        *,
        session: Session,
        run_id: str,
        session_date: date,
        close_ts: datetime,
        market: SyntheticMarket,
        provider: SyntheticMarketProvider,
        ledgers: dict[str, Ledger],
        cash_baseline: CashBaseline,
        passive_baseline: PassiveBaseline,
        adapter: SimulatorBrokerAdapter,
        reconciliation: ReconciliationService,
        passive_purchased: bool,
    ) -> None:
        adapter.set_now(close_ts)

        # 1) Resolve UNKNOWN submissions against the venue's authoritative state.
        for order_id in adapter.reconcile_unknown(close_ts):
            self._emit(
                session=session,
                run_id=run_id,
                ts=close_ts,
                origin=EventOrigin.RECONCILIATION,
                event_type="unknown_resolved",
                correlation={"order": order_id},
                payload={"note": "venue confirms the order was accepted; reservations retained"},
            )

        # 2) Entry orders are working orders: withdraw at the close (a request,
        #    not a confirmation). Protective exits are left resting to expire.
        for order_id in list(adapter.open_order_ids()):
            order = adapter.order(order_id)
            if order is None or order.side is not OrderSide.BUY:
                continue
            adapter.set_now(close_ts)
            adapter.cancel_order(order_id)
            self._emit(
                session=session,
                run_id=run_id,
                ts=close_ts,
                origin=EventOrigin.EXECUTION,
                event_type="cancel_requested",
                correlation={"order": order_id},
                payload={
                    "note": "entry working-age expired; cancel requested (not a confirmation)"
                },
            )

        # 3) Settle: confirm pending cancels, DAY-expire the rest.
        for order_id in adapter.end_of_session(close_ts):
            order = adapter.order(order_id)
            status = order.status.value if order is not None else "expired"
            self._emit(
                session=session,
                run_id=run_id,
                ts=close_ts,
                origin=EventOrigin.EXECUTION,
                event_type="cancel_confirmed" if status == "cancelled" else f"order_{status}",
                correlation={"order": order_id},
                payload={
                    "status": status,
                    "note": "cancel confirmed at close (fills retained)"
                    if status == "cancelled"
                    else "DAY time-in-force expired (reservation released)",
                },
            )
        self._sync_reservations(
            session, run_id, adapter.terminal_order_ids_any(), adapter, close_ts
        )

        # 4) Documented daily cash yield, credited before the reconciliation.
        # The strategy book's credit is generated by the simulated venue
        # (the source of account-level yield events, as a real broker would
        # credit interest); the baseline books accrue the same convention on
        # their own books. Both use the identical Decimal factor and rounding.
        credit = adapter.cash_yield_credit(close_ts)
        if credit > 0:
            ledgers[STRATEGY_BOOK].apply_cash_flow(
                credit,
                kind="cash_yield",
                ts=close_ts,
                note="venue daily cash-yield credit",
                ref_type="venue",
                ref_id=f"yield-{session_date.isoformat()}",
            )
            ledgers[STRATEGY_BOOK].flush()
        for book in (CASH_BOOK, PASSIVE_BOOK):
            ledger = ledgers[book]
            accrual = cash_baseline.accrual(ledger.cash)
            if accrual > 0:
                ledger.apply_cash_flow(
                    accrual,
                    kind="cash_yield",
                    ts=close_ts,
                    note="baseline daily cash yield (same documented convention)",
                    ref_id=f"yield-{session_date.isoformat()}",
                )
            ledger.flush()

        # 5) Passive baseline: one equal-weight purchase at the first open.
        if not passive_purchased:
            self._passive_purchase(session, run_id, market, passive_baseline, ledgers, session_date)

        # 6) Ledger-vs-venue reconciliation for the strategy book.
        recon = reconciliation.run_session_end(
            close_ts, strategy_ledger=ledgers[STRATEGY_BOOK], adapter=adapter
        )
        self._emit(
            session=session,
            run_id=run_id,
            ts=close_ts,
            origin=EventOrigin.RECONCILIATION,
            event_type="reconciliation",
            correlation={"run": run_id},
            payload={
                "status": recon.status,
                "session": session_date.isoformat(),
                "differences": json.dumps(recon.differences),
            },
        )

        # 7) Persist one snapshot per book at the close.
        marks = self._session_marks(provider, close_ts)
        for book, ledger in ledgers.items():
            reconciliation_status = recon.status if book == STRATEGY_BOOK else "unverified"
            snapshot = ledger.snapshot(
                as_of=close_ts, marks=marks, reconciliation_status=reconciliation_status
            )
            self._persist_snapshot(session, run_id, snapshot)

    def _passive_purchase(
        self,
        session: Session,
        run_id: str,
        market: SyntheticMarket,
        passive_baseline: PassiveBaseline,
        ledgers: dict[str, Ledger],
        session_date: date,
    ) -> None:
        start, _ = self._clock.session_bounds(session_date)
        open_bars: dict[str, MarketBar] = {}
        for instrument_id in self._config.engine.passive_basket:
            bars = [bar for bar in market.bars.get(instrument_id, ()) if bar.ts >= start]
            if bars:
                open_bars[instrument_id] = min(bars, key=lambda bar: bar.ts)
        plan = passive_baseline.purchase_plan(self._config.paper.initial_cash_usd, open_bars)
        if not plan.legs:
            return
        fee_rate = self._config.engine.commission_bps / FEE_BPS_DENOMINATOR
        for instrument_id, quantity, limit in plan.legs:
            fee = round_money(quantity * limit * fee_rate)
            fill = Fill(
                fill_id=hashlib.sha256(f"passive|{run_id}|{instrument_id}".encode()).hexdigest()[
                    :32
                ],
                run_id=run_id,
                order_id="passive-plan",
                instrument_id=instrument_id,
                side=OrderSide.BUY,
                ts=min(bar.ts for bar in open_bars.values())
                if open_bars
                else self._clock.ticks(session_date)[0],
                quantity=quantity,
                price=limit,
                fee=fee,
                raw_fill_id=f"passive-{run_id}-{instrument_id}",
                source="simulator",
            )
            if ledgers[PASSIVE_BOOK].apply_fill(fill, at=fill.ts):
                ledgers[PASSIVE_BOOK].flush()
                self._emit(
                    session=session,
                    run_id=run_id,
                    ts=fill.ts,
                    origin=EventOrigin.SYSTEM,
                    event_type="passive_purchase",
                    correlation={"instrument": instrument_id},
                    payload={
                        "note": "passive baseline buys the basket once at the first open",
                        "quantity": str(quantity),
                        "price": str(limit),
                        "fee": str(fee),
                    },
                )

    def _session_marks(
        self, provider: SyntheticMarketProvider, close_ts: datetime
    ) -> dict[str, tuple[Decimal | None, datetime | None, QualityFlag]]:
        marks: dict[str, tuple[Decimal | None, datetime | None, QualityFlag]] = {}
        for instrument in provider.instruments():
            quote = provider.quote(instrument.instrument_id, close_ts)
            if quote is None:
                marks[instrument.instrument_id] = (None, None, QualityFlag.MISSING)
            else:
                marks[instrument.instrument_id] = (quote.price, quote.as_of, quote.quality)
        return marks

    def _persist_snapshot(self, session: Session, run_id: str, snapshot: Any) -> None:
        positions = [
            {
                "instrument_id": p.instrument_id,
                "quantity": str(p.quantity),
                "average_cost": str(p.average_cost),
                "mark": str(p.mark) if p.mark is not None else None,
                "mark_as_of": p.mark_as_of.isoformat() if p.mark_as_of is not None else None,
                "mark_stale": p.mark_stale,
            }
            for p in snapshot.positions
        ]
        session.execute(
            portfolio_snapshots.insert().values(
                run_id=run_id,
                portfolio_key=snapshot.portfolio_key,
                ts=snapshot.as_of,
                equity=snapshot.equity,
                cash=snapshot.cash,
                gross_exposure=snapshot.gross_exposure,
                positions=json.dumps(positions),
                reconciliation_status=snapshot.reconciliation_status,
            )
        )

    # ---------------------------------------------------------- finalize

    def _finalize(
        self,
        session: Session,
        run_id: str,
        ledgers: dict[str, Ledger],
        adapter: SimulatorBrokerAdapter,
        reconciliation: ReconciliationService,
        result: RunResult,
    ) -> None:
        completed_at = self._clock.ticks(self._market().sessions[-1])[2]
        session.execute(
            runs.update()
            .where(runs.c.run_id == run_id)
            .values(status="completed", completed_at=completed_at)
        )
        for book in BOOKS:
            result.equity[book] = self._last_equity(session, run_id, book) or Decimal("0")
        for instrument_id in self._config.paper.synthetic_fixture_universe:
            pos = ledgers[STRATEGY_BOOK].position(instrument_id)
            if pos.quantity > 0:
                result.positions[f"position_{instrument_id}"] = pos.quantity
        result.reconciliation = "consistent" if reconciliation.healthy() else "needs-review"
        result.authority = self._config.authority()

    # ------------------------------------------------------- activity feed

    def _emit(
        self,
        *,
        session: Session,
        run_id: str,
        ts: datetime,
        origin: EventOrigin,
        event_type: str,
        correlation: dict[str, str],
        payload: dict[str, str],
    ) -> int:
        cursor = self._next_cursor(session, run_id)
        event_id = f"evt-{run_id}-{cursor}"
        session.execute(
            activity_events.insert().values(
                event_id=event_id,
                cursor=cursor,
                run_id=run_id,
                account_alias=ACCOUNT_ALIAS,
                mode=self._config.app.mode.value,
                ts=ts,
                origin=origin.value,
                event_type=event_type,
                correlation=json.dumps(correlation),
                payload=json.dumps(payload),
            )
        )
        return cursor + 1

    def _next_cursor(self, session: Session, run_id: str) -> int:
        cursor: int | None = session.execute(
            select(func.max(activity_events.c.cursor)).where(activity_events.c.run_id == run_id)
        ).scalar_one()
        return (cursor or 0) + 1

    # ---------------------------------------------------------- summary

    def _summarize(self, session: Session, run_id: str, *, resumed: bool) -> RunResult:
        result = RunResult(run_id=run_id, status="completed", resumed=resumed)
        result.sessions = session.execute(
            select(func.count(func.distinct(portfolio_snapshots.c.ts))).where(
                portfolio_snapshots.c.run_id == run_id,
                portfolio_snapshots.c.portfolio_key == STRATEGY_BOOK,
            )
        ).scalar_one()
        result.decisions = session.execute(
            select(func.count()).select_from(decisions).where(decisions.c.run_id == run_id)
        ).scalar_one()
        result.holds = session.execute(
            select(func.count())
            .select_from(decisions)
            .where(decisions.c.run_id == run_id, decisions.c.action == "HOLD")
        ).scalar_one()
        result.entries = session.execute(
            select(func.count())
            .select_from(decisions)
            .where(decisions.c.run_id == run_id, decisions.c.action == "ENTER")
        ).scalar_one()
        result.exits = session.execute(
            select(func.count())
            .select_from(decisions)
            .where(decisions.c.run_id == run_id, decisions.c.action == "EXIT")
        ).scalar_one()
        result.risk_rejections = session.execute(
            select(func.count())
            .select_from(risk_evaluations)
            .where(
                risk_evaluations.c.run_id == run_id,
                risk_evaluations.c.outcome == "reject",
            )
        ).scalar_one()
        result.orders = session.execute(
            select(func.count()).select_from(broker_orders).where(broker_orders.c.run_id == run_id)
        ).scalar_one()
        result.fills = session.execute(
            select(func.count()).select_from(fills).where(fills.c.run_id == run_id)
        ).scalar_one()
        # Orders that *ever reached* partially_filled (they end filled/
        # cancelled/expired, so the terminal status alone always reads 0).
        result.partially_filled_orders = session.execute(
            select(func.count(func.distinct(order_events.c.order_id))).where(
                order_events.c.run_id == run_id,
                order_events.c.to_status == "partially_filled",
            )
        ).scalar_one()
        result.cancelled_orders = session.execute(
            select(func.count())
            .select_from(broker_orders)
            .where(broker_orders.c.run_id == run_id, broker_orders.c.status == "cancelled")
        ).scalar_one()
        result.expired_orders = session.execute(
            select(func.count())
            .select_from(broker_orders)
            .where(broker_orders.c.run_id == run_id, broker_orders.c.status == "expired")
        ).scalar_one()
        result.unknown_resolved = session.execute(
            select(func.count())
            .select_from(order_events)
            .where(
                order_events.c.run_id == run_id,
                order_events.c.to_status == "acknowledged",
                order_events.c.reason.like("reconciliation%"),
            )
        ).scalar_one()
        for book in BOOKS:
            result.equity[book] = self._last_equity(session, run_id, book) or Decimal("0")
        recon = session.execute(
            select(reconciliation_runs.c.status)
            .where(reconciliation_runs.c.run_id == run_id)
            .order_by(reconciliation_runs.c.completed_at.desc())
            .limit(1)
        ).first()
        result.reconciliation = recon[0] if recon is not None else "unverified"
        return result
