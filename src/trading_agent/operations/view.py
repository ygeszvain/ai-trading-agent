"""Read-only scoped operational evidence; never constructs a sender or executor."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Connection

from ..config.models import TradingConfig
from ..db.schema import m7_accounts, ops_closeouts, ops_mail, ops_records
from ..supervised.contracts import State, digest
from .email import Notice
from .reconciliation import Comparison


def project(conn: Connection, config: TradingConfig, run_id: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "authority": "LIVE_NOT_AUTHORIZED",
        "actual_dispatch_allowed": False,
        "approved_live_capital_usd": "0",
        "mode": config.app.mode.value,
        "read_only": True,
        "source": "PERSISTED_FIXTURE_ONLY",
        "run_id": None,
        "mail": [],
        "closeouts": [],
        "reconciliations": [],
        "coverage": (
            "bounded to 100 records per collection; not a full-history readiness certificate"
        ),
        "external_email_delivery": "EXTERNAL_VALIDATION_PENDING",
        "real_execution": "BLOCKED",
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
        or (run_id is not None and run_id != state.run_id)
    ):
        return result
    result["run_id"] = state.run_id
    for row in conn.execute(select(ops_mail).where(ops_mail.c.scope == key).limit(100)):
        doc = json.loads(row.document)
        if not isinstance(doc, dict) or not isinstance(doc.get("notice"), dict):
            raise ValueError("invalid persisted email document")
        notice = Notice.model_validate_json(json.dumps(doc["notice"]))
        if notice.run_id != state.run_id:
            continue
        if row.status not in {
            "PENDING",
            "SENDING",
            "ACCEPTED",
            "ACKNOWLEDGED",
            "UNKNOWN",
            "REJECTED",
        }:
            raise ValueError("invalid persisted email state")
        result["mail"].append(
            {
                "message_id": row.message_id,
                "code": notice.code,
                "status": row.status,
                "smtp_acceptance_is_not_delivery": True,
            }
        )
    for row in conn.execute(select(ops_closeouts).where(ops_closeouts.c.scope == key).limit(100)):
        doc = json.loads(row.document)
        if not isinstance(doc, dict):
            raise ValueError("invalid closeout document")
        if doc.get("run_id") != state.run_id:
            continue
        if doc.get("phase") not in {"WAITING", "FLAT", "EXIT_STARTING", "EXIT_WORKING", "BLOCKED"}:
            raise ValueError("invalid persisted closeout phase")
        result["closeouts"].append({"job_id": row.job_id, "phase": doc["phase"]})
    for row in conn.execute(
        select(ops_records.c.document)
        .where(ops_records.c.scope == key, ops_records.c.kind == "reconciliation")
        .limit(100)
    ):
        report = Comparison.model_validate_json(row.document)
        if report.run_id == state.run_id:
            result["reconciliations"].append(
                {
                    "as_of": report.as_of.isoformat(),
                    "consistent": report.consistent,
                    "differences": report.differences,
                    "snapshot_hash": report.snapshot_hash,
                    "settled_funds_verified": report.settled_funds_verified,
                }
            )
    return result
