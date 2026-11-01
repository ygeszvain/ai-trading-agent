"""Fictional $1,000 feasibility fixture; no change to runtime-approved capital."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from ..config.loading import load_config
from .contracts import (
    Approval,
    Grant,
    Health,
    Intent,
    Quote,
    Resume,
    State,
    StrategyManifest,
    digest,
    mock_sign,
)

NOW = datetime(2026, 11, 1, 15, tzinfo=UTC)
KEY = digest("M6 fictional account, not a brokerage identity")


def state_fixture(now: datetime = NOW) -> State:
    config = load_config(
        Path(__file__).resolve().parents[3] / "config/simulation.yaml", env={}
    ).model_dump(mode="json")
    config["app"]["mode"] = "supervised_live"
    config["broker"]["provider"] = "robinhood"
    config["broker"]["approved_account_id"] = "m6-fixture"
    config["broker"]["allowlisted_tool_schema_digest"] = digest("MOCK schemas only")
    config["universe"]["live_instrument_allowlist"] = ["MOCK_ETF"]
    config["live"].update(
        enabled=True,
        approved_capital_usd="1000",
        owner_authorization_ref="MOCK-grant",
        authorization_expires_at=(now + timedelta(hours=1)).isoformat(),
    )
    from ..config.models import TradingConfig

    cfg = TradingConfig.model_validate(config)
    manifest = StrategyManifest(
        code_hash=digest("fixture-code"),
        dependency_hash=digest("fixture-dependencies"),
        model_hash=digest("no-model"),
        prompt_hash=digest("no-prompt"),
        feature_hash=digest("fixture-features"),
        strategy_settings_json=cfg.strategy.model_dump_json(),
    )
    strategy_hash = manifest.digest()
    grant = Grant(
        authorization_id="MOCK-grant",
        account_alias="m6-fixture",
        account_key=KEY,
        capital=Decimal(1000),
        universe=("MOCK_ETF",),
        policy_hash=digest(cfg.risk.model_dump(mode="json")),
        strategy_hash=strategy_hash,
        starts_at=now,
        expires_at=now + timedelta(hours=1),
    )
    health = Health(status="healthy", as_of=now)
    return State(
        account_alias="m6-fixture",
        account_key=KEY,
        observed_account_key=KEY,
        run_id="m6-demo",
        config_json=cfg.model_dump_json(),
        authorization=mock_sign(grant),
        strategy_hash=strategy_hash,
        strategy_frozen=True,
        strategy_manifest=manifest,
        data=health,
        reconciliation=health,
        audit=health,
        eligibility_as_of=now,
        account_as_of=now,
        quote=Quote(
            instrument="MOCK_ETF",
            price=Decimal(5),
            mark=Decimal(5),
            volume=Decimal(1000000),
            as_of=now,
            eligible=True,
            asset_class="unleveraged_etf",
            tradable=True,
            regular_session=True,
        ),
        cash=Decimal(1000),
        high_water_mark=Decimal(1000),
        day_start_nav=Decimal(1000),
    )


def intent_fixture(state: State, *, suffix: str = "one", now: datetime = NOW) -> Intent:
    from .readiness import config_for

    cfg = config_for(state)
    return Intent(
        intent_id="mock-intent-" + suffix,
        run_id=state.run_id,
        account_alias=state.account_alias,
        account_key=state.account_key,
        instrument=state.quote.instrument,
        side="buy",
        quantity=Decimal(2),
        target_weight=Decimal("0.01"),
        limit_price=Decimal(5),
        price_lower=Decimal("4.99"),
        price_upper=Decimal("5.00"),
        max_fee=Decimal("0.01"),
        strategy_version=cfg.strategy.version,
        policy_version=cfg.risk.policy_version,
        strategy_hash=state.strategy_hash,
        policy_hash=digest(cfg.risk.model_dump(mode="json")),
        evidence_hashes=(digest("fictional evidence"),),
        risk_snapshot_hash=state.risk_hash(),
        created_at=now,
        expires_at=now + timedelta(minutes=1),
    )


def approval_fixture(state: State, intent: Intent, *, now: datetime = NOW) -> Approval:
    from .contracts import verify

    assert state.authorization is not None
    grant = verify(state.authorization, Grant)
    return Approval(
        approval_id="mock-approval-" + intent.intent_id,
        intent_hash=intent.digest(),
        authorization_hash=grant.digest(),
        epoch=state.epoch,
        issued_at=now,
        expires_at=intent.expires_at,
    )


def resume_fixture(state: State, *, now: datetime = NOW) -> Resume:
    return Resume(
        resume_id="mock-resume-" + str(state.revision),
        state_revision=state.revision,
        account_key=state.account_key,
        boot_id=state.boot_id,
        epoch=state.epoch,
        issued_at=now,
        expires_at=now + timedelta(minutes=1),
    )
