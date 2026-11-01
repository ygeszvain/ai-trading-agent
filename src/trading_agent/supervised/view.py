"""Read-only projection. Never imports the executor, transport, or control issuer."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.engine import Connection

from ..config.models import TradingConfig
from ..db.schema import m6_accounts, m6_approvals, m6_audit, m6_orders
from ..security.exports import redacted_evidence
from .contracts import Approval, Order, Record, Resume, Signed, State, digest, verify
from .package import unsigned_package
from .readiness import GATE_NAMES, evaluate


def safe_audit(value: Any, field: str = "") -> Any:
    # Exact public content hashes and typed money are audit bindings, not secrets.
    if isinstance(value, dict):
        return {k: safe_audit(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [safe_audit(v, field) for v in value]
    if field.endswith(("_hash", "_hashes")) or field in {
        "account_key",
        "observed_account_key",
        "cash",
        "reserved_cash",
        "quantity",
        "remaining_quantity",
        "filled_quantity",
        "price",
        "mark",
        "limit_price",
        "price_lower",
        "price_upper",
        "fee",
        "fees",
        "max_fee",
        "average_cost",
        "realized_pnl",
        "high_water_mark",
        "day_start_nav",
        "daily_turnover",
    }:
        return value
    return redacted_evidence(value)


def project(
    conn: Connection,
    config: TradingConfig,
    *,
    now: datetime,
    run_id: str | None = None,
    intent_id: str | None = None,
) -> dict[str, Any]:
    package = unsigned_package()
    payload: dict[str, Any] = {
        "authority": "LIVE_NOT_AUTHORIZED",
        "actual_dispatch_allowed": False,
        "as_of": now.isoformat(),
        "scope": {"mode": config.app.mode.value, "account_alias": None, "run_id": None},
        "runtime": {
            "mode": config.app.mode.value,
            "live_enabled": config.live.enabled,
            "approved_capital_usd": "0",
            "configured_capital_usd": str(config.live.approved_capital_usd),
            "owner_authorization_active": False,
        },
        "unmet_runtime_prerequisites": list(GATE_NAMES)
        + ["build_live_dispatch_disabled", "upstream_readiness_failures"],
        "package": package,
        "mock": None,
        "orders": [],
        "approvals": [],
        "audit": [],
        "software_evidence": "MOCK VERIFICATION ONLY",
        "integration_evidence": "EXTERNAL_VALIDATION_PENDING",
        "investment_evidence": "EXTERNAL_VALIDATION_PENDING",
    }
    if config.app.mode.value != "simulation":
        return payload
    # Only this deliberately fictional, simulation-scoped journal is ever exposed.
    state_rows: list[str] = list(
        conn.execute(
            select(m6_accounts.c.document)
            .where(
                m6_accounts.c.account_key
                == digest("M6 fictional account, not a brokerage identity")
            )
            .limit(1)
        ).scalars()
    )
    for raw in state_rows:
        state = State.model_validate_json(raw)
        if state.account_alias != "m6-fixture" or (run_id is not None and state.run_id != run_id):
            continue
        payload["scope"] = {
            "mode": "simulation",
            "target_mode": "supervised_live",
            "account_alias": state.account_alias,
            "run_id": state.run_id,
        }
        key = state.account_key
        order_rows: list[str] = list(
            conn.execute(
                select(m6_orders.c.document).where(m6_orders.c.account_key == key).limit(40)
            ).scalars()
        )
        all_orders = [Order.model_validate_json(s) for s in order_rows]
        selected = [o for o in all_orders if intent_id is None or o.intent.intent_id == intent_id]
        payload["orders"] = [o.model_dump(mode="json") for o in selected]
        consent = {}
        for row in conn.execute(
            select(m6_approvals).where(m6_approvals.c.account_key == key).limit(100)
        ):
            signed = Signed.model_validate_json(row.document)
            record: Record
            try:
                record = verify(signed, Approval)
                consent[record.approval_id] = record
                kind = "per-intent or cancellation"
            except ValueError:
                record = verify(signed, Resume)
                kind = "explicit resume"
            payload["approvals"].append(
                {
                    "kind": kind,
                    "record": record.model_dump(mode="json"),
                    "consumed": row.consumed,
                    "revoked": row.revoked,
                }
            )
        order = selected[0] if selected else None
        readiness = evaluate(
            state,
            now=now,
            intent=order.intent if order else None,
            approval=consent.get(order.approval_id) if order else None,
        )
        payload["mock"] = {
            "label": "M6_MOCK_ONLY — fictional account and fills; target mode is a test input",
            "readiness": readiness.model_dump(mode="json"),
            "cash": str(state.cash),
            "reserved_cash": str(state.reserved_cash),
            "holdings": [p.model_dump(mode="json") for p in state.holdings],
            "boot_id": state.boot_id,
            "epoch": state.epoch,
            "resumed": state.resumed,
            "paused": state.paused,
            "revoked": state.revoked,
        }
        for row in conn.execute(
            select(m6_audit)
            .where(m6_audit.c.account_key == key, m6_audit.c.run_id == state.run_id)
            .order_by(m6_audit.c.sequence.desc())
            .limit(100)
        ):
            event = json.loads(row.payload)
            # Keep exact financial before/after values, omit bulky configuration copies.
            for name in ("before", "after"):
                if isinstance(event.get(name), dict):
                    event[name] = {
                        k: v
                        for k, v in event[name].items()
                        if k not in {"config_json", "authorization"}
                    }
            payload["audit"].append(
                {
                    "sequence": row.sequence,
                    "at": row.at,
                    "event_type": row.event_type,
                    "payload": safe_audit(event),
                }
            )
        totals = {
            table.name: conn.execute(
                select(func.count()).select_from(table).where(table.c.account_key == key)
            ).scalar_one()
            for table in (m6_orders, m6_approvals, m6_audit)
        }
        payload["coverage"] = {
            "orders_returned": len(payload["orders"]),
            "orders_total": totals["m6_orders"],
            "approvals_returned": len(payload["approvals"]),
            "approvals_total": totals["m6_approvals"],
            "audit_returned": len(payload["audit"]),
            "audit_total": totals["m6_audit"],
        }
        break
    return payload
