"""Envelope-authorized synthetic execution. No signer, real broker or renewal method."""

from __future__ import annotations

import json
import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy.engine import Connection

from ..db.schema import m7_notices
from ..supervised.contracts import (
    Check,
    Intent,
    Order,
    Permit,
    Readiness,
    State,
    digest,
    money_context,
)
from ..supervised.executor import TERMINAL, UNCERTAIN, MockExecutor
from ..supervised.fake import FakeTransport, Observation
from ..supervised.journal import Denied
from ..supervised.readiness import config_for, fresh, risk_check
from .artifacts import ArtifactVault, dependency_bytes, execution_code_bytes
from .contracts import (
    Envelope,
    OwnerAcknowledgement,
    OwnerResume,
    OwnerRevocation,
    Rollback,
    Runtime,
    Signed,
    verify,
)
from .store import Store, schema_hash


class AutonomousExecutor(MockExecutor):
    def __init__(
        self, store: Store, transport: FakeTransport, *, artifacts: Path, boot_id: str, clock: Any
    ) -> None:
        super().__init__(store, transport, boot_id=boot_id, clock=clock)
        self.store = store
        self.artifacts = artifacts

    def vault(self, runtime: Runtime) -> ArtifactVault:
        return ArtifactVault(self.artifacts / runtime.artifact_set)

    def startup(self, key: str, *, now: datetime) -> None:
        super().startup(key, now=now)
        with self.store.transaction() as conn:
            runtime = self.store.runtime(conn, key)
            self.store.save_runtime(conn, key, runtime.changed(authorized_generation=None))

    def _authorize(
        self,
        conn: Connection,
        state: State,
        intent: Intent,
        reference: str,
        *,
        now: datetime,
        consumed: bool,
        excluding_cash: Decimal = Decimal(0),
        excluding_entry: int = 0,
        excluding_turnover: Decimal = Decimal(0),
    ) -> Permit:
        self._assert_fence(state)
        envelope = self.store.envelope(conn, state.account_key)
        runtime = self.store.runtime(conn, state.account_key)
        champion = self.vault(runtime).champion(envelope.champion_hash)
        config = config_for(state)
        self._check_common(conn, state, envelope, runtime, now)
        session = envelope.session_at(now)
        held = sum(
            (p.quantity for p in state.holdings if p.instrument == intent.instrument), Decimal(0)
        )
        side = "sell" if held else "buy"
        quantity = held if held else champion.quantity
        if (
            reference != envelope.envelope_id
            or intent.domain != "M7_MOCK_ONLY"
            or intent.mode != envelope.mode
            or intent.account_key != envelope.account_key
            or intent.account_alias != envelope.account_alias
            or intent.run_id != envelope.run_id
            or intent.instrument != state.quote.instrument
            or intent.instrument not in [a.instrument for a in envelope.assets]
            or intent.side != side
            or intent.quantity != quantity
            or intent.target_weight != (Decimal(0) if held else champion.target_weight)
            or intent.strategy_version != champion.strategy_version
            or intent.strategy_hash != state.strategy_hash
            or intent.policy_version != config.risk.policy_version
            or intent.policy_hash != envelope.risk_policy_hash
            or intent.risk_snapshot_hash != state.risk_hash()
            or intent.evidence_hashes != (state.risk_hash(),)
            or not intent.created_at <= now < intent.expires_at <= envelope.expires_at
            or intent.limit_price != state.quote.price
            or intent.price_upper != state.quote.price
            or intent.price_lower != state.quote.price - state.quote.price_tick
            or intent.max_fee != Decimal(".01")
            or intent.order_type not in envelope.order_types
            or intent.time_in_force not in envelope.time_in_force
            or session is None
            or runtime.session_id != session.session_id
        ):
            raise Denied("intent_outside_frozen_strategy_or_envelope")
        if (
            runtime.open_incidents
            or runtime.authorized_generation != state.executor_generation
            or not state.resumed
            or state.paused
        ):
            raise Denied("explicit_resume_or_incident_review_required")
        if any(
            o.status in UNCERTAIN and (not consumed or o.intent.intent_id != intent.intent_id)
            for o in self.store.account_orders(conn, state.account_key)
        ):
            raise Denied("unknown_orders")
        if any(
            o.status not in TERMINAL and (not consumed or o.intent.intent_id != intent.intent_id)
            for o in self.store.account_orders(conn, state.account_key)
        ):
            raise Denied("working_order_conflict")
        risk = risk_check(
            state, config, intent, now, excluding_cash, excluding_entry, excluding_turnover
        )
        if not risk["passed"]:
            raise Denied("risk_policy_breach")
        return Permit(
            authorization_hash=envelope.digest(),
            report=Readiness(
                mock_controls_satisfied=True,
                checks=(
                    Check(
                        name="synthetic_envelope_and_frozen_champion",
                        satisfied=True,
                        detail="No per-intent app approval; synthetic envelope only",
                    ),
                    Check(
                        name="build_live_dispatch_disabled",
                        satisfied=False,
                        detail="No real authorization or live transport",
                    ),
                ),
            ),
        )

    def _check_common(
        self,
        conn: Connection,
        state: State,
        envelope: Envelope,
        runtime: Runtime,
        now: datetime,
        *,
        require_monitor: bool = True,
    ) -> None:
        if not envelope.starts_at <= now < envelope.expires_at:
            raise Denied("expired_or_not_started_authority")
        if state.revoked:
            raise Denied("revoked_authority")
        config = config_for(state)
        if (
            state.domain != "M7_MOCK_ONLY"
            or state.account_key != envelope.account_key
            or state.observed_account_key != envelope.account_key
            or state.account_alias != envelope.account_alias
            or state.run_id != envelope.run_id
            or config.broker.approved_account_id != envelope.account_alias
        ):
            raise Denied("account_binding")
        if (
            config.app.mode.value != envelope.mode
            or not config.live.enabled
            or config.live.approved_capital_usd != envelope.capital
            or config.live.require_application_approval_per_intent
            or config.live.resume_after_restart
            or digest(json.loads(state.config_json)) != envelope.configuration_hash
            or digest(config.risk.model_dump(mode="json")) != envelope.risk_policy_hash
            or tuple(config.universe.live_instrument_allowlist)
            != tuple(a.instrument for a in envelope.assets)
        ):
            raise Denied("configuration_or_permission_expansion")
        if (
            schema_hash(self.store.engine) != envelope.database_schema_hash
            or runtime.observed_schema_hash != envelope.tool_schema_hash
        ):
            raise Denied("schema_drift")
        if runtime.observed_permissions_hash != envelope.permissions_hash:
            raise Denied("permission_drift")
        champion = self.vault(runtime).champion(envelope.champion_hash)
        code = next(a.content_hash for a in champion.artifacts if a.role == "code")
        dependencies = next(a.content_hash for a in champion.artifacts if a.role == "dependencies")
        if (
            runtime.champion_hash != envelope.champion_hash
            or self.vault(runtime).get(code) != execution_code_bytes()
            or self.vault(runtime).get(dependencies) != dependency_bytes()
            or not state.strategy_frozen
            or state.strategy_manifest.digest() != champion.strategy_manifest_hash
            or state.strategy_hash != champion.strategy_manifest_hash
            or state.strategy_manifest.strategy_settings_json != config.strategy.model_dump_json()
        ):
            raise Denied("champion_artifact_or_hidden_settings_changed")
        for health in (state.data, state.audit, state.reconciliation):
            if health.status != "healthy" or not fresh(
                health.as_of, now, config.risk.max_account_state_age_seconds
            ):
                raise Denied("unhealthy_or_stale_data_reconciliation_audit")
        q = state.quote
        if (
            not fresh(state.account_as_of, now, config.risk.max_account_state_age_seconds)
            or not fresh(q.as_of, now, config.risk.max_quote_age_seconds)
            or not fresh(state.eligibility_as_of, now, config.risk.max_account_state_age_seconds)
            or not q.eligible
            or not q.tradable
            or q.asset_class != "unleveraged_etf"
            or not q.regular_session
        ):
            raise Denied("stale_or_ineligible_market_account")
        if require_monitor:
            heartbeat = self.store.heartbeat(conn, state.account_key)
            if (
                heartbeat is None
                or not heartbeat.healthy
                or heartbeat.monitor_id != envelope.monitoring.monitor_id
                or heartbeat.process_id == os.getpid()
                or heartbeat.executor_generation != state.executor_generation
                or heartbeat.envelope_hash != envelope.digest()
                or heartbeat.champion_hash != envelope.champion_hash
                or heartbeat.schema_hash != envelope.tool_schema_hash
                or heartbeat.permissions_hash != envelope.permissions_hash
                or not fresh(
                    heartbeat.observed_at, now, envelope.monitoring.max_heartbeat_age_seconds
                )
            ):
                raise Denied("independent_monitor_missing_stale_or_unhealthy")

    def _consume(self, conn: Connection, state: State, reference: str) -> None:
        # A use record consumes capacity; it neither issues nor modifies authorization.
        self.store.event(
            conn,
            state,
            self.clock(),
            "m7_envelope_used_no_application_approval",
            {"envelope_id": reference},
        )

    def dispatch(self, intent: Intent, approval_id: str, *, now: datetime) -> Order:
        try:
            return super().dispatch(intent, approval_id, now=now)
        except Exception as error:
            if not isinstance(error, Denied):
                self._failed = True
            reason = str(error) if isinstance(error, Denied) else "audit_or_artifact_failure"
            self.store.deny(intent.account_key, now, reason, evidence_hash=intent.digest())
            raise

    def dispatch_reserved(self, key: str, intent_id: str, *, now: datetime) -> Order:
        try:
            result = super().dispatch_reserved(key, intent_id, now=now)
            if result.status in {"unknown", "manual_review", "broker_approval_required"}:
                with self.store.transaction() as conn:
                    self.store.incident(
                        conn,
                        self.store.state(conn, key),
                        now,
                        "unresolved_broker_outcome",
                        evidence_hash=result.digest(),
                    )
            return result
        except Exception as error:
            if not isinstance(error, Denied):
                self._failed = True
            reason = str(error) if isinstance(error, Denied) else "audit_or_artifact_failure"
            self.store.deny(key, now, reason)
            raise

    def resume(self, proof: Signed, *, now: datetime) -> None:
        self._check_instance()
        request = verify(proof, OwnerResume, role="fixture_owner")
        with self.store.transaction() as conn:
            state = self.store.state(conn, request.account_key)
            self._assert_fence(state)
            envelope = self.store.envelope(conn, state.account_key)
            runtime = self.store.runtime(conn, state.account_key)
            self._check_common(conn, state, envelope, runtime, now)
            if (
                request.envelope_hash != envelope.digest()
                or request.generation != state.executor_generation
                or request.state_revision != state.revision
                or request.incident_cursor != runtime.change_sequence
                or not request.issued_at <= now < request.expires_at <= envelope.expires_at
                or runtime.open_incidents
                or any(
                    o.status in UNCERTAIN
                    for o in self.store.account_orders(conn, state.account_key)
                )
            ):
                raise Denied("resume_scope_expiry_or_unresolved_incident")
            self.store.record_change(
                conn, state, now, "OWNER_RESUME", request.model_dump(mode="json")
            )
            self.store.save(conn, state.changed(paused=False, resumed=True))
            self.store.save_runtime(
                conn,
                state.account_key,
                runtime.changed(authorized_generation=state.executor_generation),
            )

    @money_context
    def reconcile_account(self, key: str, *, cash: Decimal, holdings: Any, now: datetime) -> bool:
        result = super().reconcile_account(key, cash=cash, holdings=holdings, now=now)
        with self.store.transaction() as conn:
            state = self.store.state(conn, key)
            self._assert_fence(state)
            runtime = self.store.runtime(conn, key)
            if not result:
                self.store.incident(conn, state, now, "reconciliation_difference")
            elif (
                not self._failed
                and not runtime.open_incidents
                and runtime.authorized_generation == state.executor_generation
            ):
                self.store.save(conn, state.changed(paused=False, resumed=True))
        return result

    def acknowledge(self, proof: Signed, *, now: datetime) -> None:
        request = verify(proof, OwnerAcknowledgement, role="fixture_owner")
        with self.store.transaction() as conn:
            state = self.store.state(conn, request.account_key)
            runtime = self.store.runtime(conn, state.account_key)
            if (
                request.envelope_hash != runtime.envelope_hash
                or request.incident_hash not in runtime.open_incidents
                or not request.issued_at <= now < request.expires_at
            ):
                raise Denied("human_acknowledgement_invalid")
            self.store.record_change(
                conn, state, now, "HUMAN_ACKNOWLEDGED", request.model_dump(mode="json")
            )
            conn.execute(
                m7_notices.update()
                .where(m7_notices.c.incident_hash == request.incident_hash)
                .values(acknowledged=True)
            )
            self.store.save_runtime(
                conn,
                state.account_key,
                runtime.changed(
                    open_incidents=tuple(
                        x for x in runtime.open_incidents if x != request.incident_hash
                    )
                ),
            )

    def rollback(self, proof: Signed, *, now: datetime) -> None:
        request = verify(proof, Rollback, role="fixture_owner")
        with self.store.transaction() as conn:
            state = self.store.state(conn, request.account_key)
            self._assert_fence(state)
            runtime = self.store.runtime(conn, state.account_key)
            envelope = self.store.envelope(conn, state.account_key)
            if (
                request.envelope_hash != envelope.digest()
                or request.target_champion_hash != envelope.rollback_target
                or not request.issued_at <= now < request.expires_at
            ):
                raise Denied("rollback_not_authorized")
            ArtifactVault(self.artifacts / "backup").champion(envelope.rollback_target)
            self.store.record_change(
                conn, state, now, "ROLLBACK_RECORDED", request.model_dump(mode="json")
            )
            self.store.save_runtime(
                conn,
                state.account_key,
                runtime.changed(
                    artifact_set="backup",
                    champion_hash=envelope.rollback_target,
                    authorized_generation=None,
                ),
            )
            self.store.save(conn, state.changed(paused=True, resumed=False))

    def request_state_change(
        self, key: str, operation: str, payload: dict[str, Any], *, now: datetime
    ) -> None:
        # Research/learning/UI have proposal/read capabilities only. No update switch.
        self.store.deny(
            key,
            now,
            "forbidden_authority_change",
            evidence_hash=digest({"operation": operation, "payload": payload}),
        )
        raise Denied("authorization_issue_renew_widen_replace_modify_unavailable")

    def protective_cancel(self, key: str, intent_id: str, *, now: datetime) -> Order:
        try:
            return self._protective_cancel(key, intent_id, now=now)
        except Exception as error:
            if not isinstance(error, Denied):
                self._failed = True
            self.store.deny(key, now, "protective_cancellation_unresolved")
            raise

    def _protective_cancel(self, key: str, intent_id: str, *, now: datetime) -> Order:
        self._check_instance()
        with self.store.transaction() as conn:
            state = self.store.state(conn, key)
            self._assert_fence(state)
            envelope = self.store.envelope(conn, key)
            order = self.store.order(conn, intent_id, key)
            runtime = self.store.runtime(conn, key)
            if (
                state.observed_account_key != envelope.account_key
                or runtime.observed_schema_hash != envelope.tool_schema_hash
                or runtime.observed_permissions_hash != envelope.permissions_hash
                or schema_hash(self.store.engine) != envelope.database_schema_hash
                or not fresh(
                    state.account_as_of, now, config_for(state).risk.max_account_state_age_seconds
                )
            ):
                raise Denied("protective_state_schema_or_permissions_unverified")
            if (
                "cancel_entries" not in envelope.protective_actions
                or not envelope.starts_at <= now < envelope.protective_expires_at
                or order.intent.side != "buy"
                or order.status in TERMINAL
                or order.status in UNCERTAIN
                or order.authorization_hash != envelope.digest()
            ):
                raise Denied("protective_cancellation_not_permitted")
            request_hash = digest(
                {
                    "cancel": intent_id,
                    "generation": state.executor_generation,
                    "envelope_hash": envelope.digest(),
                }
            )
            self.store.record_change(
                conn,
                state,
                now,
                "PROTECTIVE_CANCEL_REQUESTED",
                {"request_hash": request_hash, "intent_id": intent_id, "reserves_retained": True},
            )
            self.store.save_order(conn, order.changed(status="cancel_pending"))
        # Commit the cancellation attempt before touching even the fake transport.
        with self.store.transaction() as conn:
            state = self.store.state(conn, key)
            self._assert_fence(state)
            current = self.store.envelope(conn, key)
            runtime = self.store.runtime(conn, key)
            wire_now = self.clock()
            if (
                current.digest() != envelope.digest()
                or not current.starts_at <= wire_now < current.protective_expires_at
                or not fresh(
                    state.account_as_of,
                    wire_now,
                    config_for(state).risk.max_account_state_age_seconds,
                )
                or runtime.observed_schema_hash != current.tool_schema_hash
                or runtime.observed_permissions_hash != current.permissions_hash
                or schema_hash(self.store.engine) != current.database_schema_hash
                or self.store.order(conn, intent_id, key).status != "cancel_pending"
            ):
                raise Denied("protective_pre_wire_revalidation_failed")
            try:
                response = self.transport.cancel(intent_id)
            except Exception:
                response = Observation(status="unknown")
        return self._observe(key, intent_id, response, now=now)

    def cancel(self, *_args: Any, **_kwargs: Any) -> Order:
        raise Denied("M6 approval cannot authorize M7 cancellation; use envelope protection")

    @money_context
    def _observe_market(self, key: str, quote: Any, *, now: datetime) -> None:
        """Trusted fixture observation; cannot alter capital, policy, artifacts or envelope."""
        with self.store.transaction() as conn:
            state = self.store.state(conn, key)
            self._assert_fence(state)
            runtime = self.store.runtime(conn, key)
            envelope = self.store.envelope(conn, key)
            session = envelope.session_at(now)
            if (
                quote.instrument not in [a.instrument for a in envelope.assets]
                or quote.as_of != now
                or state.account_as_of is None
                or now < state.account_as_of
            ):
                raise Denied("market_observation_scope_or_time")
            holdings = sum((p.quantity for p in state.holdings), Decimal(0))
            nav = state.cash + sum((p.quantity * quote.mark for p in state.holdings), Decimal(0))
            changed = state.changed(
                quote=quote,
                account_as_of=now,
                eligibility_as_of=now,
                data=state.data.changed(status="healthy", as_of=now),
                audit=state.audit.changed(status="healthy", as_of=now),
                high_water_mark=max(state.high_water_mark, nav),
            )
            if session is not None and runtime.session_id != session.session_id:
                if any(o.status not in TERMINAL for o in self.store.account_orders(conn, key)):
                    raise Denied("working_orders_cross_session")
                if envelope.overnight_policy == "FORBID" and holdings:
                    self.store.incident(conn, state, now, "overnight_exposure_not_permitted")
                    raise Denied("overnight_exposure_not_permitted")
                changed = changed.changed(
                    day_start_nav=nav, daily_turnover=Decimal(0), entry_attempts=0
                )
                self.store.save_runtime(conn, key, runtime.changed(session_id=session.session_id))
                self.store.event(
                    conn,
                    state,
                    now,
                    "m7_new_session_counters",
                    {
                        "session_id": session.session_id,
                        "high_water_mark_preserved": str(state.high_water_mark),
                    },
                )
            self.store.save(conn, changed)
            self.store.event(
                conn, changed, now, "m7_market_observed", {"quote": quote.model_dump(mode="json")}
            )

    def observe_market(self, key: str, quote: Any, *, now: datetime) -> None:
        try:
            self._observe_market(key, quote, now=now)
        except Denied as error:
            self.store.deny(key, now, str(error))
            raise

    def revoke(self, proof: Signed, *, now: datetime) -> None:
        request = verify(proof, OwnerRevocation, role="fixture_owner")
        with self.store.transaction() as conn:
            state = self.store.state(conn, request.account_key)
            envelope = self.store.envelope(conn, state.account_key)
            runtime = self.store.runtime(conn, state.account_key)
            if (
                request.envelope_hash != envelope.digest()
                or not request.issued_at <= now < request.expires_at
            ):
                raise Denied("revocation_scope_or_expiry")
            self.store.record_change(
                conn, state, now, "ENVELOPE_REVOKED", request.model_dump(mode="json")
            )
            conn.execute(
                self.store.approvals.update()
                .where(self.store.approvals.c.account_key == state.account_key)
                .values(revoked=True)
            )
            self.store.save(
                conn, state.changed(revoked=True, paused=True, resumed=False, epoch=state.epoch + 1)
            )
            self.store.save_runtime(
                conn, state.account_key, runtime.changed(authorized_generation=None)
            )
