"""OAuth 2.1 + MCP session client for the Robinhood trading endpoint.

Implements (against ``https://agent.robinhood.com/mcp/trading``):
  * Authorization-server metadata discovery (RFC 8414 / 9728).
  * Dynamic client registration (RFC 7591) with a persistent, audited
    client id (``.data/robinhood_mcp_client.json``).
  * Authorization-code + PKCE flow with encrypted token storage.
  * Single-flight token refresh on expiry or HTTP 401.
  * MCP session lifecycle (initialize / notifications.initialized / tools).

Errors are classified into typed exceptions so callers (broker adapter,
shadow loop) can react without string matching:
  * ``McpStateError``     — protocol/session problem; safe to rebuild.
  * ``TokenRefreshRequired`` — auth failure after a failed refresh; the
    owner must re-authorize (``trading-agent broker setup``).
  * ``McpSessionError``   — transport/network problem.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from .credentials import CredentialStore, TokenRecord, TokenStoreError
from .transport import JsonRpcTransport, RpcError

log = logging.getLogger(__name__)


class McpStateError(RuntimeError):
    """MCP protocol/session-level failure (safe to rebuild the session)."""


class TokenRefreshRequired(McpStateError):
    """The credential is rejected or unrefreshable; owner re-auth required."""


class McpSessionError(RuntimeError):
    """Transport/network failure talking to the MCP endpoint."""


@dataclass(frozen=True)
class OAuthMetadata:
    """Authorization-server metadata (RFC 8414) as discovered."""

    issuer: str
    authorization_endpoint: str | None
    token_endpoint: str | None
    registration_endpoint: str | None
    redirect_uris: tuple[str, ...]


class McpOAuthClient:
    """One OAuth client + one MCP session for one endpoint."""

    def __init__(
        self,
        *,
        endpoint_url: str,
        token_store_path: Path,
        client_record_path: Path,
        phrase: str,
        http: httpx.Client | None = None,
        redirect_uri: str | None = None,
    ) -> None:
        self._endpoint_url = endpoint_url
        self._token_store_path = Path(token_store_path)
        self._client_record_path = Path(client_record_path)
        self._phrase = phrase
        self._http = http or httpx.Client(timeout=30.0)
        self._redirect_uri = redirect_uri or "http://127.0.0.1:8765/callback"
        self._metadata: OAuthMetadata | None = None
        self._client_id: str | None = None
        self._tokens: TokenRecord | None = None
        self._transport: JsonRpcTransport | None = None
        self._refresh_lock = threading.Lock()

    # ---------------------------------------------------------- discovery

    def _discover_metadata(self) -> None:
        base = urllib.parse.urlparse(self._endpoint_url)
        root = f"{base.scheme}://{base.netloc}"
        candidates = [
            self._endpoint_url + "/.well-known/oauth-protected-resource",
            f"{root}/mcp/.well-known/oauth-protected-resource",
            f"{root}/.well-known/oauth-protected-resource",
        ]
        for url in candidates:
            try:
                response = self._http.get(url, timeout=15.0)
                if response.status_code != 200:
                    continue
                data = response.json()
            except (httpx.HTTPError, json.JSONDecodeError, ValueError):
                continue
            resource_metadata = data
            server_url = data.get("authorization_servers") or [root]
            server_root = urllib.parse.urlparse(server_url[0])
            as_base = f"{server_root.scheme}://{server_root.netloc}"
            for meta_url in (
                f"{as_base}/.well-known/oauth-authorization-server/{server_root.path}".rstrip("/"),
                f"{as_base}/.well-known/openid-configuration",
                f"{as_base}/.well-known/oauth-authorization-server",
            ):
                try:
                    meta_response = self._http.get(meta_url, timeout=15.0)
                    if meta_response.status_code != 200:
                        continue
                    meta = meta_response.json()
                except (httpx.HTTPError, json.JSONDecodeError, ValueError):
                    continue
                self._metadata = OAuthMetadata(
                    issuer=str(meta.get("issuer", server_url[0])),
                    authorization_endpoint=meta.get("authorization_endpoint"),
                    token_endpoint=meta.get("token_endpoint"),
                    registration_endpoint=meta.get("registration_endpoint"),
                    redirect_uris=(self._redirect_uri,),
                )
                self._client_id = self._registered_client_id() or self._register()
                log.info(
                    "OAuth metadata resolved for %s (token_endpoint=%s, client=%s...)",
                    resource_metadata.get("resource") or self._endpoint_url,
                    (self._metadata.token_endpoint or "")[:80],
                    (self._client_id or "")[:12],
                )
                return
        raise McpStateError(
            "could not discover OAuth metadata for the MCP endpoint "
            f"(tried {len(candidates)} well-known URLs)"
        )

    def _registered_client_id(self) -> str | None:
        if not self._client_record_path.exists():
            return None
        try:
            record = json.loads(self._client_record_path.read_text())
            return record.get("client_id")
        except (json.JSONDecodeError, OSError):
            return None

    def _register(self) -> str:
        if self._metadata is None or not self._metadata.registration_endpoint:
            raise McpStateError(
                "no registration endpoint advertised; cannot create an OAuth client"
            )
        payload = {
            "client_name": "trading-agent-shadow-observer",
            "client_uri": "https://github.com/jaymontri",
            "redirect_uris": [self._redirect_uri],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",  # public client + PKCE
        }
        response = self._http.post(
            self._metadata.registration_endpoint, json=payload, timeout=20.0
        )
        if response.status_code not in (200, 201):
            raise McpStateError(
                f"dynamic client registration failed (HTTP {response.status_code}): "
                f"{response.text[:200]}"
            )
        client_id = str(response.json()["client_id"])
        self._client_record_path.parent.mkdir(parents=True, exist_ok=True)
        self._client_record_path.write_text(
            json.dumps({"client_id": client_id, "registered_at": time.time()})
        )
        self._client_record_path.chmod(0o600)
        log.info("registered MCP OAuth client %s...", client_id[:12])
        return client_id

    # ------------------------------------------------------ token lifecycle

    def _load_or_require(self) -> None:
        if self._metadata is None:
            self._discover_metadata()
        assert self._client_id
        store = CredentialStore(self._token_store_path, self._phrase)
        self._tokens = store.load()
        if self._tokens is None:
            raise TokenRefreshRequired(
                f"no credentials in {self._token_store_path}; run "
                "`trading-agent broker setup` to complete OAuth authorization"
            )
        log.info(
            "loaded vault token %s (expired=%s)",
            self._tokens.access_token_digest,
            self._tokens.is_expired(),
        )

    def _refresh(self) -> None:
        if self._metadata is None or self._tokens is None:
            raise McpStateError("cannot refresh: no metadata/tokens loaded")
        if not self._tokens.refresh_token:
            raise TokenRefreshRequired(
                "stored token has no refresh token; owner re-authorization required"
            )
        response = self._http.post(
            self._metadata.token_endpoint,
            data={
                "grant_type": "refresh_token",
                "refresh_token": self._tokens.refresh_token,
                "client_id": self._client_id,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=20.0,
        )
        if response.status_code != 200:
            raise TokenRefreshRequired(
                f"token refresh rejected (HTTP {response.status_code}); "
                "run `trading-agent broker setup`"
            )
        self._tokens = CredentialStore(
            self._token_store_path, self._phrase
        ).load() or CredentialStore(self._token_store_path, self._phrase)._persist_after_refresh(
            response.json(), self._client_id  # type: ignore[attr-defined]
        )

    def _ensure_valid_token(self) -> None:
        with self._refresh_lock:
            if self._tokens is None:
                self._load_or_require()
            if self._tokens is not None and self._tokens.is_expired():
                self._refresh()
            if self._tokens is None:
                raise TokenRefreshRequired("no usable token after refresh")

    def _auth_headers(self) -> dict[str, str]:
        self._ensure_valid_token()
        assert self._tokens is not None
        return {
            "Authorization": f"{self._tokens.token_type} {self._tokens.access_token}",
        }

    # ---------------------------------------------------------- MCP session

    def _open_transport(self) -> JsonRpcTransport:
        transport = JsonRpcTransport(self._endpoint_url, http=self._http)
        try:
            transport.request(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "trading-agent", "version": "0.4.0-m4"},
                },
            )
            transport.notify("notifications/initialized")
        except httpx.HTTPStatusError as error:
            status = error.response.status_code if error.response is not None else None
            if status in (401, 403):
                self._tokens = None
                raise TokenRefreshRequired(
                    f"MCP rejected the token (HTTP {status}); re-authorization required"
                ) from error
            raise McpSessionError(f"MCP initialize failed: HTTP {status}") from error
        except httpx.HTTPError as error:
            raise McpSessionError(f"MCP initialize transport error: {error}") from error
        self._transport = transport
        return transport

    def session_request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """One MCP request with session bootstrap + one token-refresh retry."""
        if self._transport is None:
            self._open_transport()
        assert self._transport is not None
        try:
            response = self._authed_transport_request(method, params)
        except TokenRefreshRequired:
            self.close()
            self._tokens = None
            self._transport = None
            self._open_transport()
            response = self._authed_transport_request(method, params)
        return response

    def _authed_transport_request(
        self, method: str, params: dict[str, Any] | None
    ) -> dict[str, Any]:
        assert self._transport is not None
        try:
            # The transport carries the bearer header per request.
            self._http.headers.update(self._auth_headers())
            return self._transport.request(method, params)
        except RpcError as error:
            raise McpStateError(str(error)) from error
        except httpx.HTTPStatusError as error:
            status = error.response.status_code if error.response is not None else None
            if status in (401, 403):
                self._http.headers.pop("Authorization", None)
                self._tokens = None
                raise TokenRefreshRequired(
                    f"auth failed mid-session (HTTP {status}); will re-authorize"
                ) from error
            raise McpSessionError(f"MCP request failed: HTTP {status}") from error
        except httpx.HTTPError as error:
            raise McpSessionError(f"MCP transport error: {error}") from error

    def close(self) -> None:
        if self._transport is not None:
            self._transport.close()
            self._transport = None
        self._http.headers.pop("Authorization", None)

    def __enter__(self) -> "McpOAuthClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ------------------------------------------------- OAuth authorization-code + PKCE

    def build_authorization_url(self) -> tuple[str, str, str]:
        """Return (authorization_url, state, code_verifier) for the owner's
        browser flow. The owner visits the URL, completes login/consent at
        Robinhood, and pastes the redirect URL back to the CLI."""
        if self._metadata is None:
            self._discover_metadata()
        if self._metadata is None or not self._metadata.authorization_endpoint:
            raise McpStateError("authorization endpoint not advertised by the server")
        state = secrets.token_urlsafe(24)
        verifier = secrets.token_urlsafe(48)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        query = urllib.parse.urlencode(
            {
                "response_type": "code",
                "client_id": self._client_id or "",
                "redirect_uri": self._redirect_uri,
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"{self._metadata.authorization_endpoint}?{query}", state, verifier

    def finish_authorization(
        self, redirect_url: str, *, state: str, code_verifier: str
    ) -> dict[str, Any]:
        """Exchange the pasted redirect URL's code for tokens and persist."""
        if self._metadata is None:
            self._discover_metadata()
        assert self._metadata is not None
        parsed = urllib.parse.urlparse(redirect_url)
        query = dict(urllib.parse.parse_qsl(parsed.query))
        if query.get("state") != state:
            raise TokenStoreError(
                f"OAuth state mismatch (expected {state[:8]}…, got {str(query.get('state'))[:8]}…); "
                "possible CSRF — no tokens stored"
            )
        code = query.get("code")
        if not code:
            raise TokenStoreError(
                f"no authorization code in redirect URL (error: {query.get('error')!r})"
            )
        if not self._metadata.token_endpoint:
            raise McpStateError("no token endpoint advertised")
        response = self._http.post(
            self._metadata.token_endpoint,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": self._client_id or "",
                "redirect_uri": self._redirect_uri,
                "code_verifier": code_verifier,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=20.0,
        )
        if response.status_code != 200:
            raise TokenRefreshRequired(
                f"token exchange failed (HTTP {response.status_code}); no credentials stored"
            )
        tokens = CredentialStore.exchange(
            response.json(),
            client_id=self._client_id or "",
            issuer=self._metadata.issuer,
            path=self._token_store_path,
            phrase=self._phrase,
        )
        self._tokens = tokens
        log.info(
            "OAuth authorization completed: scope=%s, token %s",
            ",".join(tokens.scopes) or "(none)",
            tokens.access_token_digest,
        )
        return {"scopes": list(tokens.scopes), "token_digest": tokens.access_token_digest}
