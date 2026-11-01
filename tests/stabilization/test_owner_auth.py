from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import pytest

from trading_agent.owner_runtime.auth import (
    PROFILE,
    RESOURCE,
    RESOURCE_METADATA,
    SERVER_METADATA,
    Attempt,
    AuthError,
    OAuth,
    _require_owner_identity,
    login,
    owner_root,
)
from trading_agent.security.files import read_private_json

CALLBACK = "http://127.0.0.1:54123/callback"


def fixture_http(*, altered=None, token_status=200):
    calls = []

    def handle(request):
        calls.append(request)
        if str(request.url) == RESOURCE_METADATA:
            return httpx.Response(
                200,
                json={
                    "resource": RESOURCE,
                    "authorization_servers": [RESOURCE],
                    "scopes_supported": ["internal"],
                },
            )
        if str(request.url) == SERVER_METADATA:
            return httpx.Response(200, json=PROFILE | (altered or {}))
        if str(request.url) == PROFILE["registration_endpoint"]:
            return httpx.Response(
                201,
                json={
                    "client_id": "fixture-public-client",
                    "redirect_uris": [CALLBACK],
                    "token_endpoint_auth_method": "none",
                },
            )
        if str(request.url) == PROFILE["token_endpoint"]:
            return httpx.Response(
                token_status,
                json={
                    "access_token": "FIXTURE-ACCESS-CANARY",
                    "refresh_token": "FIXTURE-REFRESH-CANARY",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "scope": "internal",
                },
            )
        raise AssertionError("unexpected network target")

    return httpx.Client(transport=httpx.MockTransport(handle)), calls


def test_pkce_code_exchange_is_bound_and_protected_without_broker_calls(tmp_path):
    http, calls = fixture_http()
    flow = OAuth(http)
    client = flow.register(CALLBACK)
    attempt = Attempt()
    query = parse_qs(urlsplit(attempt.url(client, CALLBACK)).query)
    assert query["code_challenge_method"] == ["S256"]
    assert query["resource"] == [RESOURCE] and "code_verifier" not in query
    response = urlencode({"state": attempt.state, "iss": PROFILE["issuer"], "code": "fixture-code"})
    code = attempt.accept(response)
    flow.exchange(
        client=client, code=code, verifier=attempt.verifier, callback=CALLBACK, root=tmp_path
    )
    record = read_private_json(tmp_path / "oauth.json")
    assert record["access_token"] == "FIXTURE-ACCESS-CANARY"
    assert record["financial_authority"] == "LIVE_NOT_AUTHORIZED"
    assert (tmp_path / "oauth.json").stat().st_mode & 0o777 == 0o600
    token_request = calls[-1]
    assert parse_qs(token_request.content.decode())["resource"] == [RESOURCE]
    assert all(str(call.url) != RESOURCE for call in calls)  # no MCP/account/order request
    assert not flow.inspect()["scope_is_read_only"]
    with pytest.raises(AuthError, match="already consumed"):
        attempt.accept(response)
    with pytest.raises(AuthError, match="already exists"):
        flow.exchange(
            client=client,
            code="other-code",
            verifier=attempt.verifier,
            callback=CALLBACK,
            root=tmp_path,
        )
    assert read_private_json(tmp_path / "oauth.json") == record


@pytest.mark.parametrize(
    "mutation",
    [
        {"token_endpoint": "https://evil.invalid/token"},
        {"issuer": "https://evil.invalid"},
        {"registration_endpoint": "https://agent.robinhood.com/changed"},
        {"code_challenge_methods_supported": ["plain"]},
        {"authorization_response_iss_parameter_supported": False},
    ],
)
def test_discovery_drift_cannot_send_registration_or_code(mutation):
    http, calls = fixture_http(altered=mutation)
    with pytest.raises(AuthError, match="metadata changed"):
        OAuth(http).register(CALLBACK)
    assert all(call.method == "GET" for call in calls)


@pytest.mark.parametrize("part", ["state", "iss", "duplicate_state", "expired", "error"])
def test_callback_rejects_csrf_mixup_replay_expiry_and_owner_denial(part):
    clock = [0.0]
    attempt = Attempt(clock=lambda: clock[0])
    values = {"state": attempt.state, "iss": PROFILE["issuer"], "code": "fixture-code"}
    if part in ("state", "iss"):
        values[part] = "wrong"
    if part == "error":
        values["error"] = "denied-fixture"
    if part == "expired":
        clock[0] = 301
    query = urlencode(values)
    if part == "duplicate_state":
        query += "&state=" + attempt.state
    with pytest.raises(AuthError):
        attempt.accept(query)


def test_unapproved_identity_is_denied_before_browser_or_auth_network(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("auth/network/browser attempted")

    monkeypatch.setattr("trading_agent.owner_runtime.auth.webbrowser.open", forbidden)
    monkeypatch.setattr("trading_agent.owner_runtime.auth.httpx.Client", forbidden)
    monkeypatch.setenv("USER", "randygeszvain")
    monkeypatch.setenv("LOGNAME", "randygeszvain")
    monkeypatch.setattr(
        "trading_agent.owner_runtime.auth.pwd.getpwuid",
        lambda uid: SimpleNamespace(pw_name="unapproved-fixture-user"),
    )
    with pytest.raises(AuthError, match="approved local OS identity"):
        login(tmp_path / "not-created")
    assert not (tmp_path / "not-created").exists()


@pytest.mark.parametrize("name", ["randygeszvain", "ai-trading-executor"])
def test_approved_identity_still_cannot_store_credentials_in_checkout(name, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "trading_agent.owner_runtime.auth.pwd.getpwuid",
        lambda uid: SimpleNamespace(pw_name=name),
    )
    _require_owner_identity()
    root = tmp_path / "checkout" / "private"
    with pytest.raises(AuthError, match="outside the source checkout"):
        owner_root(root, checkout=tmp_path / "checkout")
    assert not root.exists()


def test_approved_username_cannot_bypass_effective_uid_mismatch(monkeypatch):
    monkeypatch.setattr(
        "trading_agent.owner_runtime.auth.pwd.getpwuid",
        lambda uid: SimpleNamespace(pw_name="randygeszvain"),
    )
    monkeypatch.setattr("trading_agent.owner_runtime.auth.os.getuid", lambda: 501)
    monkeypatch.setattr("trading_agent.owner_runtime.auth.os.geteuid", lambda: 0)
    with pytest.raises(AuthError, match="approved local OS identity"):
        _require_owner_identity()


def test_token_failure_never_echoes_credentials_or_persists_success(tmp_path):
    http, calls = fixture_http(token_status=401)
    with pytest.raises(AuthError) as error:
        OAuth(http).exchange(
            client="fixture",
            code="fixture-code",
            verifier="fixture-verifier",
            callback=CALLBACK,
            root=tmp_path,
        )
    assert "CANARY" not in str(error.value) and not (tmp_path / "oauth.json").exists()


@pytest.mark.parametrize(
    "callback",
    [
        "https://evil.invalid/callback",
        "http://0.0.0.0:1234/callback",
        "http://127.0.0.1:1234/callback?token=x",
    ],
)
def test_registration_rejects_non_loopback_or_credential_bearing_callback(callback):
    http, calls = fixture_http()
    with pytest.raises(AuthError):
        OAuth(http).register(callback)
    assert not calls


def test_owner_discovery_only_lists_schemas_and_cannot_verify_account_or_execution(
    tmp_path, monkeypatch
):
    import json
    import time

    from trading_agent.execution.mcp_client import PROTOCOL_VERSION
    from trading_agent.owner_runtime.auth import discover
    from trading_agent.security.files import write_private_json

    write_private_json(
        tmp_path / "oauth.json",
        {
            "resource": RESOURCE,
            "issuer": PROFILE["issuer"],
            "expires_at": time.time() + 60,
            "scope": "internal",
            "access_token": "FIXTURE-ACCESS-CANARY",
        },
        replace=False,
    )
    public_http, _ = fixture_http()
    methods = []

    def handle(request):
        if str(request.url) != RESOURCE:
            return public_http._transport.handle_request(request)
        body = json.loads(request.content)
        methods.append(body["method"])
        if body["method"] == "notifications/initialized":
            return httpx.Response(202)
        if body["method"] == "initialize":
            result = {"protocolVersion": PROTOCOL_VERSION}
        elif body["method"] == "tools/list":
            result = {
                "tools": [
                    {
                        "name": "fixture_read_quote",
                        "inputSchema": {"type": "object"},
                        "description": "fixture",
                    }
                ]
            }
        else:
            raise AssertionError("discovery invoked broker tool")
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

    original = httpx.Client
    monkeypatch.setattr("trading_agent.owner_runtime.auth.owner_root", lambda path: tmp_path)
    monkeypatch.setattr(
        "trading_agent.owner_runtime.auth.httpx.Client",
        lambda **kw: original(transport=httpx.MockTransport(handle)),
    )
    result = discover(tmp_path)
    assert methods == ["initialize", "notifications/initialized", "tools/list"]
    assert result["schema_observed"] and not result["account_binding_verified"]
    assert not result["live_dispatch_allowed"] and not result["schema_approved_for_execution"]
    assert len(list(tmp_path.glob("tools-*.json"))) == 1
