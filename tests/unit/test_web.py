"""Read-only web app: owner-token bootstrap and the loopback host guard."""

from __future__ import annotations

import stat

from fastapi.testclient import TestClient

from trading_agent.config.models import TradingConfig
from trading_agent.web import auth as web_auth
from trading_agent.web.app import build_app


def test_ensure_bootstrap_creates_600_file(tmp_path, monkeypatch) -> None:
    token_file = tmp_path / ".data" / "web_token"
    monkeypatch.setenv("TRADING_AGENT_WEB_AUTH_FILE", str(token_file))
    path, created = web_auth.ensure_bootstrap()
    assert created is True
    assert path == token_file
    assert token_file.exists()
    assert stat.S_IMODE(token_file.stat().st_mode) == 0o600

    # An existing file is never overwritten.
    path, created_again = web_auth.ensure_bootstrap()
    assert created_again is False
    assert path == token_file

    store = web_auth.load_store(path)
    assert store.owner_token and store.session_secret
    assert len(store.owner_token) >= 20


def test_host_guard_rejects_mismatched_host(valid_config_dict, monkeypatch) -> None:
    config = TradingConfig.model_validate(valid_config_dict)

    store = web_auth.AuthStore(
        path=web_auth.resolve_auth_path(),
        owner_token="owner-token-1",
        session_secret="session-secret-1",
    )
    from tests.auth_helpers import auth_only_engine, register_cookie

    engine = auth_only_engine()
    monkeypatch.setattr("trading_agent.web.app.create_app_engine", lambda *a, **kw: engine)
    app = build_app(config, auth_store=store)
    client = TestClient(app, raise_server_exceptions=False)
    cookie = f"{web_auth.SESSION_COOKIE}={register_cookie(engine, store)}"
    host_ok = f"{config.app.web_host}:{config.app.web_port}"
    host_bad = "10.0.0.5:8000"

    # Unauthenticated on a matching host → redirect to the login page.
    response = client.get("/", headers={"host": host_ok}, follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/auth/login"

    # A valid persisted session on the matching host renders the page.
    response = client.get("/", headers={"host": host_ok, "cookie": cookie})
    assert response.status_code == 200

    # The same valid session on a mismatched host is rejected outright.
    response = client.get("/", headers={"host": host_bad, "cookie": cookie})
    assert response.status_code == 403

    # The public login page renders on the matching host.
    assert client.get("/auth/login", headers={"host": host_ok}).status_code == 200
