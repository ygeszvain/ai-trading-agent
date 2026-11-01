"""Readiness predicates are evidence checks, never a live activation certificate."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import Any

from ..config.models import TradingConfig
from ..contracts.decision import Decision, DecisionAction
from ..contracts.market import Quote as RiskQuote
from ..contracts.orders import OrderIntent, OrderSide, TimeInForce
from ..risk.engine import RiskEngine, RiskState
from .contracts import (
    Approval,
    Check,
    Grant,
    Intent,
    Readiness,
    State,
    digest,
    money_context,
    verify,
)

GATE_NAMES = (
    "selected_supervised_mode",
    "separate_live_enabled",
    "approved_nonzero_capital",
    "exact_account_binding",
    "approved_universe",
    "instrument_eligibility",
    "valid_risk_policy",
    "frozen_strategy",
    "healthy_data",
    "healthy_reconciliation",
    "healthy_audit",
    "fresh_account",
    "unexpired_owner_authorization",
    "explicit_resume",
    "not_revoked",
    "intent_bindings",
    "current_risk",
    "per_intent_owner_approval",
)


def fresh(at: datetime | None, now: datetime, seconds: float) -> bool:
    return at is not None and 0 <= (now - at).total_seconds() <= seconds


def config_for(state: State) -> TradingConfig:
    config = TradingConfig.model_validate_json(state.config_json)
    if config.llm.auth_token is not None or config.broker.account_number is not None:
        raise ValueError("mock state cannot contain runtime credentials or account numbers")
    return config


@money_context
def evaluate(
    state: State | None,
    *,
    now: datetime,
    intent: Intent | None = None,
    approval: Approval | None = None,
    require_resume: bool = True,
    excluding_cash: Decimal = Decimal(0),
    excluding_entry: int = 0,
    excluding_turnover: Decimal = Decimal(0),
) -> Readiness:
    if now.tzinfo is None:
        raise ValueError("readiness clock must be timezone aware")
    results: dict[str, tuple[bool, str]] = {
        name: (False, "missing verified evidence") for name in GATE_NAMES
    }

    def put(name: str, ok: bool, detail: str) -> None:
        results[name] = (bool(ok), detail)

    if state is not None:
        try:
            config = config_for(state)
        except ValueError:
            config = None
        grant = None
        try:
            if state.authorization is not None:
                grant = verify(state.authorization, Grant)
        except ValueError:
            pass
        if config is not None:
            policy_hash = digest(config.risk.model_dump(mode="json"))
            put(
                "selected_supervised_mode",
                config.app.mode.value == "supervised_live",
                "selected mode must be supervised_live",
            )
            put("separate_live_enabled", config.live.enabled, "flag is independent of mode/consent")
            put(
                "approved_nonzero_capital",
                config.live.approved_capital_usd > 0
                and grant is not None
                and config.live.approved_capital_usd == grant.capital,
                "exact signed MOCK capital binding; real approved capital remains zero",
            )
            put(
                "exact_account_binding",
                state.account_key == state.observed_account_key
                and grant is not None
                and grant.account_key == state.account_key
                and grant.account_alias == state.account_alias == config.broker.approved_account_id,
                "exact identity fingerprint and local alias; no account number displayed",
            )
            put(
                "approved_universe",
                bool(config.universe.live_instrument_allowlist)
                and grant is not None
                and tuple(config.universe.live_instrument_allowlist) == grant.universe,
                "exact frozen allowlist",
            )
            q = state.quote
            put(
                "instrument_eligibility",
                q.eligible
                and q.tradable
                and q.regular_session
                and q.asset_class == "unleveraged_etf"
                and fresh(state.eligibility_as_of, now, config.risk.max_account_state_age_seconds),
                "fresh tradability, session, class, precision and minimum quantity required",
            )
            put(
                "valid_risk_policy",
                grant is not None
                and grant.policy_hash == policy_hash
                and config.live.require_application_approval_per_intent
                and not config.live.resume_after_restart,
                "full risk policy digest, per-intent consent, no automatic restart",
            )
            put(
                "frozen_strategy",
                state.strategy_frozen
                and grant is not None
                and grant.strategy_hash == state.strategy_hash
                and state.strategy_manifest.digest() == state.strategy_hash
                and digest(json.loads(state.strategy_manifest.strategy_settings_json))
                == digest(config.strategy.model_dump(mode="json")),
                "immutable code/model/prompt/feature/parameter manifest hash",
            )
            for key in ("data", "reconciliation", "audit"):
                health = getattr(state, key)
                put(
                    "healthy_" + key,
                    health.status == "healthy"
                    and fresh(health.as_of, now, config.risk.max_account_state_age_seconds),
                    "healthy, current, non-future evidence required",
                )
            put(
                "fresh_account",
                fresh(state.account_as_of, now, config.risk.max_account_state_age_seconds),
                "fresh reconciled account state required",
            )
            put(
                "unexpired_owner_authorization",
                grant is not None
                and grant.starts_at <= now < grant.expires_at
                and config.live.owner_authorization_ref == grant.authorization_id
                and config.live.authorization_expires_at == grant.expires_at,
                "verified MOCK owner grant, scope, start and strict expiry",
            )
            put(
                "explicit_resume",
                not require_resume
                or (state.resumed and not state.paused and state.boot_id != "not-started"),
                "explicit current-boot resume after reconciliation; "
                "process restart never resumes itself",
            )
            put("not_revoked", not state.revoked, "durable revocation epoch checked independently")
            if intent is not None:
                binding = (
                    intent.domain == "M6_MOCK_ONLY"
                    and state.domain == "M6_MOCK_ONLY"
                    and intent.mode == config.app.mode.value
                    and intent.account_key == state.account_key
                    and intent.account_alias == state.account_alias
                    and intent.run_id == state.run_id
                    and intent.instrument == q.instrument
                    and intent.instrument in config.universe.live_instrument_allowlist
                    and intent.strategy_hash == state.strategy_hash
                    and intent.strategy_version == config.strategy.version
                    and intent.policy_hash == policy_hash
                    and intent.policy_version == config.risk.policy_version
                    and intent.risk_snapshot_hash == state.risk_hash()
                    and intent.created_at <= now < intent.expires_at
                    and intent.quantity >= q.minimum_quantity
                    and intent.limit_price % q.price_tick == 0
                    and intent.price_upper % q.price_tick == 0
                    and intent.price_lower <= q.price <= intent.price_upper
                )
                put(
                    "intent_bindings",
                    binding,
                    "exact intent, evidence, risk snapshot, versions, price bounds and lifetime",
                )
                try:
                    risk = risk_check(
                        state,
                        config,
                        intent,
                        now,
                        excluding_cash,
                        excluding_entry,
                        excluding_turnover,
                    )
                except (ValueError, ArithmeticError):
                    risk = {"passed": False, "reasons": "invalid or unavailable risk input"}
                put("current_risk", risk["passed"], str(risk["reasons"]))
                put(
                    "per_intent_owner_approval",
                    approval is not None
                    and grant is not None
                    and approval.intent_hash == intent.digest()
                    and approval.authorization_hash == grant.digest()
                    and approval.epoch == state.epoch
                    and approval.issued_at <= now < approval.expires_at <= intent.expires_at
                    and approval.expires_at <= grant.expires_at,
                    "signed exact intent/authorization hash, epoch, single use and strict expiry",
                )
    checks = tuple(
        Check(name=name, satisfied=value[0], detail=value[1]) for name, value in results.items()
    )
    return Readiness(
        mock_controls_satisfied=all(c.satisfied for c in checks),
        checks=checks
        + (
            Check(
                name="build_live_dispatch_disabled",
                satisfied=False,
                detail="No real transport, active authorization, deployed privileged runtime "
                "or upstream readiness; actual dispatch prohibited",
            ),
        ),
    )


def risk_check(
    state: State,
    config: TradingConfig,
    intent: Intent,
    now: datetime,
    excluding_cash: Decimal = Decimal(0),
    excluding_entry: int = 0,
    excluding_turnover: Decimal = Decimal(0),
) -> dict[str, Any]:
    q = state.quote
    if any(p.instrument != q.instrument and p.quantity > 0 for p in state.holdings):
        return {"passed": False, "reasons": "held instrument mark unavailable"}
    gross = sum((p.quantity * q.mark for p in state.holdings), Decimal(0))
    nav = min(state.cash + gross, config.live.approved_capital_usd)
    sleeve_cash = min(state.cash, max(Decimal(0), nav - gross))
    reserved = state.reserved_cash - excluding_cash
    if reserved < 0 or not fresh(q.as_of, now, config.risk.max_quote_age_seconds):
        return {"passed": False, "reasons": "invalid reservation or stale quote"}
    decision = Decision(
        intent.intent_id,
        intent.run_id,
        intent.account_alias,
        intent.mode,
        intent.instrument,
        intent.created_at,
        intent.expires_at,
        DecisionAction.ENTER if intent.side == "buy" else DecisionAction.EXIT,
        intent.target_weight,
        intent.strategy_version,
        None,
        intent.risk_snapshot_hash,
        "deterministic MOCK M6 risk",
        risk_policy_version=intent.policy_version,
    )
    order = OrderIntent(
        intent.intent_id,
        intent.run_id,
        intent.intent_id,
        intent.account_alias,
        intent.instrument,
        OrderSide(intent.side),
        intent.quantity,
        intent.price_upper,
        TimeInForce.DAY,
        intent.intent_id,
        intent.created_at,
        intent.policy_version,
        intent.strategy_version,
    )
    risk_state = RiskState(
        nav=nav,
        cash=sleeve_cash,
        reserved_cash=reserved,
        positions={p.instrument: p.quantity for p in state.holdings},
        marks={q.instrument: q.mark},
        volumes={q.instrument: q.volume},
        quote_age_seconds={q.instrument: Decimal(str((now - q.as_of).total_seconds()))},
        sessions_since={q.instrument: 0},
        pending_entry_value=reserved,
        pending_entry_instruments=(q.instrument,) if reserved else (),
        open_entry_count=state.entry_attempts - excluding_entry,
        day_start_nav=state.day_start_nav,
        high_water_mark=state.high_water_mark,
        account_as_of=state.account_as_of,
        paused=state.paused or state.revoked,
    )
    result, quantity = RiskEngine(config, exchange_timezone=config.app.exchange_timezone).evaluate(
        decision, order, risk_state, RiskQuote(q.instrument, q.price, q.as_of), now=now
    )
    worst = intent.quantity * intent.price_upper + intent.max_fee
    additional = intent.side != "buy" or (
        sleeve_cash - reserved - worst >= nav * config.risk.min_cash_nav_fraction
    )
    turnover = state.daily_turnover - excluding_turnover + intent.quantity * intent.price_upper
    return {
        "passed": result.passed
        and quantity == intent.quantity
        and additional
        and turnover <= nav * config.risk.max_planned_daily_turnover_nav_fraction,
        "reasons": result.reasons,
        "limits": result.limits,
        "evaluation_hash": digest(result.limits),
    }
