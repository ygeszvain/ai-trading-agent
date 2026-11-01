from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select

from tests.auth_helpers import register_cookie
from trading_agent.config.loading import load_config
from trading_agent.db.schema import OPS_TABLES, web_auth, web_sessions
from trading_agent.operations.demo import run_demo
from trading_agent.web.app import build_app
from trading_agent.web.auth import SESSION_COOKIE, AuthStore


def test_operations_reads_are_scoped_private_and_have_no_mutation_or_sender(tmp_path, monkeypatch):
    demo = run_demo(tmp_path / "demo")
    engine = create_engine(
        "sqlite:///" + str((__import__("pathlib").Path(demo["journal"])).resolve())
    )
    web_auth.create(engine)
    web_sessions.create(engine)
    store = AuthStore(tmp_path / "fixture-auth", "fixture-owner", "fixture-signing")
    cookie = register_cookie(engine, store)
    cfg = load_config("config/simulation.yaml", env={})
    monkeypatch.setattr("trading_agent.web.app.create_app_engine", lambda *a, **k: engine)

    def forbidden(*args, **kwargs):
        raise AssertionError("browser read invoked financial/email/model operation")

    monkeypatch.setattr("trading_agent.operations.email.GmailSender.__init__", forbidden)
    monkeypatch.setattr("trading_agent.operations.email.Dispatcher.send_one", forbidden)
    monkeypatch.setattr("trading_agent.execution.mcp_client.McpClient.__init__", forbidden)
    monkeypatch.setattr("trading_agent.research.model_client.LocalModelClient.__init__", forbidden)
    client = TestClient(build_app(cfg, auth_store=store), base_url="http://127.0.0.1:8000")
    assert client.get("/api/v1/operations").status_code == 401
    client.cookies.set(SESSION_COOKIE, cookie)

    def counts():
        with engine.connect() as conn:
            return [
                conn.execute(select(func.count()).select_from(t)).scalar_one() for t in OPS_TABLES
            ]

    before = counts()
    result = client.get("/api/v1/operations").json()
    assert not result["actual_dispatch_allowed"] and result["approved_live_capital_usd"] == "0"
    assert result["closeouts"][0]["phase"] == "FLAT"
    assert (
        result["reconciliations"]
        and result["external_email_delivery"] == "EXTERNAL_VALIDATION_PENDING"
    )
    page = client.get("/operations")
    assert (
        page.status_code == 200
        and "LIVE_NOT_AUTHORIZED" in page.text
        and "fieldset disabled" in page.text
    )
    assert "owner@example.invalid" not in page.text
    assert client.get("/api/v1/operations?run_id=alien").json()["closeouts"] == []
    for action in ("send-email", "activate", "closeout", "resume"):
        assert client.post("/api/v1/operations/" + action).status_code == 403
    assert (
        client.get("/api/v1/operations", headers={"Origin": "https://foreign.invalid"}).status_code
        == 403
    )
    assert counts() == before
    engine.dispose()
