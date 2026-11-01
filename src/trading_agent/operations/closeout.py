"""Calendar-bound pre-close controls. Execution remains exact M7 fake transport only.

The signed synthetic envelope freezes the policy record. Missing closeout policy
never acquires authority. Exits use the existing final-wire checks and ledger;
no alternate broker adapter, market-order fallback or implicit resume exists.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal, Self, cast

from pydantic import Field, model_validator
from sqlalchemy import select
from sqlalchemy.engine import Connection

from ..autonomy.contracts import Envelope, Session
from ..autonomy.engine import AutonomousExecutor
from ..db.schema import ops_closeouts, ops_records
from ..supervised.contracts import Digest, Fill, Identifier, Intent, Record, State, digest
from ..supervised.executor import TERMINAL, UNCERTAIN
from ..supervised.journal import Denied
from ..supervised.readiness import config_for
from .journal import record
from .reconciliation import Comparison, Inventory, LedgerView, OpenOrder, Position


class CloseoutPolicy(Record):
    domain: Literal["M7_MOCK_ONLY"] = "M7_MOCK_ONLY"
    account_key: Digest
    instrument: Identifier
    calendar_hash: Digest
    sessions: tuple[Session, ...] = Field(min_length=1, max_length=30)
    entry_cutoff_minutes: int = Field(ge=1, le=120)
    cancel_entries_minutes: int = Field(ge=1, le=120)
    exit_start_minutes: int = Field(ge=1, le=120)
    flat_deadline_minutes: int = Field(ge=1, le=120)
    max_snapshot_span_seconds: int = Field(default=5, ge=0, le=5)
    email_ack_required: bool = True
    email_ack_max_age_seconds: int = Field(default=3600, ge=60, le=86400)

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if not self.instrument.startswith("MOCK_"):
            raise ValueError("only fictional closeout execution is supported")
        if (
            not self.entry_cutoff_minutes
            >= self.cancel_entries_minutes
            > self.exit_start_minutes
            > self.flat_deadline_minutes
        ):
            raise ValueError("pre-close deadlines inconsistent")
        if self.calendar_hash != digest([s.model_dump(mode="json") for s in self.sessions]):
            raise ValueError("session calendar hash mismatch")
        if any(
            (s.closes_at - s.opens_at).total_seconds() <= 60 * self.entry_cutoff_minutes
            for s in self.sessions
        ):
            raise ValueError("session too short for closeout policy")
        return self


def install_policy(conn: Connection, policy: CloseoutPolicy) -> str:
    return record(conn, policy.account_key, "closeout_policy", policy.model_dump(mode="json"))


def bound_policy(conn: Connection, envelope: Envelope) -> CloseoutPolicy:
    row = conn.execute(
        select(ops_records).where(
            ops_records.c.record_id == envelope.closeout_policy_hash,
            ops_records.c.scope == envelope.account_key,
            ops_records.c.kind == "closeout_policy",
        )
    ).one_or_none()
    if row is None:
        raise Denied("closeout_policy_missing")
    policy = CloseoutPolicy.model_validate_json(row.document)
    if (
        digest(
            {
                "scope": policy.account_key,
                "kind": "closeout_policy",
                "document": policy.model_dump(mode="json"),
            }
        )
        != envelope.closeout_policy_hash
        or policy.account_key != envelope.account_key
        or policy.sessions != envelope.sessions
        or [policy.instrument] != [a.instrument for a in envelope.assets]
        or envelope.overnight_policy != "FORBID"
    ):
        raise Denied("closeout_policy_binding")
    return policy


def enforce_entry_window(
    conn: Connection, envelope: Envelope, intent: Intent, now: datetime
) -> None:
    policy = bound_policy(conn, envelope)
    session = envelope.session_at(now)
    if session is None or (
        intent.side == "buy"
        and now >= session.closes_at - timedelta(minutes=policy.entry_cutoff_minutes)
    ):
        raise Denied("preclose_entry_cutoff")
    if intent.side == "buy" and policy.email_ack_required:
        from .email import delivery_health

        if not delivery_health(
            conn,
            envelope.account_key,
            now,
            max_ack_age_seconds=policy.email_ack_max_age_seconds,
            run_id=envelope.run_id,
        ):
            raise Denied("email_delivery_unverified")


def ledger_view(executor: AutonomousExecutor, conn: Connection, state: State) -> LedgerView:
    orders = []
    for order in executor.store.account_orders(conn, state.account_key):
        if order.status in TERMINAL:
            continue
        status = (
            "unknown"
            if order.status in UNCERTAIN
            else "cancel_pending"
            if order.status == "cancel_pending"
            else "working"
        )
        if order.status == "broker_approval_required":
            status = "approval_required"
        orders.append(
            OpenOrder(
                order_key=digest(order.broker_order_id or order.intent.intent_id),
                instrument=order.intent.instrument,
                side=order.intent.side,
                remaining=order.remaining_quantity,
                status=cast(
                    Literal["working", "cancel_pending", "unknown", "approval_required"], status
                ),
            )
        )
    return LedgerView(
        account_key=state.account_key,
        run_id=state.run_id,
        mode="simulation",
        cash=state.cash,
        positions=tuple(
            Position(asset_class="equity", instrument=p.instrument, quantity=p.quantity)
            for p in state.holdings
        ),
        orders=tuple(orders),
        audit_healthy=state.audit.status == "healthy",
    )


class CloseoutController:
    def __init__(self, executor: AutonomousExecutor) -> None:
        self.executor = executor

    def tick(self, key: str, *, now: datetime, comparison: Comparison) -> str:
        exe = self.executor
        with exe.store.transaction() as conn:
            state = exe.store.state(conn, key)
            exe._assert_fence(state)
            envelope = exe.store.envelope(conn, key)
            policy = bound_policy(conn, envelope)
            session = envelope.session_at(now)
            # After the session, monitoring still reports unresolved exposure; it never trades.
            if session is None:
                exe.store.incident(conn, state, now, "closeout_outside_session")
                return "BLOCKED"
            view = ledger_view(exe, conn, state)
            proof = conn.execute(
                select(ops_records).where(
                    ops_records.c.record_id
                    == digest(
                        {
                            "scope": key,
                            "kind": "reconciliation",
                            "document": comparison.model_dump(mode="json"),
                        }
                    ),
                    ops_records.c.scope == key,
                    ops_records.c.kind == "reconciliation",
                )
            ).first()
            evidence_rows = [
                conn.execute(select(ops_records).where(ops_records.c.record_id == ref)).first()
                for ref in (comparison.inventory_record_id, comparison.ledger_record_id)
            ]
            evidence_valid = all(
                row is not None
                and row.scope == key
                and digest(json.loads(row.document)) == expected
                for row, expected in zip(
                    evidence_rows, (comparison.snapshot_hash, comparison.ledger_hash), strict=True
                )
            )
            inventory_row = evidence_rows[0]
            snapshot = (
                Inventory.model_validate_json(inventory_row.document)
                if evidence_valid and inventory_row is not None
                else None
            )
            if (
                snapshot is None
                or not 0
                <= (now - snapshot.completed_at).total_seconds()
                <= config_for(state).risk.max_account_state_age_seconds
                or (snapshot.completed_at - snapshot.started_at).total_seconds()
                > policy.max_snapshot_span_seconds
                or proof is None
                or not evidence_valid
                or comparison.approved_schema_hash != envelope.tool_schema_hash
                or comparison.source != "FIXTURE"
                or not comparison.consistent
                or comparison.account_key != key
                or comparison.run_id != state.run_id
                or comparison.mode != "simulation"
                or comparison.ledger_hash != view.digest()
                or not 0
                <= (now - comparison.as_of).total_seconds()
                <= config_for(state).risk.max_account_state_age_seconds
            ):
                exe.store.incident(conn, state, now, "closeout_reconciliation_required")
                return "BLOCKED"
            if any(p.instrument != policy.instrument and p.quantity for p in state.holdings):
                exe.store.incident(conn, state, now, "closeout_ownership_ambiguous")
                return "BLOCKED"
            orders = exe.store.account_orders(conn, key)
            unresolved = [o for o in orders if o.status not in TERMINAL]
            if any(
                o.intent.instrument != policy.instrument
                or o.intent.run_id != state.run_id
                or o.intent.strategy_hash != state.strategy_hash
                for o in unresolved
            ):
                exe.store.incident(conn, state, now, "closeout_unmanaged_order")
                return "BLOCKED"
            held = sum(
                (p.quantity for p in state.holdings if p.instrument == policy.instrument),
                Decimal(0),
            )
            job_id = digest(
                {
                    "scope": key,
                    "policy": envelope.closeout_policy_hash,
                    "session": session.session_id,
                    "envelope": envelope.digest(),
                    "run_id": state.run_id,
                }
            )
            prior = conn.execute(
                select(ops_closeouts).where(ops_closeouts.c.job_id == job_id)
            ).first()
            job = (
                json.loads(prior.document)
                if prior
                else {
                    "phase": "WAITING",
                    "intent_id": None,
                    "run_id": state.run_id,
                    "policy_hash": envelope.closeout_policy_hash,
                }
            )
            allowed_orders = {
                o.intent.intent_id
                for o in orders
                if o.intent.run_id == state.run_id and o.intent.strategy_hash == state.strategy_hash
            }
            owned = Decimal(0)
            raw_fills: list[str] = list(
                conn.execute(
                    select(exe.store.fills.c.document).where(exe.store.fills.c.account_key == key)
                ).scalars()
            )
            for fill_raw in raw_fills:
                fill = Fill.model_validate_json(fill_raw)
                if fill.order_id in allowed_orders and fill.instrument == policy.instrument:
                    owned += fill.quantity if fill.side == "buy" else -fill.quantity
            if held != owned:
                exe.store.incident(conn, state, now, "closeout_ownership_ambiguous")
                return "BLOCKED"
            if prior is None:
                conn.execute(
                    ops_closeouts.insert().values(
                        job_id=job_id, scope=key, document=json.dumps(job)
                    )
                )
            if job["phase"] == "FLAT" and (held or unresolved):
                return self._blocked(
                    conn, state, job_id, job, now, "exposure_after_flat_confirmation"
                )
            if job["phase"] in {"BLOCKED", "FLAT"}:
                return str(job["phase"])
            if now >= session.closes_at - timedelta(minutes=policy.flat_deadline_minutes) and (
                held or unresolved
            ):
                return self._blocked(conn, state, job_id, job, now, "closeout_flat_deadline_missed")
            if any(o.status in UNCERTAIN for o in unresolved):
                return self._blocked(conn, state, job_id, job, now, "closeout_unknown_order")
            working_buys = [o for o in unresolved if o.intent.side == "buy"]
            if working_buys and now >= session.closes_at - timedelta(
                minutes=policy.cancel_entries_minutes
            ):
                action = "CANCEL"
                target = working_buys[0].intent.intent_id
            elif now < session.closes_at - timedelta(minutes=policy.exit_start_minutes):
                return "WAITING"
            elif not held and not unresolved:
                self._save(conn, key, job_id, {**job, "phase": "FLAT"}, now)
                return "FLAT"
            elif unresolved:
                action, target = "OBSERVE", unresolved[0].intent.intent_id
            elif job["intent_id"] is not None:
                return self._blocked(
                    conn, state, job_id, job, now, "closeout_attempt_requires_review"
                )
            else:
                # This is the frozen champion's already-permitted held-position exit.
                # No new quantity, asset, limit type or strategy parameter is introduced.
                champion = exe.vault(exe.store.runtime(conn, key)).champion(envelope.champion_hash)
                cfg = config_for(state)
                target = "closeout-" + job_id[:32]
                order_intent = Intent(
                    domain="M7_MOCK_ONLY",
                    mode="bounded_autonomous_live",
                    intent_id=target,
                    run_id=state.run_id,
                    account_alias=state.account_alias,
                    account_key=key,
                    instrument=policy.instrument,
                    side="sell",
                    quantity=held,
                    target_weight=Decimal(0),
                    limit_price=state.quote.price,
                    price_lower=state.quote.price - state.quote.price_tick,
                    price_upper=state.quote.price,
                    max_fee=Decimal(".01"),
                    strategy_version=champion.strategy_version,
                    policy_version=cfg.risk.policy_version,
                    strategy_hash=state.strategy_hash,
                    policy_hash=envelope.risk_policy_hash,
                    evidence_hashes=(state.risk_hash(),),
                    risk_snapshot_hash=state.risk_hash(),
                    created_at=now,
                    expires_at=min(now + timedelta(seconds=30), envelope.expires_at),
                )
                job = {**job, "intent_id": target, "phase": "EXIT_STARTING"}
                self._save(conn, key, job_id, job, now)  # durable before executor reservation/wire
                action = "SUBMIT"
        try:
            if action == "CANCEL":
                exe.protective_cancel(key, target, now=now)
                return "AWAIT_RECONCILIATION"
            if action == "OBSERVE":
                exe.reconcile_order(key, target, now=now)
                return "AWAIT_RECONCILIATION"
            outcome = exe.dispatch(order_intent, envelope.envelope_id, now=now)
            if outcome.status in UNCERTAIN:
                with exe.store.transaction() as conn:
                    return self._blocked(
                        conn,
                        exe.store.state(conn, key),
                        job_id,
                        job,
                        now,
                        "closeout_broker_outcome_unresolved",
                    )
            with exe.store.transaction() as conn:
                self._save(conn, key, job_id, {**job, "phase": "EXIT_WORKING"}, now)
            return "EXIT_WORKING"
        except Exception:
            with exe.store.transaction() as conn:
                current = exe.store.state(conn, key)
                return self._blocked(
                    conn, current, job_id, job, now, "closeout_execution_uncertain"
                )

    @staticmethod
    def _save(
        conn: Connection, key: str, job_id: str, job: dict[str, object], now: datetime
    ) -> None:
        conn.execute(
            ops_closeouts.update()
            .where(ops_closeouts.c.job_id == job_id)
            .values(document=json.dumps(job))
        )
        record(conn, key, "closeout_state", {"job_id": job_id, "at": now.isoformat(), **job})

    def _blocked(
        self,
        conn: Connection,
        state: State,
        job_id: str,
        job: dict[str, object],
        now: datetime,
        reason: str,
    ) -> str:
        self._save(
            conn, state.account_key, job_id, {**job, "phase": "BLOCKED", "reason": reason}, now
        )
        self.executor.store.incident(conn, state, now, reason)
        return "BLOCKED"
