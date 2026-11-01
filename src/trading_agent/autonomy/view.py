"""Persisted synthetic read model. No issuer, executor, artifact path or inference."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.engine import Connection

from ..config.models import TradingConfig
from ..db.schema import (
    m7_accounts,
    m7_audit,
    m7_changes,
    m7_envelopes,
    m7_monitor,
    m7_notices,
    m7_orders,
    m7_runtime,
)
from ..supervised.contracts import Order, State, digest
from ..supervised.readiness import fresh
from ..supervised.view import safe_audit
from .contracts import Champion, Envelope, Heartbeat, Runtime, Signed, verify
from .package import unsigned_package


def project(
    conn: Connection, config: TradingConfig, *, now: datetime, run_id: str | None = None
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "authority": "LIVE_NOT_AUTHORIZED",
        "actual_dispatch_allowed": False,
        "runtime_approved_capital_usd": "0",
        "real_authorization": None,
        "automatic_change_class": "NONE",
        "as_of": now.isoformat(),
        "package": unsigned_package(),
        "mock": None,
        "orders": [],
        "history": [],
        "incidents": [],
        "audit": [],
        "integration_evidence": "EXTERNAL_VALIDATION_PENDING",
        "investment_evidence": "EXTERNAL_VALIDATION_PENDING",
    }
    if config.app.mode.value != "simulation":
        return result
    key = digest("M7 fictional account, not a brokerage identity")
    raw = conn.execute(
        select(m7_accounts.c.document).where(m7_accounts.c.account_key == key)
    ).scalar_one_or_none()
    if raw is None:
        return result
    state = State.model_validate_json(raw)
    if (
        state.domain != "M7_MOCK_ONLY"
        or state.account_alias != "m7-fixture"
        or (run_id is not None and state.run_id != run_id)
    ):
        return result
    row = conn.execute(select(m7_envelopes).where(m7_envelopes.c.account_key == key)).one()
    envelope = verify(Signed.model_validate_json(row.document), Envelope, role="fixture_owner")
    runtime = Runtime.model_validate_json(
        conn.execute(
            select(m7_runtime.c.document).where(m7_runtime.c.account_key == key)
        ).scalar_one()
    )
    if envelope.digest() != runtime.envelope_hash or row.intent_hash != envelope.digest():
        raise ValueError("persisted envelope integrity failure")
    frozen = conn.execute(
        select(m7_changes.c.document).where(
            m7_changes.c.account_key == key, m7_changes.c.kind == "CHAMPION_FROZEN"
        )
    ).scalar_one()
    content = json.loads(frozen)["champion_content"]
    if hashlib.sha256(content.encode()).hexdigest() != envelope.champion_hash:
        raise ValueError("persisted champion integrity failure")
    champion = Champion.model_validate_json(content)
    monitor_raw = conn.execute(
        select(m7_monitor.c.document).where(m7_monitor.c.account_key == key)
    ).scalar_one_or_none()
    heartbeat = (
        verify(Signed.model_validate_json(monitor_raw), Heartbeat, role="fixture_monitor")
        if monitor_raw
        else None
    )
    monitor_current = bool(
        heartbeat
        and heartbeat.healthy
        and heartbeat.executor_generation == state.executor_generation
        and heartbeat.envelope_hash == envelope.digest()
        and fresh(heartbeat.observed_at, now, envelope.monitoring.max_heartbeat_age_seconds)
    )
    result["mock"] = {
        "label": "M7_MOCK_ONLY — synthetic envelope; no real authorization",
        "scope": {
            "mode": "simulation",
            "target_mode": "bounded_autonomous_live",
            "account_alias": state.account_alias,
            "run_id": state.run_id,
        },
        "envelope": envelope.model_dump(mode="json"),
        "envelope_hash": envelope.digest(),
        "champion": champion.model_dump(mode="json"),
        "champion_hash": envelope.champion_hash,
        "envelope_current": not row.revoked and envelope.starts_at <= now < envelope.expires_at,
        "revoked": bool(row.revoked),
        "paused": state.paused,
        "resumed": state.resumed,
        "executor_generation": state.executor_generation,
        "artifact_set": runtime.artifact_set,
        "open_incidents": list(runtime.open_incidents),
        "cash": str(state.cash),
        "reserved_cash": str(state.reserved_cash),
        "high_water_mark": str(state.high_water_mark),
        "monitor_current": monitor_current,
        "monitor": heartbeat.model_dump(mode="json") if heartbeat else None,
        "health": {
            name: getattr(state, name).model_dump(mode="json")
            for name in ("data", "reconciliation", "audit")
        },
        "learning_changes": "Journal and proposals only. Champion and envelope remain frozen.",
    }
    totals = {}
    for table, field in (
        (m7_orders, "orders"),
        (m7_changes, "history"),
        (m7_notices, "incidents"),
        (m7_audit, "audit"),
    ):
        query = select(table).where(table.c.account_key == key)
        if table is m7_audit:
            query = query.where(table.c.run_id == state.run_id).order_by(table.c.sequence.desc())
        else:
            query = query.order_by(*table.primary_key.columns)
        for event in conn.execute(query.limit(100)):
            if table is m7_orders:
                order = Order.model_validate_json(event.document).model_dump(mode="json")
                order["envelope_id"] = order.pop("approval_id")
                result[field].append(order)
            elif table is m7_audit:
                data = json.loads(event.payload)
                for name in ("before", "after"):
                    if isinstance(data.get(name), dict):
                        data[name].pop("config_json", None)
                        data[name].pop("authorization", None)
                result[field].append(
                    {
                        "sequence": event.sequence,
                        "at": event.at,
                        "event_type": event.event_type,
                        "payload": safe_audit(data),
                    }
                )
            else:
                data = json.loads(event.document)
                data.pop("champion_content", None)
                result[field].append(
                    safe_audit(
                        {"kind": event.kind, **data}
                        if table is m7_changes
                        else {**data, "acknowledged": event.acknowledged}
                    )
                )
        totals[field] = {
            "returned": len(result[field]),
            "total": conn.execute(
                select(func.count()).select_from(table).where(table.c.account_key == key)
            ).scalar_one(),
        }
    result["coverage"] = totals
    return result
