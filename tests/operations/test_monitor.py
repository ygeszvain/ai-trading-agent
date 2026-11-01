import json
import os
import subprocess
import sys
from datetime import timedelta

from sqlalchemy import func, select

from trading_agent.autonomy.fixtures import NOW
from trading_agent.db.schema import ops_mail
from trading_agent.operations.monitor import Health, MonitorProfile, monitor_once
from trading_agent.operations.readiness import Evidence, readiness
from trading_agent.supervised.contracts import digest


def health():
    return Health(
        domain="FIXTURE",
        scope=digest("scope"),
        run_id="fixture",
        executor_pid=os.getpid() + 100000,
        executor_generation=1,
        observed_at=NOW,
        data_at=NOW,
        reconciliation_at=NOW,
        audit_at=NOW,
        healthy=True,
        unknown_orders=False,
        forbidden_close_exposure=False,
        envelope_expires_at=NOW + timedelta(days=30),
    )


def test_missing_stale_future_restart_and_recovery_do_not_flood_or_renew(ops_engine):
    cfg = MonitorProfile(enabled=True, scope=digest("scope"), run_id="fixture")
    first = monitor_once(ops_engine, cfg, None, now=NOW)
    assert first["status"] == "ALERT" and first["message_id"]
    assert monitor_once(ops_engine, cfg, None, now=NOW + timedelta(seconds=1))["message_id"] is None
    assert (
        monitor_once(ops_engine, cfg, health(), now=NOW)["status"] == "ALERT"
    )  # clock rewind retained
    assert (
        monitor_once(
            ops_engine,
            cfg,
            health().changed(observed_at=NOW + timedelta(seconds=2)),
            now=NOW + timedelta(seconds=2),
        )["status"]
        == "OBSERVED_HEALTHY"
    )
    changed = health().changed(executor_generation=2)
    assert (
        "executor_restart_review_required"
        in monitor_once(ops_engine, cfg, changed, now=NOW + timedelta(seconds=2))["issues"]
    )
    with ops_engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(ops_mail)).scalar_one() >= 2


def test_real_separate_process_detects_dead_executor_without_secrets(ops_engine):
    cfg = MonitorProfile(enabled=True, scope=digest("scope"), run_id="fixture")
    script = """import json,sys
from datetime import datetime
from sqlalchemy import create_engine
from trading_agent.operations.monitor import MonitorProfile,monitor_once
p=json.loads(sys.stdin.read())
e=create_engine(p['db'])
print(json.dumps(monitor_once(e,MonitorProfile.model_validate_json(p['profile']),None,now=datetime.fromisoformat(p['now']))))
e.dispose()
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        input=json.dumps(
            {"db": str(ops_engine.url), "profile": cfg.model_dump_json(), "now": NOW.isoformat()}
        ),
        text=True,
        capture_output=True,
        timeout=10,
        check=True,
        env={
            k: v
            for k, v in os.environ.items()
            if k in {"PATH", "PYTHONPATH", "VIRTUAL_ENV", "TMPDIR"}
        },
    )
    observed = json.loads(result.stdout)
    assert observed["monitor_pid"] != os.getpid() and observed["status"] == "ALERT"
    assert observed["financial_authority"] == "LIVE_NOT_AUTHORIZED"


def test_every_external_flag_still_cannot_activate():
    result = readiness(
        Evidence(
            email_code=True,
            closeout_code=True,
            reconciliation_code=True,
            execution_controls_code=True,
            actual_email_delivery_and_ack=True,
            deployed_independent_monitor=True,
            actual_broker_integration=True,
            prospective_strategy_evidence=True,
        )
    )
    assert (
        result["activation"] == "BLOCKED"
        and not result["actual_dispatch_allowed"]
        and result["approved_live_capital_usd"] == "0"
    )
