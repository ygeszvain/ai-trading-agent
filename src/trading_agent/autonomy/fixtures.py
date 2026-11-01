"""Owner-authored synthetic envelope fixture. No real owner decisions are supplied."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from ..config.models import TradingConfig
from ..supervised.contracts import Intent, State, StrategyManifest, digest
from ..supervised.fixtures import state_fixture
from .artifacts import ArtifactVault, execution_code_bytes
from .contracts import Artifact, Asset, Champion, Envelope, Monitoring, OwnerResume, Session, Signed
from .owner_fixture import sign_fixture
from .store import Store, schema_hash

NOW = datetime(2026, 11, 2, 15, tzinfo=UTC)
KEY = digest("M7 fictional account, not a brokerage identity")


def seed_fixture(store: Store, root: Path, now: datetime = NOW) -> tuple[State, Envelope, Champion]:
    store.create_fixture_schema()
    base = state_fixture(now)
    raw = json.loads(base.config_json)
    raw["app"]["mode"] = "bounded_autonomous_live"
    raw["broker"]["approved_account_id"] = "m7-fixture"
    raw["live"].update(
        require_application_approval_per_intent=False,
        owner_authorization_ref="m7-fixture-envelope",
        authorization_expires_at=(now + timedelta(days=2, hours=7)).isoformat(),
    )
    raw["strategy"].update(
        name="m7-fixture-flat-entry-held-exit",
        version="m7-fixture-v1",
        target_weight="0.01",
        order_slice_weight="0.01",
    )
    cfg = TradingConfig.model_validate(raw)
    manifest = StrategyManifest(
        code_hash=digest("fixture-m7-code"),
        dependency_hash=digest("locked-fixture-dependencies"),
        model_hash=digest("no-inference"),
        prompt_hash=digest("no-prompt-inference"),
        feature_hash=digest("flat-held-fixture-only"),
        strategy_settings_json=cfg.strategy.model_dump_json(),
    )
    content = {
        "code": execution_code_bytes(),
        "dependencies": (Path(__file__).resolve().parents[3] / "uv.lock").read_bytes(),
        "parameters": cfg.strategy.model_dump_json().encode(),
        "features": b"flat-or-held-from-reconciled-ledger",
        "model": b"NO_MODEL_WEIGHTS_NO_INFERENCE",
        "prompt": b"NO_INFERENCE_PROMPT_V1",
        "memory_policy": b"INCIDENT_NOTES_ARE_NOT_STRATEGY_INPUTS",
    }
    vault = ArtifactVault(root / "primary")
    artifacts = tuple(
        Artifact.model_validate({"role": role, "content_hash": vault.put(value)})
        for role, value in content.items()
    )
    champion = Champion(
        champion_id="m7-frozen-fixture-v1",
        strategy_version=cfg.strategy.version,
        model_version="NO_MODEL_V1",
        prompt_version="NO_PROMPT_V1",
        strategy_manifest_hash=manifest.digest(),
        artifacts=artifacts,
    )
    champion_hash = vault.put(champion.model_dump_json().encode())
    for artifact in artifacts:
        ArtifactVault(root / "backup").put(vault.get(artifact.content_hash))
    ArtifactVault(root / "backup").put(champion.model_dump_json().encode())
    envelope = Envelope(
        envelope_id="m7-fixture-envelope",
        account_key=KEY,
        run_id="m7-demo",
        capital=Decimal(1000),
        assets=(Asset(instrument="MOCK_ETF"),),
        champion_hash=champion_hash,
        configuration_hash=digest(json.loads(cfg.model_dump_json())),
        risk_policy_hash=digest(cfg.risk.model_dump(mode="json")),
        database_schema_hash=schema_hash(store.engine),
        tool_schema_hash=digest("fictional-equity-tools-v1"),
        permissions_hash=digest("fictional-account-equity-limits-only"),
        sessions=tuple(
            Session(
                session_id="fixture-session-" + str(i + 1),
                opens_at=now + timedelta(days=i),
                closes_at=now + timedelta(days=i, hours=6),
            )
            for i in range(3)
        ),
        monitoring=Monitoring(monitor_id="independent-fixture-monitor"),
        starts_at=now,
        expires_at=now + timedelta(days=2, hours=7),
        protective_expires_at=now + timedelta(days=2, hours=8),
        rollback_target=champion_hash,
    )
    state = base.changed(
        domain="M7_MOCK_ONLY",
        account_key=KEY,
        observed_account_key=KEY,
        account_alias="m7-fixture",
        run_id="m7-demo",
        config_json=cfg.model_dump_json(),
        authorization=None,
        strategy_manifest=manifest,
        strategy_hash=manifest.digest(),
    )
    store.seed_envelope(state, sign_fixture(envelope), envelope)
    with store.transaction() as conn:
        store.record_change(
            conn,
            state,
            now,
            "CHAMPION_FROZEN",
            {"champion_hash": champion_hash, "champion_content": champion.model_dump_json()},
        )
    return state, envelope, champion


def owner_resume(store: Store, now: datetime) -> Signed:
    with store.transaction() as conn:
        state = store.state(conn, KEY)
        runtime = store.runtime(conn, KEY)
    return sign_fixture(
        OwnerResume(
            account_key=KEY,
            envelope_hash=runtime.envelope_hash,
            generation=state.executor_generation,
            state_revision=state.revision,
            incident_cursor=runtime.change_sequence,
            issued_at=now,
            expires_at=now + timedelta(seconds=60),
        )
    )


def intent_fixture(store: Store, champion: Champion, *, suffix: str, now: datetime) -> Intent:
    with store.transaction() as conn:
        state = store.state(conn, KEY)
    cfg = TradingConfig.model_validate_json(state.config_json)
    held = sum(
        (p.quantity for p in state.holdings if p.instrument == state.quote.instrument), Decimal(0)
    )
    return Intent(
        domain="M7_MOCK_ONLY",
        mode="bounded_autonomous_live",
        intent_id="m7-order-" + suffix,
        run_id=state.run_id,
        account_alias=state.account_alias,
        account_key=KEY,
        instrument=state.quote.instrument,
        side="sell" if held else "buy",
        quantity=held or champion.quantity,
        target_weight=Decimal(0) if held else champion.target_weight,
        limit_price=state.quote.price,
        price_lower=state.quote.price - state.quote.price_tick,
        price_upper=state.quote.price,
        max_fee=Decimal(".01"),
        strategy_version=cfg.strategy.version,
        policy_version=cfg.risk.policy_version,
        strategy_hash=state.strategy_hash,
        policy_hash=digest(cfg.risk.model_dump(mode="json")),
        evidence_hashes=(state.risk_hash(),),
        risk_snapshot_hash=state.risk_hash(),
        created_at=now,
        expires_at=now + timedelta(seconds=30),
    )
