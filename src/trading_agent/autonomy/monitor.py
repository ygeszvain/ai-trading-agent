"""Independent read-only fixture monitor process. No broker/executor/owner issuer."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, select, text

from ..db.schema import m7_accounts, m7_envelopes, m7_orders, m7_runtime
from ..supervised.contracts import Order, State
from ..supervised.readiness import config_for, fresh
from .artifacts import ArtifactVault, dependency_bytes, execution_code_bytes
from .contracts import MOCK_MONITOR_KEY, Envelope, Heartbeat, Runtime, Signed, verify
from .store import Store, schema_hash


def observe(db: str, key: str, root: Path, now: datetime) -> Signed:
    engine = create_engine(db)
    with engine.connect() as conn:
        if engine.dialect.name == "sqlite":
            conn.exec_driver_sql("PRAGMA query_only=ON")
        else:
            conn.execute(text("SET TRANSACTION READ ONLY"))
        state = State.model_validate_json(
            conn.execute(
                select(m7_accounts.c.document).where(m7_accounts.c.account_key == key)
            ).scalar_one()
        )
        runtime = Runtime.model_validate_json(
            conn.execute(
                select(m7_runtime.c.document).where(m7_runtime.c.account_key == key)
            ).scalar_one()
        )
        row = conn.execute(select(m7_envelopes).where(m7_envelopes.c.account_key == key)).one()
        envelope = verify(Signed.model_validate_json(row.document), Envelope, role="fixture_owner")
        issues = []
        if envelope.digest() != runtime.envelope_hash or row.revoked:
            issues.append("envelope_changed_or_revoked")
        if not envelope.starts_at <= now < envelope.expires_at:
            issues.append("authorization_expired")
        if schema_hash(engine) != envelope.database_schema_hash:
            issues.append("database_schema_drift")
        if runtime.observed_schema_hash != envelope.tool_schema_hash:
            issues.append("tool_schema_drift")
        if runtime.observed_permissions_hash != envelope.permissions_hash:
            issues.append("permission_drift")
        if (
            envelope.overnight_policy == "FORBID"
            and envelope.session_at(now) is None
            and any(position.quantity for position in state.holdings)
        ):
            issues.append("overnight_exposure_not_permitted")
        try:
            vault = ArtifactVault(root / runtime.artifact_set)
            champion = vault.champion(envelope.champion_hash)
            code = next(a.content_hash for a in champion.artifacts if a.role == "code")
            if vault.get(code) != execution_code_bytes():
                issues.append("execution_code_changed")
            dependencies = next(
                a.content_hash for a in champion.artifacts if a.role == "dependencies"
            )
            if vault.get(dependencies) != dependency_bytes():
                issues.append("dependency_lock_changed")
        except (ValueError, OSError):
            issues.append("champion_artifact_changed")
        order_rows: list[str] = list(
            conn.execute(
                select(m7_orders.c.document).where(m7_orders.c.account_key == key)
            ).scalars()
        )
        if any(
            Order.model_validate_json(raw).status
            in {"unknown", "submission_pending", "manual_review", "broker_approval_required"}
            for raw in order_rows
        ):
            issues.append("unresolved_orders")
        cfg = config_for(state)
        for name in ("data", "reconciliation", "audit"):
            health = getattr(state, name)
            if health.status != "healthy" or not fresh(
                health.as_of, now, cfg.risk.max_account_state_age_seconds
            ):
                issues.append(name + "_unhealthy_or_stale")
        if not fresh(state.account_as_of, now, cfg.risk.max_account_state_age_seconds) or not fresh(
            state.quote.as_of, now, cfg.risk.max_quote_age_seconds
        ):
            issues.append("account_or_quote_stale")
        report = Heartbeat(
            monitor_id=envelope.monitoring.monitor_id,
            account_key=key,
            envelope_hash=envelope.digest(),
            champion_hash=runtime.champion_hash,
            schema_hash=runtime.observed_schema_hash,
            permissions_hash=runtime.observed_permissions_hash,
            executor_generation=state.executor_generation,
            observed_at=now,
            healthy=not issues,
            process_id=os.getpid(),
            sequence=runtime.monitor_sequence + 1,
            issues=tuple(issues),
        )
    engine.dispose()
    payload = report.model_dump_json()
    return Signed(
        role="fixture_monitor",
        payload_json=payload,
        signature=hmac.new(MOCK_MONITOR_KEY, payload.encode(), hashlib.sha256).hexdigest(),
    )


def run_monitor(store: Store, key: str, artifacts: Path, now: datetime) -> Heartbeat:
    """Separate process: only sanitized fixture DB URL/paths, no secret environment."""
    request = {
        "db": store.engine.url.render_as_string(hide_password=True),
        "key": key,
        "artifacts": str(artifacts.resolve()),
        "at": now.isoformat(),
    }
    completed = subprocess.run(
        [sys.executable, "-m", "trading_agent.autonomy.monitor"],
        input=json.dumps(request),
        capture_output=True,
        text=True,
        timeout=15,
        env={
            k: v
            for k, v in os.environ.items()
            if k in {"PATH", "PYTHONPATH", "TMPDIR", "VIRTUAL_ENV", "SYSTEMROOT"}
        },
    )
    if completed.returncode:
        raise ValueError("independent fixture monitor failed; no automatic recovery or authority")
    proof = Signed.model_validate_json(completed.stdout)
    store.accept_heartbeat(proof)
    return verify(proof, Heartbeat, role="fixture_monitor")


def main() -> None:
    try:
        raw = sys.stdin.buffer.read(8193)
        if len(raw) > 8192:
            raise ValueError("request over budget")
        data = json.loads(raw)
        if set(data) != {"db", "key", "artifacts", "at"}:
            raise ValueError("unknown monitor fields")
        db = data["db"]
        # The process is fixture-only; no arbitrary remote DB/credential injection.
        if (
            not db.startswith("sqlite:///")
            and db != "postgresql+psycopg://review@127.0.0.1:55433/m7_review"
        ):
            raise ValueError("non-fixture database")
        print(
            observe(
                db, data["key"], Path(data["artifacts"]), datetime.fromisoformat(data["at"])
            ).model_dump_json()
        )
    except Exception:
        print('{"error":"fixture monitor unavailable"}')
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
