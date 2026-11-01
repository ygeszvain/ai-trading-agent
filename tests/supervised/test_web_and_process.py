from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from tests.auth_helpers import register_cookie
from tests.supervised.test_controls import approved
from tests.supervised.test_controls import system as system
from trading_agent.config.loading import load_config
from trading_agent.db.schema import M6_TABLES, web_auth, web_sessions
from trading_agent.supervised.demo import run_demo
from trading_agent.supervised.fixtures import NOW
from trading_agent.supervised.package import unsigned_package
from trading_agent.web.app import build_app
from trading_agent.web.auth import SESSION_COOKIE, AuthStore


def test_process_demo_preserves_unsigned_package_and_authority(tmp_path):
    report = run_demo(tmp_path)
    assert report["parent_pid"] == os.getpid() and report["worker"]["pid"] != os.getpid()
    assert report["authority"] == "LIVE_NOT_AUTHORIZED" and not report["actual_dispatch_allowed"]
    assert (
        report["integration_evidence"]
        == report["investment_evidence"]
        == "EXTERNAL_VALIDATION_PENDING"
    )
    assert report["order"]["status"] == "filled" and report["order"]["filled_quantity"] == "2"
    path = Path(report["journal"]).parent
    draft = json.loads((path / "activation-package.unsigned.json").read_text())
    assert draft == unsigned_package() and draft["requested_capital_ceiling_usd"] == "1000"
    assert draft["runtime_approved_capital_usd"] == "0"
    assert draft["owner_signature"] is None and draft["dedicated_account_alias"] is None
    assert all(v is None for v in draft["limits"].values())
    assert Path(report["journal"]).stat().st_mode & 0o777 == 0o600
    second = run_demo(tmp_path)
    assert second["journal"] != report["journal"]
    assert (path / "report.json").exists()


def test_readiness_dashboard_exact_bindings_read_only_scope_and_denied_controls(
    system, monkeypatch, tmp_path
):
    journal, controls, executor, transport = system
    intent, approval = approved(system)
    executor.dispatch(intent, approval.approval_id, now=NOW)
    web_auth.create(journal.engine)
    web_sessions.create(journal.engine)
    config = load_config("config/simulation.yaml", env={})
    monkeypatch.setattr("trading_agent.web.app.create_app_engine", lambda *a, **k: journal.engine)
    store = AuthStore(tmp_path / "fixture-owner", "fixture-owner-web", "fixture-session-signing")
    cookie = register_cookie(journal.engine, store)
    app = build_app(config, auth_store=store)
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    assert client.get("/readiness", follow_redirects=False).status_code == 302
    client.cookies.set(SESSION_COOKIE, cookie)

    def forbidden(*args, **kwargs):
        raise AssertionError("read invoked control/model/broker")

    monkeypatch.setattr("trading_agent.supervised.executor.MockControls.approve", forbidden)
    monkeypatch.setattr("trading_agent.supervised.executor.MockExecutor.dispatch", forbidden)
    monkeypatch.setattr("trading_agent.research.model_client.LocalModelClient.__init__", forbidden)
    monkeypatch.setattr("trading_agent.execution.mcp_client.McpClient.__init__", forbidden)

    def counts():
        with journal.engine.connect() as conn:
            return {
                t.name: conn.execute(select(func.count()).select_from(t)).scalar_one()
                for t in M6_TABLES
            }

    before = counts()
    response = client.get("/api/v1/readiness")
    assert response.status_code == 200
    view = response.json()
    assert view["authority"] == "LIVE_NOT_AUTHORIZED" and not view["actual_dispatch_allowed"]
    assert view["runtime"]["approved_capital_usd"] == "0"
    assert view["orders"][0]["intent"] == intent.model_dump(mode="json")
    assert view["approvals"] and view["audit"]
    page = client.get("/readiness")
    assert page.status_code == 200
    for value in (
        "LIVE_NOT_AUTHORIZED",
        "UNSIGNED_BLOCKED",
        "MOCK_ONLY",
        intent.risk_snapshot_hash,
        approval.intent_hash,
    ):
        assert value in page.text
    assert "fieldset disabled" in page.text
    for action in ("approve", "activate", "dispatch", "resume", "cancel"):
        assert (
            client.post(
                "/api/v1/readiness/" + action,
                headers={"Origin": "http://127.0.0.1:8000"},
                json={"enabled": True},
            ).status_code
            == 403
        )
    assert client.get("/api/v1/readiness?run_id=alien-run").json()["orders"] == []
    assert client.get("/api/v1/readiness?intent_id=alien-intent").json()["orders"] == []
    assert client.get("/api/v1/readiness", headers={"Host": "127.0.0.1:9000"}).status_code == 403
    assert (
        client.get(
            "/api/v1/readiness", headers={"Origin": "https://unapproved.invalid"}
        ).status_code
        == 403
    )
    assert counts() == before
    assert transport.calls == [("submit", intent.intent_id)]
