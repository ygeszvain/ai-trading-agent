"""Owner-run public-client OAuth, pinned to verified official Robinhood metadata.

No broker tools, order submission, account enumeration or activation occurs here.
Development verification injects a fake HTTP transport; no real login is tested.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import os
import pwd
import re
import secrets
import stat
import time
import webbrowser
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

from ..security.files import read_private_json, write_private_json

RESOURCE = "https://agent.robinhood.com/mcp/trading"
RESOURCE_METADATA = "https://agent.robinhood.com/.well-known/oauth-protected-resource/mcp/trading"
SERVER_METADATA = "https://agent.robinhood.com/.well-known/oauth-authorization-server/mcp/trading"
PROFILE: dict[str, Any] = {
    "issuer": RESOURCE,
    "authorization_endpoint": "https://robinhood.com/oauth",
    "token_endpoint": "https://api.robinhood.com/oauth2/token/",
    "registration_endpoint": "https://agent.robinhood.com/oauth/trading/register",
    "scopes_supported": ["internal"],
    "code_challenge_methods_supported": ["S256"],
    "token_endpoint_auth_methods_supported": ["none"],
    "authorization_response_iss_parameter_supported": True,
}


class AuthError(RuntimeError):
    """Classified failure; never include raw OAuth bodies, codes, URLs or tokens."""


def _callback(url: str) -> None:
    try:
        parsed = urlsplit(url)
        valid = (
            parsed.scheme == "http"
            and parsed.hostname == "127.0.0.1"
            and parsed.port is not None
            and 0 < parsed.port < 65536
            and parsed.path == "/callback"
            and not parsed.username
            and not parsed.password
            and not parsed.query
            and not parsed.fragment
        )
    except ValueError:
        valid = False
    if not valid:
        raise AuthError("exact loopback callback required")


def owner_root(path: Path, *, checkout: Path | None = None) -> Path:
    """Requires a separate OS identity. No environment switch bypasses this check."""
    repository = checkout or Path(__file__).resolve().parents[3]
    if pwd.getpwuid(os.getuid()).pw_name != "ai-trading-executor" or os.getuid() != os.geteuid():
        raise AuthError("owner authentication requires a separate runtime OS identity")
    root = path.expanduser().absolute()
    if root.is_symlink() or root.resolve().is_relative_to(repository.resolve()):
        raise AuthError("runtime credential directory must be outside the source checkout")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = root.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise AuthError("runtime directory must be owned by runtime user and mode 0700")
    # Parent symlinks and group/public-writable directories can redirect secrets.
    cursor = root
    while cursor != cursor.parent:
        if cursor.is_symlink() or cursor.stat().st_mode & 0o022:
            raise AuthError("runtime path contains a symlink or writable ancestor")
        cursor = cursor.parent
    return root


def _object(response: httpx.Response) -> dict[str, Any]:
    if response.status_code not in (200, 201) or len(response.content) > 65536:
        raise AuthError("official authentication request rejected or unavailable")
    try:
        value = response.json()
    except ValueError:
        raise AuthError("invalid official authentication response") from None
    if not isinstance(value, dict):
        raise AuthError("invalid official authentication response")
    return value


class OAuth:
    def __init__(self, http: httpx.Client, *, root: Path | None = None) -> None:
        # An exact MockTransport cannot reach a real account; all other transports
        # require the owner-runtime identity before registration/token operations.
        if type(http._transport) is not httpx.MockTransport:
            if root is None:
                raise AuthError("owner-runtime credential directory required")
            owner_root(root)
        self.http = http

    def inspect(self) -> dict[str, Any]:
        try:
            resource = _object(self.http.get(RESOURCE_METADATA, follow_redirects=False))
            server = _object(self.http.get(SERVER_METADATA, follow_redirects=False))
        except httpx.HTTPError:
            raise AuthError("public authentication metadata unavailable") from None
        if (
            resource.get("resource") != RESOURCE
            or resource.get("authorization_servers") != [RESOURCE]
            or resource.get("scopes_supported") != ["internal"]
            or any(server.get(key) != expected for key, expected in PROFILE.items())
        ):
            raise AuthError("official authentication metadata changed; owner review required")
        profile_hash = hashlib.sha256(json.dumps(PROFILE, sort_keys=True).encode()).hexdigest()
        return {
            "metadata_hash": profile_hash,
            "scope": "internal",
            "scope_is_read_only": False,
            "dispatch_allowed": False,
        }

    def register(self, callback: str) -> str:
        _callback(callback)
        self.inspect()
        try:
            result = _object(
                self.http.post(
                    PROFILE["registration_endpoint"],
                    json={
                        "client_name": "AI Trading Agent owner runtime",
                        "redirect_uris": [callback],
                        "token_endpoint_auth_method": "none",
                        "grant_types": ["authorization_code", "refresh_token"],
                        "response_types": ["code"],
                    },
                    follow_redirects=False,
                )
            )
        except httpx.HTTPError:
            raise AuthError("client registration unavailable; no automatic retry") from None
        client = result.get("client_id")
        if (
            not isinstance(client, str)
            or not 1 <= len(client) <= 2048
            or any(ord(char) < 32 for char in client)
            or result.get("redirect_uris") != [callback]
            or result.get("token_endpoint_auth_method", "none") != "none"
        ):
            raise AuthError("unverified client registration response")
        return client

    def exchange(self, *, client: str, code: str, verifier: str, callback: str, root: Path) -> None:
        if (root / "oauth.json").exists():
            raise AuthError("credential record already exists; explicit recovery required")
        _callback(callback)
        self.inspect()  # do not send a code to changed token endpoints
        try:
            result = _object(
                self.http.post(
                    PROFILE["token_endpoint"],
                    data={
                        "grant_type": "authorization_code",
                        "client_id": client,
                        "code": code,
                        "code_verifier": verifier,
                        "redirect_uri": callback,
                        "resource": RESOURCE,
                    },
                    follow_redirects=False,
                )
            )
        except httpx.HTTPError:
            raise AuthError("token exchange outcome unclear; start a new owner flow") from None
        token = result.get("access_token")
        expiry = result.get("expires_in")
        refresh = result.get("refresh_token")
        if (
            not isinstance(token, str)
            or not token
            or len(token) > 16384
            or any(ord(char) < 33 for char in token)
            or result.get("token_type", "").lower() != "bearer"
            or type(expiry) is not int
            or not 0 < expiry <= 31536000
            or (
                refresh is not None
                and (not isinstance(refresh, str) or not refresh or len(refresh) > 16384)
            )
            or result.get("scope", "internal") != "internal"
        ):
            raise AuthError("token contract unverified; runtime remains disabled")
        record = {
            "resource": RESOURCE,
            "issuer": PROFILE["issuer"],
            "access_token": token,
            "refresh_token": refresh,
            "client_id": client,
            "expires_at": time.time() + expiry,
            "scope": "internal",
            "financial_authority": "LIVE_NOT_AUTHORIZED",
        }
        if not write_private_json(root / "oauth.json", record, replace=False):
            raise AuthError("credential record already exists; explicit recovery required")


class Attempt:
    """One short-lived, one-use callback with exact state and issuer binding."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self.deadline = clock() + 300
        self.state = secrets.token_urlsafe(32)
        self.verifier = secrets.token_urlsafe(48)
        self.used = False

    def url(self, client: str, callback: str) -> str:
        _callback(callback)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(self.verifier.encode()).digest())
            .decode()
            .rstrip("=")
        )
        return (
            str(PROFILE["authorization_endpoint"])
            + "?"
            + urlencode(
                {
                    "client_id": client,
                    "redirect_uri": callback,
                    "response_type": "code",
                    "scope": "internal",
                    "state": self.state,
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                    "resource": RESOURCE,
                }
            )
        )

    def accept(self, query: str) -> str:
        values = parse_qs(query, keep_blank_values=True, max_num_fields=10)
        if self.used or self.clock() >= self.deadline:
            raise AuthError("authorization callback expired or already consumed")
        if (
            any(len(value) != 1 for value in values.values())
            or not hmac.compare_digest(values.get("state", [""])[0], self.state)
            or values.get("iss") != [PROFILE["issuer"]]
        ):
            raise AuthError("authorization callback state or issuer mismatch")
        self.used = True
        code = values.get("code", [""])[0]
        if "error" in values or not code or len(code) > 4096:
            raise AuthError("owner authorization denied or response invalid")
        return code


def login(path: Path) -> dict[str, Any]:
    root = owner_root(path)  # before HTTP construction, browser or token access
    if (root / "oauth.json").exists():
        raise AuthError("existing credential requires explicit recovery; login not repeated")
    if not write_private_json(
        root / "auth-attempt.json",
        {
            "started_at": time.time(),
            "phase": "OWNER_FLOW_STARTED",
            "authority": "LIVE_NOT_AUTHORIZED",
            "recovery": "Do not blindly repeat an unclear login; review/revoke with broker first",
        },
        replace=False,
    ):
        raise AuthError("prior owner flow requires explicit recovery review")
    attempt = Attempt()
    received: list[str] = []

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass  # callback URL carries a code; never log it

        def do_GET(self) -> None:
            split = urlsplit(self.path)
            expected = "127.0.0.1:" + str(cast(tuple[str, int], self.server.server_address)[1])
            if (
                self.headers.get("Host") != expected
                or split.path != "/callback"
                or split.scheme
                or split.netloc
            ):
                self.send_error(400, "invalid callback")
                return
            try:
                received.append(attempt.accept(split.query))
            except (AuthError, ValueError):
                self.send_error(400, "authorization callback rejected")
                return
            self.send_response(200)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", "default-src 'none'")
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Authorization received. Return to the owner runtime terminal.")

    with (
        HTTPServer(("127.0.0.1", 0), Callback) as server,
        httpx.Client(
            timeout=20,
            follow_redirects=False,
            trust_env=False,
        ) as http,
    ):
        server.timeout = 1
        callback = (
            "http://127.0.0.1:" + str(cast(tuple[str, int], server.server_address)[1]) + "/callback"
        )
        oauth = OAuth(http, root=root)
        client = oauth.register(callback)
        try:
            opened = webbrowser.open(attempt.url(client, callback))
        except Exception:
            raise AuthError("owner runtime browser unavailable") from None
        if not opened:
            raise AuthError("owner runtime browser unavailable; no URL or code printed")
        while not received and not attempt.used and time.monotonic() < attempt.deadline:
            server.handle_request()
        if not received:
            raise AuthError("owner sign-in timed out; no automatic retry")
        oauth.exchange(
            client=client, code=received[0], verifier=attempt.verifier, callback=callback, root=root
        )
    write_private_json(
        root / "auth-attempt.json",
        {
            "completed_at": time.time(),
            "phase": "OWNER_AUTHENTICATED_DISPATCH_DISABLED",
            "authority": "LIVE_NOT_AUTHORIZED",
        },
        replace=True,
    )
    return {
        "authentication": "OWNER_COMPLETED",
        "scope": "internal",
        "live_dispatch_allowed": False,
        "authority": "LIVE_NOT_AUTHORIZED",
    }


def _credential_record(root: Path) -> dict[str, Any]:
    record = read_private_json(root / "oauth.json")
    expiry = record.get("expires_at")
    token = record.get("access_token")
    if (
        record.get("resource") != RESOURCE
        or record.get("issuer") != PROFILE["issuer"]
        or record.get("scope") != "internal"
        or not isinstance(expiry, (int, float))
        or isinstance(expiry, bool)
        or not math.isfinite(expiry)
        or expiry <= 0
        or not isinstance(token, str)
        or not 1 <= len(token) <= 16384
        or any(ord(char) < 33 for char in token)
    ):
        raise AuthError("private credential contract unverified")
    return record


def status(path: Path) -> dict[str, Any]:
    root = owner_root(path)
    record = _credential_record(root)
    return {
        "credential_present": True,
        "expired": time.time() >= record["expires_at"],
        "scope": record["scope"],
        "authority": "LIVE_NOT_AUTHORIZED",
        "account_binding_verified": False,
        "live_dispatch_allowed": False,
    }


def discover(path: Path) -> dict[str, Any]:
    """Owner-runtime schema observation only; never enumerate accounts or call tools."""
    from ..execution.mcp_client import PROTOCOL_VERSION, McpClient

    root = owner_root(path)
    record = _credential_record(root)
    if (
        record.get("resource") != RESOURCE
        or record.get("issuer") != PROFILE["issuer"]
        or time.time() >= record.get("expires_at", 0)
        or not isinstance(record.get("access_token"), str)
    ):
        raise AuthError("credential scope or expiry unverified")
    with httpx.Client(timeout=20, follow_redirects=False, trust_env=False) as http:
        OAuth(http, root=root).inspect()
        with McpClient(RESOURCE, token=record["access_token"], http=http) as client:
            initialized = client.initialize()
            if initialized.get("protocolVersion") != PROTOCOL_VERSION:
                raise AuthError("broker protocol version requires reviewed compatibility")
            tools = client.list_tools()
    if not 1 <= len(tools) <= 256:
        raise AuthError("broker tool list outside observation budget")
    if any(
        not isinstance(tool.get("name"), str)
        or not tool.get("name")
        or not isinstance(tool.get("inputSchema"), dict)
        for tool in tools
    ):
        raise AuthError("broker tool schema unavailable")
    names = [tool["name"] for tool in tools]
    if len(names) != len(set(names)):
        raise AuthError("duplicate broker tool names")
    manifest = {
        "protocol_version": PROTOCOL_VERSION,
        "tools": sorted(tools, key=lambda t: t["name"]),
    }
    raw = json.dumps(manifest, sort_keys=True).encode()
    if len(raw) > 60000:
        raise AuthError("tool manifest exceeds private observation budget")
    digest = hashlib.sha256(raw).hexdigest()
    write_private_json(root / ("tools-" + digest + ".json"), manifest, replace=False)
    documented_reads = {
        "get_accounts",
        "get_portfolio",
        "get_equity_positions",
        "get_equity_orders",
        "get_pnl_trade_history",
        "get_equity_quotes",
        "get_equity_tradability",
        "get_trade_approval_setting",
    }
    summaries = []
    for tool in tools:
        if tool["name"] not in documented_reads:
            continue
        schema = tool["inputSchema"]
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            continue
        fields = {}
        for name, field in properties.items():
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", name) or not isinstance(
                field, dict
            ):
                continue
            kind = field.get("type")
            if isinstance(kind, str) and kind in {
                "string",
                "number",
                "integer",
                "boolean",
                "array",
                "object",
                "null",
            }:
                fields[name] = kind
        summaries.append(
            {"tool": tool["name"], "field_types_only": fields, "complete_schema": False}
        )
    return {
        "schema_observed": True,
        "tool_count": len(tools),
        "schema_hash": digest,
        "protocol_version": PROTOCOL_VERSION,
        "documented_read_schema_summaries": summaries,
        "account_binding_verified": False,
        "schema_approved_for_execution": False,
        "live_dispatch_allowed": False,
        "authority": "LIVE_NOT_AUTHORIZED",
    }
