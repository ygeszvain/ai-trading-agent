"""Scoped persisted review, snapshot notifications and bounded synthetic exports.

No inference, broker transport, owner issuer, configuration mutation or replay
execution is imported. Cursors carry read scope only, never financial authority.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import time
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config.models import TradingConfig
from ..db.schema import (
    activity_events,
    data_quality,
    ledger_events,
    market_bars,
    portfolio_snapshots,
    reconciliation_runs,
    research_evaluations,
    research_jobs,
    risk_evaluations,
    source_registry,
)
from ..security.exports import SafeCsvWriter, redacted_evidence
from .queries import _envelope, get_equity_curve, get_health, get_overview, resolve_run

SECTIONS = {"data", "research", "risk", "performance", "health", "alerts", "audit"}


def _exact(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _exact(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_exact(item) for item in value]
    return value


def _rows(session: Session, table: Any, run: Any) -> dict[str, Any]:
    scope = [table.c.run_id == run.run_id]
    if "account_alias" in table.c:
        scope.append(table.c.account_alias == run.account_alias)
    if "mode" in table.c:
        scope.append(table.c.mode == run.mode)
    count = session.execute(select(func.count()).select_from(table).where(*scope)).scalar_one()
    rows = session.execute(
        select(table).where(*scope).order_by(*table.primary_key.columns).limit(100)
    ).mappings()
    return {
        "rows": redacted_evidence([_exact(dict(row)) for row in rows]),
        "total": count,
        "limit": 100,
        "ordering": "primary key; complete history retained in database",
    }


def review(
    session: Session, config: TradingConfig, run_id: str | None, section: str
) -> dict[str, Any]:
    if section not in SECTIONS:
        raise ValueError("unknown review section")
    run = resolve_run(session, config, run_id)
    payload: dict[str, Any] = {
        "section": section,
        "authority": "LIVE_NOT_AUTHORIZED",
        "live_dispatch_allowed": False,
        "evidence_status": "PERSISTED_SIMULATION_ONLY",
        "integration_evidence": "EXTERNAL_VALIDATION_PENDING",
        "investment_evidence": "EXTERNAL_VALIDATION_PENDING",
        "collections": {},
    }
    if run is not None:
        tables = {
            "data": (source_registry, data_quality, market_bars),
            "research": (research_jobs, research_evaluations),
            "risk": (risk_evaluations, reconciliation_runs),
            "performance": (portfolio_snapshots,),
            "health": (reconciliation_runs,),
            "alerts": (reconciliation_runs,),
            "audit": (activity_events, ledger_events),
        }[section]
        payload["collections"] = {t.name: _rows(session, t, run) for t in tables}
        payload["health"] = get_health(session, config, run.run_id)
        if section == "performance":
            payload["overview"] = get_overview(session, config, run.run_id)
            payload["cost_method"] = (
                "Exact ledger amounts; books separate; deposits are not returns"
            )
        if section == "alerts":
            payload["delivery_status"] = "NO_EXTERNAL_ALERT_DELIVERY_VERIFIED"
    return _envelope(
        session=session, config=config, run=run, as_of=datetime.now(UTC), payload=payload
    )


def _scope(run: Any) -> str:
    return hashlib.sha256(
        (run.run_id + "|" + run.account_alias + "|" + run.mode).encode()
    ).hexdigest()


def cursor(run: Any, sequence: int, secret: str, *, clock: float | None = None) -> str:
    stamp = time.time() if clock is None else clock
    data = json.dumps(
        {"scope": _scope(run), "sequence": sequence, "expires": stamp + 600},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    signature = hmac.new(secret.encode(), data, hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(data).decode().rstrip("=") + "." + signature


def decode(token: str, run: Any, secret: str) -> int:
    if len(token) > 2048:
        raise ValueError("cursor invalid; resnapshot required")
    try:
        encoded, signature = token.split(".")
        data = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        expected = hmac.new(secret.encode(), data, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("signature")
        parsed = json.loads(data)
        sequence = parsed["sequence"]
        if (
            parsed["scope"] != _scope(run)
            or parsed["expires"] <= time.time()
            or type(sequence) is not int
            or sequence < 0
        ):
            raise ValueError("scope")
    except (ValueError, KeyError, TypeError):
        raise ValueError("cursor invalid or expired; resnapshot required") from None
    return sequence


def bootstrap(
    session: Session, config: TradingConfig, run_id: str | None, secret: str
) -> dict[str, Any]:
    run = resolve_run(session, config, run_id)
    if run is None:
        raise ValueError("no scoped run available")
    # Both responses and cursor share the request's repeatable-read snapshot.
    sequence: int = (
        session.execute(
            select(func.max(activity_events.c.cursor)).where(
                activity_events.c.run_id == run.run_id,
                activity_events.c.account_alias == run.account_alias,
                activity_events.c.mode == run.mode,
            )
        ).scalar_one()
        or 0
    )
    return {
        "overview": get_overview(session, config, run.run_id),
        "health": get_health(session, config, run.run_id),
        "equity_curve": get_equity_curve(session, config, run.run_id),
        "cursor": cursor(run, sequence, secret),
        "sequence": sequence,
        "run_id": run.run_id,
        "read_only": True,
        "stream_method": "bounded persisted polling; no broker/model calls",
    }


def notifications(
    session: Session, config: TradingConfig, run_id: str, token: str, secret: str
) -> dict[str, Any]:
    run = resolve_run(session, config, run_id)
    if run is None:
        raise ValueError("scope unavailable; resnapshot required")
    after = decode(token, run, secret)
    maximum: int = (
        session.execute(
            select(func.max(activity_events.c.cursor)).where(
                activity_events.c.run_id == run_id,
                activity_events.c.account_alias == run.account_alias,
                activity_events.c.mode == run.mode,
            )
        ).scalar_one()
        or 0
    )
    if after > maximum:
        raise ValueError("history regressed; resnapshot required")
    rows = session.execute(
        select(activity_events)
        .where(
            activity_events.c.run_id == run_id,
            activity_events.c.cursor > after,
            activity_events.c.account_alias == run.account_alias,
            activity_events.c.mode == run.mode,
        )
        .order_by(activity_events.c.cursor)
        .limit(100)
    ).all()
    if rows and (
        rows[0].cursor != after + 1
        or any(b.cursor != a.cursor + 1 for a, b in zip(rows, rows[1:], strict=False))
    ):
        raise ValueError("notification gap; resnapshot required")
    events = [
        {
            "sequence": r.cursor,
            "at": r.ts.isoformat(),
            "type": r.event_type,
            "origin": r.origin,
            "payload": redacted_evidence(
                json.loads(r.payload) if isinstance(r.payload, str) else r.payload
            ),
        }
        for r in rows
    ]
    next_sequence = rows[-1].cursor if rows else after
    return {
        "events": events,
        "cursor": cursor(run, next_sequence, secret),
        "has_more": next_sequence < maximum,
        "run_id": run_id,
        "heartbeat_at": datetime.now(UTC).isoformat(),
        "market_freshness_unchanged": True,
        "read_only": True,
    }


def export_activity(
    session: Session, config: TradingConfig, run_id: str, token: str | None, secret: str
) -> tuple[str, str, bool]:
    run = resolve_run(session, config, run_id)
    if run is None or run.data_source != "synthetic":
        raise ValueError("export scope or source rights unverified")
    token = token or cursor(run, 0, secret)
    page = notifications(session, config, run_id, token, secret)
    buffer = io.StringIO()
    writer = SafeCsvWriter(buffer)
    writer.writerow(["mode", "run_id", "sequence", "at", "event_type", "origin", "payload"])
    for event in page["events"]:
        writer.writerow(
            [
                run.mode,
                run_id,
                event["sequence"],
                event["at"],
                event["type"],
                event["origin"],
                json.dumps(event["payload"], default=str),
            ]
        )
    return buffer.getvalue(), page["cursor"], page["has_more"]
