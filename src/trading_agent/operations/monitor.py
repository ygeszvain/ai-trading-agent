"""Independent persisted health monitor; no broker credentials or execution APIs."""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Literal

from pydantic import AwareDatetime, Field
from sqlalchemy import select
from sqlalchemy.engine import Engine

from ..db.schema import ops_mail, ops_monitors
from ..supervised.contracts import Digest, Identifier, Record, digest
from ..supervised.journal import Journal
from .email import Notice, enqueue
from .journal import record


class Health(Record):
    domain: Literal["FIXTURE", "RUNTIME_HEALTH"]
    scope: Digest
    run_id: Identifier
    executor_pid: int = Field(ge=1)
    executor_generation: int = Field(ge=1)
    observed_at: AwareDatetime
    data_at: AwareDatetime
    reconciliation_at: AwareDatetime
    audit_at: AwareDatetime
    healthy: bool
    unknown_orders: bool
    forbidden_close_exposure: bool
    envelope_expires_at: AwareDatetime


class MonitorProfile(Record):
    enabled: bool = False
    scope: Digest
    run_id: Identifier = "operations"
    max_age_seconds: int = Field(default=10, ge=1, le=60)
    poll_seconds: int = Field(default=5, ge=1, le=30)


def monitor_once(
    engine: Engine,
    profile: MonitorProfile,
    health: Health | None,
    *,
    now: datetime,
    fixture: bool = True,
) -> dict[str, object]:
    if now.tzinfo is None:
        raise ValueError("aware monitor clock required")
    if not profile.enabled:
        return {"status": "DISABLED", "financial_authority": "LIVE_NOT_AUTHORIZED"}
    issues = []
    if health is None:
        issues.append("health_missing")
    else:
        if (health.scope, health.run_id) != (
            profile.scope,
            profile.run_id,
        ) or health.executor_pid == os.getpid():
            issues.append("scope_or_monitor_independence")
        if not fixture and health.domain != "RUNTIME_HEALTH":
            issues.append("health_source_unverified")
        for name in ("observed_at", "data_at", "reconciliation_at", "audit_at"):
            if not 0 <= (now - getattr(health, name)).total_seconds() <= profile.max_age_seconds:
                issues.append("stale_or_future_" + name)
        if not health.healthy or health.unknown_orders or health.forbidden_close_exposure:
            issues.append("runtime_unhealthy_or_exposed")
        if now >= health.envelope_expires_at:
            issues.append("authority_expired")
    with Journal(engine).transaction() as conn:
        row = conn.execute(
            select(ops_monitors).where(ops_monitors.c.scope == profile.scope).with_for_update()
        ).first()
        state: dict[str, Any] = (
            json.loads(row.document)
            if row
            else {"episode": 0, "active": None, "last_at": None, "executor_generation": None}
        )
        if state["last_at"] is not None and now < datetime.fromisoformat(state["last_at"]):
            issues.append("monitor_clock_rewind")
        if (
            health is not None
            and state.get("last_input_at") is not None
            and health.observed_at < datetime.fromisoformat(state["last_input_at"])
        ):
            issues.append("input_clock_rewind")
        mail_rows = conn.execute(
            select(ops_mail).where(ops_mail.c.scope == profile.scope).limit(1001)
        ).all()
        if len(mail_rows) > 1000:
            issues.append("mail_history_budget_exceeded")
        for mail in mail_rows:
            document = json.loads(mail.document)
            notice = Notice.model_validate_json(json.dumps(document["notice"]))
            if notice.run_id != profile.run_id:
                continue
            if mail.status in {"UNKNOWN", "REJECTED"} and document.get("resolved_at") is None:
                issues.append("email_delivery_failed")
                break
            if (
                mail.status == "ACCEPTED"
                and document.get("ack_deadline") is not None
                and now >= datetime.fromisoformat(document["ack_deadline"])
            ):
                issues.append("email_ack_overdue")
                break
        if (
            health is not None
            and state["executor_generation"] is not None
            and health.executor_generation != state["executor_generation"]
        ):
            issues.append("executor_restart_review_required")
        issue_hash = digest(sorted(issues)) if issues else None
        message_id = None
        if issue_hash is not None and issue_hash != state["active"]:
            state["episode"] += 1
            incident = digest(
                {"scope": profile.scope, "episode": state["episode"], "issues": issue_hash}
            )
            message_id = enqueue(
                conn,
                Notice(
                    domain="FIXTURE" if fixture else "OPERATIONAL_NOTICE",
                    scope=profile.scope,
                    incident_hash=incident,
                    run_id=profile.run_id,
                    code="MONITOR_MISSING" if health is None else "CONTROL_INCIDENT",
                    at=now,
                ),
            )
            record(
                conn,
                profile.scope,
                "monitor_incident",
                {"incident": incident, "issues": sorted(issues), "at": now.isoformat()},
            )
        state["active"] = issue_hash
        # Rewind/restart evidence is retained; monitoring cannot accept a new executor generation.
        if state["last_at"] is None or now >= datetime.fromisoformat(state["last_at"]):
            state["last_at"] = now.isoformat()
        if health is not None and health.scope == profile.scope and health.observed_at <= now:
            previous_input = state.get("last_input_at")
            if previous_input is None or health.observed_at >= datetime.fromisoformat(
                previous_input
            ):
                state["last_input_at"] = health.observed_at.isoformat()
        if health is not None and state["executor_generation"] is None:
            state["executor_generation"] = health.executor_generation
        if row is None:
            conn.execute(
                ops_monitors.insert().values(scope=profile.scope, document=json.dumps(state))
            )
        else:
            conn.execute(
                ops_monitors.update()
                .where(ops_monitors.c.scope == profile.scope)
                .values(document=json.dumps(state))
            )
    return {
        "status": "ALERT" if issues else "OBSERVED_HEALTHY",
        "issues": sorted(issues),
        "message_id": message_id,
        "monitor_pid": os.getpid(),
        "financial_authority": "LIVE_NOT_AUTHORIZED",
    }
