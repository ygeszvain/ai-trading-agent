"""Durable envelope, monitoring, incidents and change history; no renewal path."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import inspect, select
from sqlalchemy.engine import Connection, Engine

from ..db.schema import (
    M7_ALL_TABLES,
    M7_TABLES,
    m7_changes,
    m7_monitor,
    m7_notices,
    m7_runtime,
    metadata,
)
from ..supervised.contracts import State, digest
from ..supervised.journal import Denied, Journal
from ..supervised.readiness import config_for
from .contracts import Envelope, Heartbeat, Runtime, Signed, verify


def schema_hash(engine: Engine) -> str:
    inspector = inspect(engine)
    manifest = []
    for table in M7_ALL_TABLES:
        if not inspector.has_table(table.name):
            return digest({"missing": table.name})
        manifest.append(
            (
                table.name,
                [
                    (c["name"], str(c["type"]), c["nullable"])
                    for c in inspector.get_columns(table.name)
                ],
                inspector.get_pk_constraint(table.name)["constrained_columns"],
                sorted(
                    (
                        tuple(f["constrained_columns"]),
                        f["referred_table"],
                        tuple(f["referred_columns"]),
                    )
                    for f in inspector.get_foreign_keys(table.name)
                ),
                sorted(
                    tuple(u["column_names"]) for u in inspector.get_unique_constraints(table.name)
                ),
            )
        )
    return digest(manifest)


class Store(Journal):
    def __init__(self, engine: Engine) -> None:
        super().__init__(engine, tables=M7_TABLES)

    def create_fixture_schema(self) -> None:
        metadata.create_all(self.engine, tables=list(M7_ALL_TABLES))

    def runtime(self, conn: Connection, key: str) -> Runtime:
        raw: str = conn.execute(
            select(m7_runtime.c.document).where(m7_runtime.c.account_key == key)
        ).scalar_one()
        return Runtime.model_validate_json(raw)

    def save_runtime(self, conn: Connection, key: str, runtime: Runtime) -> None:
        conn.execute(
            m7_runtime.update()
            .where(m7_runtime.c.account_key == key)
            .values(document=runtime.model_dump_json())
        )

    def envelope(self, conn: Connection, key: str, *, allow_revoked: bool = False) -> Envelope:
        row = conn.execute(select(self.approvals).where(self.approvals.c.account_key == key)).one()
        envelope = verify(Signed.model_validate_json(row.document), Envelope, role="fixture_owner")
        runtime = self.runtime(conn, key)
        if (
            (row.revoked and not allow_revoked)
            or row.consumed
            or envelope.account_key != key
            or row.approval_id != envelope.envelope_id
            or row.intent_hash != envelope.digest()
            or runtime.envelope_hash != envelope.digest()
        ):
            raise Denied("synthetic envelope altered or revoked")
        return envelope

    def seed_envelope(self, state: State, proof: Signed, envelope: Envelope) -> None:
        config_for(state)
        if (
            verify(proof, Envelope, role="fixture_owner") != envelope
            or state.domain != "M7_MOCK_ONLY"
        ):
            raise Denied("synthetic owner envelope required")
        if envelope.database_schema_hash != schema_hash(self.engine):
            raise Denied("database schema not bound")
        runtime = Runtime(
            envelope_hash=envelope.digest(),
            champion_hash=envelope.champion_hash,
            observed_schema_hash=envelope.tool_schema_hash,
            observed_permissions_hash=envelope.permissions_hash,
        )
        with self.transaction() as conn:
            conn.execute(
                self.accounts.insert().values(
                    account_key=state.account_key, document=state.model_dump_json()
                )
            )
            conn.execute(
                self.approvals.insert().values(
                    approval_id=envelope.envelope_id,
                    account_key=state.account_key,
                    intent_hash=envelope.digest(),
                    document=proof.model_dump_json(),
                    consumed=False,
                    revoked=False,
                )
            )
            conn.execute(
                m7_runtime.insert().values(
                    account_key=state.account_key, document=runtime.model_dump_json()
                )
            )
            self.event(
                conn,
                state,
                envelope.starts_at,
                "m7_synthetic_envelope_recorded",
                {"envelope_hash": envelope.digest(), "authority": "LIVE_NOT_AUTHORIZED"},
            )

    def incident(
        self,
        conn: Connection,
        state: State,
        at: datetime,
        reason: str,
        *,
        evidence_hash: str | None = None,
    ) -> str:
        runtime = self.runtime(conn, state.account_key)
        for key in runtime.open_incidents:
            row: str = conn.execute(
                select(m7_notices.c.document).where(m7_notices.c.incident_hash == key)
            ).scalar_one()
            if json.loads(row)["reason"] == reason:
                self.save(conn, state.changed(paused=True, resumed=False))
                return key
        key = digest(
            {
                "reason": reason,
                "envelope_hash": runtime.envelope_hash,
                "cursor": runtime.change_sequence + 1,
            }
        )
        notice = {
            "domain": "M7_MOCK_ONLY",
            "incident_hash": key,
            "reason": reason,
            "evidence_hash": evidence_hash,
            "envelope_hash": runtime.envelope_hash,
            "at": at.isoformat(),
            "channel": "LOCAL_REVIEW_QUEUE",
            "operator": "fixture-human",
            "delivery_status": "QUEUED_LOCAL_NOT_SENT",
            "human_acknowledgement_required": True,
        }
        conn.execute(
            m7_notices.insert().values(
                incident_hash=key,
                account_key=state.account_key,
                document=json.dumps(notice),
                acknowledged=False,
            )
        )
        self.save_runtime(
            conn,
            state.account_key,
            runtime.changed(
                open_incidents=(*runtime.open_incidents, key),
                change_sequence=runtime.change_sequence + 1,
                authorized_generation=None,
            ),
        )
        state = self.save(conn, state.changed(paused=True, resumed=False))
        from ..operations.email import Notice, enqueue

        enqueue(
            conn,
            Notice(
                domain="FIXTURE",
                scope=state.account_key,
                incident_hash=key,
                run_id=state.run_id,
                code="CONTROL_INCIDENT",
                at=at,
            ),
        )
        self.event(conn, state, at, "m7_incident_escalation_queued", notice)
        return key

    def deny(
        self, key: str, at: datetime, reason: str, *, evidence_hash: str | None = None
    ) -> None:
        with self.transaction() as conn:
            state = self.state(conn, key)
            self.event(
                conn,
                state,
                at,
                "m7_denied_state_change",
                {
                    "reason": reason,
                    "evidence_hash": evidence_hash,
                    "envelope_hash": self.runtime(conn, key).envelope_hash,
                },
            )
            self.incident(conn, state, at, reason, evidence_hash=evidence_hash)

    def pause(self, key: str, *, at: datetime) -> None:
        """Independent local stop: can only remove authority, never cancel or resume."""
        with self.transaction() as conn:
            self.incident(conn, self.state(conn, key), at, "independent_stop_requested")

    def heartbeat(self, conn: Connection, key: str) -> Heartbeat | None:
        raw = conn.execute(
            select(m7_monitor.c.document).where(m7_monitor.c.account_key == key)
        ).scalar_one_or_none()
        return (
            verify(Signed.model_validate_json(raw), Heartbeat, role="fixture_monitor")
            if raw
            else None
        )

    def accept_heartbeat(self, proof: Signed) -> None:
        heartbeat = verify(proof, Heartbeat, role="fixture_monitor")
        with self.transaction() as conn:
            state = self.state(conn, heartbeat.account_key)
            envelope = self.envelope(conn, state.account_key, allow_revoked=True)
            runtime = self.runtime(conn, state.account_key)
            if (
                heartbeat.sequence <= runtime.monitor_sequence
                or heartbeat.envelope_hash != envelope.digest()
                or heartbeat.monitor_id != envelope.monitoring.monitor_id
                or heartbeat.executor_generation != state.executor_generation
            ):
                raise Denied("monitor identity, scope, generation or sequence mismatch")
            exists = conn.execute(
                select(m7_monitor.c.account_key).where(
                    m7_monitor.c.account_key == state.account_key
                )
            ).first()
            values = {"account_key": state.account_key, "document": proof.model_dump_json()}
            if exists:
                conn.execute(
                    m7_monitor.update()
                    .where(m7_monitor.c.account_key == state.account_key)
                    .values(document=proof.model_dump_json())
                )
            else:
                conn.execute(m7_monitor.insert().values(**values))
            self.save_runtime(
                conn, state.account_key, runtime.changed(monitor_sequence=heartbeat.sequence)
            )
            self.event(
                conn,
                state,
                heartbeat.observed_at,
                "m7_independent_monitor_observed",
                {"heartbeat": heartbeat.model_dump(mode="json")},
            )
            if not heartbeat.healthy:
                self.incident(
                    conn,
                    state,
                    heartbeat.observed_at,
                    "monitor_unhealthy",
                    evidence_hash=heartbeat.digest(),
                )

    def record_change(
        self, conn: Connection, state: State, at: datetime, kind: str, document: dict[str, Any]
    ) -> str:
        key = digest({"kind": kind, "document": document})
        if conn.execute(
            select(m7_changes.c.change_id).where(m7_changes.c.change_id == key)
        ).first():
            raise Denied("owner command or proposal replay")
        conn.execute(
            m7_changes.insert().values(
                change_id=key,
                account_key=state.account_key,
                kind=kind,
                document=json.dumps(document, sort_keys=True),
            )
        )
        self.event(conn, state, at, "m7_" + kind.lower(), {"change_id": key, **document})
        return key
