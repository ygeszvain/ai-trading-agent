from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from tests.auth_helpers import register_cookie
from tests.autonomy.test_envelope import system as system
from trading_agent.autonomy.contracts import Signed
from trading_agent.autonomy.fixtures import KEY, NOW
from trading_agent.autonomy.view import project
from trading_agent.config.loading import load_config
from trading_agent.db.schema import M7_ALL_TABLES, web_auth, web_sessions
from trading_agent.web.app import build_app
from trading_agent.web.auth import SESSION_COOKIE, AuthStore


def test_persisted_dashboard_is_scoped_escaped_and_cannot_mutate(system, monkeypatch, tmp_path):
    s = system
    web_auth.create(s.store.engine)
    web_sessions.create(s.store.engine)
    with s.store.transaction() as conn:
        state = s.store.state(conn, KEY)
        s.store.event(
            conn,
            state,
            NOW,
            "fixture_untrusted_evidence",
            {
                "message": "<script>window.fixtureInjected=1</script>",
                "token": "fixture-diagnostic-omit",
            },
        )
    config = load_config("config/simulation.yaml", env={})
    monkeypatch.setattr("trading_agent.web.app.create_app_engine", lambda *a, **k: s.store.engine)
    auth = AuthStore(tmp_path / "web-owner", "fixture-owner-web", "fixture-session-signing")
    cookie = register_cookie(s.store.engine, auth)
    client = TestClient(build_app(config, auth_store=auth), base_url="http://127.0.0.1:8000")
    assert client.get("/autonomy", follow_redirects=False).status_code == 302
    assert client.get("/api/v1/autonomy").status_code == 401
    client.cookies.set(SESSION_COOKIE, cookie)

    def forbidden(*a, **k):
        raise AssertionError("website invoked authority, transport or inference")

    monkeypatch.setattr("trading_agent.autonomy.engine.AutonomousExecutor.dispatch", forbidden)
    monkeypatch.setattr("trading_agent.autonomy.engine.AutonomousExecutor.resume", forbidden)
    monkeypatch.setattr("trading_agent.autonomy.owner_fixture.sign_fixture", forbidden)
    monkeypatch.setattr("trading_agent.research.model_client.LocalModelClient.__init__", forbidden)
    monkeypatch.setattr("trading_agent.execution.mcp_client.McpClient.__init__", forbidden)

    def counts():
        with s.store.engine.connect() as conn:
            return [
                conn.execute(select(func.count()).select_from(t)).scalar_one()
                for t in M7_ALL_TABLES
            ]

    before = counts()
    view = client.get("/api/v1/autonomy").json()
    assert view["authority"] == "LIVE_NOT_AUTHORIZED" and not view["actual_dispatch_allowed"]
    assert view["runtime_approved_capital_usd"] == "0" and view["real_authorization"] is None
    assert view["automatic_change_class"] == "NONE"
    assert view["mock"]["champion_hash"] == s.envelope.champion_hash
    assert view["mock"]["envelope_hash"] == s.envelope.digest()
    assert view["mock"]["scope"]["account_alias"] == "m7-fixture"
    assert not view["mock"]["monitor_current"]  # fixture is future-dated, not current health
    page = client.get("/autonomy")
    assert page.status_code == 200 and "fieldset disabled" in page.text
    assert "<script>window.fixtureInjected" not in page.text
    assert "fixture-diagnostic-omit" not in page.text
    assert s.envelope.champion_hash in page.text and "QUEUED_LOCAL_NOT_SENT" in page.text
    assert client.get("/api/v1/autonomy?run_id=alien").json()["mock"] is None
    for action in ("activate", "renew", "resume", "promote", "preferences", "widen"):
        assert (
            client.post(
                "/api/v1/autonomy/" + action,
                headers={"Origin": "http://127.0.0.1:8000"},
                json={"capital": "99999"},
            ).status_code
            == 403
        )
    assert client.get("/api/v1/autonomy", headers={"Host": "127.0.0.1:9000"}).status_code == 403
    assert (
        client.get("/api/v1/autonomy", headers={"Origin": "https://alien.invalid"}).status_code
        == 403
    )
    assert counts() == before and s.fake.calls == []

    with s.store.transaction() as conn:
        current = project(conn, config, now=NOW)
        stale = project(conn, config, now=NOW + timedelta(seconds=20))
    assert current["mock"]["monitor_current"] and not stale["mock"]["monitor_current"]
    assert stale["mock"]["monitor"] is not None  # keep evidence when stale


def test_read_model_fails_closed_on_corrupt_snapshot(system, monkeypatch, tmp_path):
    s = system
    config = load_config("config/simulation.yaml", env={})
    from trading_agent.db.schema import m7_changes

    with s.store.transaction() as conn:
        conn.execute(
            m7_changes.update()
            .where(m7_changes.c.kind == "CHAMPION_FROZEN")
            .values(document='{"champion_content":"{}"}')
        )
    with s.store.transaction() as conn, pytest.raises(ValueError, match="integrity"):
        project(conn, config, now=NOW)


def test_monitor_replay_and_role_confusion_do_not_authorize(system):
    s = system
    with s.store.transaction() as conn:
        raw = conn.execute(select(s.store.approvals.c.document)).scalar_one()
    from trading_agent.supervised.journal import Denied

    # Owner signature cannot be used as an independent monitor signature.
    with pytest.raises(ValueError):
        s.store.accept_heartbeat(Signed.model_validate_json(raw))
    # Existing heartbeat replay does not alter state or increment monitor cursor.
    from trading_agent.db.schema import m7_monitor

    with s.store.transaction() as conn:
        proof = Signed.model_validate_json(conn.execute(select(m7_monitor.c.document)).scalar_one())
    with pytest.raises(Denied, match="sequence"):
        s.store.accept_heartbeat(proof)
