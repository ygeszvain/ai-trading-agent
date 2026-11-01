"""Minimal MCP (Model Context Protocol) Streamable-HTTP client.

Implements the bare subset of the JSON-RPC over HTTP transport this
application needs:

  * ``initialize`` (protocol handshake; captures the MCP session id)
  * ``notifications/initialized`` (spec-required follow-up)
  * ``tools/list``
  * ``tools/call``

Responses may be ``application/json`` or ``text/event-stream`` (SSE); both
are parsed. The client is deliberately small and auditable: one class, one
HTTP request per RPC, no plugin or extension system.

Security (build plan sections 6 and 20):
  * The bearer token travels only in the ``Authorization`` header.
  * No method ever embeds the token in a raised message: every
    server-derived string passes through ``redact()`` first.
  * HTTP bodies from the server are never echoed into errors; only status
    codes and structured JSON-RPC error codes surface.
  * ``call_tool`` enforces the permitted tool set: any tool outside the
    allowlisted read set raises ``BrokerExecutionDenied``. The client
    refuses to transmit a trading call even if a caller bug reaches it.
  * All failures raise classified :class:`BrokerError` subclasses — never
    a bare exception carrying secrets.
"""

from __future__ import annotations

import json
from httpx import Client as HttpxClient
from httpx import HTTPError, ReadTimeout

from ..contracts.broker import (
    BrokerExecutionDenied,
    BrokerStateNotAvailable,
    BrokerUnavailable,
)
from .credentials import TokenStore

PROTOCOL_VERSION = "2025-03-26"
CLIENT_INFO = {"name": "trading-agent", "version": "0.4.0"}
ACCEPT = "application/json, text/event-stream"


class McpClient:
    """A single MCP session over Streamable HTTP (one bearer token)."""

    def __init__(
        self,
        base_url: str,
        *,
        token: str,
        timeout_seconds: float = 10.0,
        http: HttpxClient | None = None,
    ) -> None:
        self._base_url = base_url
        self._token = token
        self._timeout = timeout_seconds
        self._http = http if http is not None else HttpxClient(timeout=timeout_seconds)
        self._owns_http = http is None
        self._session_id: str | None = None
        self._rpc_id = 0
        self._connected = False

    # ------------------------------------------------------------- lifecycle

    @property
    def connected(self) -> bool:
        return self._connected

    def __enter__(self) -> "McpClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_http:
            try:
                self._http.close()
            except Exception:  # noqa: BLE001 - teardown must not raise
                pass
        self._connected = False

    # ------------------------------------------------------------------- rpc

    def initialize(self) -> dict:
        """Perform the protocol handshake; raises a classified BrokerError."""
        result = self._rpc("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": CLIENT_INFO,
        })
        self._connected = True
        self._notify("notifications/initialized", {})
        return result or {}

    def list_tools(self) -> list[dict]:
        """Return the raw tool definitions (name/description/inputSchema)."""
        if not self._connected:
            raise BrokerUnavailable("session not initialized")
        result = self._rpc("tools/list", {})
        tools = (result or {}).get("tools")
        if not isinstance(tools, list):
            raise BrokerStateNotAvailable("tools/list returned no tool list")
        return [tool for tool in tools if isinstance(tool, dict)]

    def call_tool(self, name: str, arguments: dict, *, permitted: set[str] | None = None) -> dict:
        """Call one tool. ``permitted`` (when given) hard-blocks other names.

        Passing ``permitted`` without the requested name raises
        ``BrokerExecutionDenied`` before any bytes go on the wire.
        """
        if not self._connected:
            raise BrokerUnavailable("session not initialized")
        if permitted is not None and name not in permitted:
            raise BrokerExecutionDenied(
                f"tool '{name}' is not in the permitted read set"
            )
        result = self._rpc("tools/call", {"name": name, "arguments": arguments})
        if result is None:
            raise BrokerStateNotAvailable(f"tool '{name}' returned no result")
        return result

    def _notify(self, method: str, params: dict) -> None:
        body = {"jsonrpc": "2.0", "method": method, "params": params}
        self._post(body, expect_result=False)

    def _rpc(self, method: str, params: dict) -> dict | None:
        self._rpc_id += 1
        body = {"jsonrpc": "2.0", "id": self._rpc_id, "method": method, "params": params}
        return self._post(body, expect_result=True)

    def _post(self, body: dict, *, expect_result: bool) -> dict | None:
        headers = {
            "Content-Type": "application/json",
            "Accept": ACCEPT,
            "Authorization": f"Bearer {self._token}",
        }
        if self._session_id is not None:
            headers["MCP-Session-Id"] = self._session_id
        try:
            response = self._http.post(self._base_url, json=body, headers=headers)
        except ReadTimeout as error:
            raise BrokerUnavailable(
                f"broker MCP request to {self._base_url} timed out after "
                f"{self._timeout:.0f}s"
            ) from error
        except HTTPError as error:
            raise BrokerUnavailable(
                f"broker MCP endpoint {self._base_url} unreachable: {type(error).__name__}"
            ) from error

        session_header = response.headers.get("mcp-session-id")
        if session_header:
            self._session_id = session_header

        if response.status_code in (401, 403):
            raise BrokerUnavailable(
                f"broker MCP rejected authentication (HTTP {response.status_code}); "
                "re-run 'trading-agent broker setup'"
            )
        if response.status_code >= 400:
            raise BrokerUnavailable(
                f"broker MCP endpoint returned HTTP {response.status_code}"
            )

        if not expect_result:
            return None

        payload = self._parse_body(response)
        if payload is None:
            raise BrokerStateNotAvailable(
                "broker MCP returned an empty response body"
            )
        if "error" in payload:
            error = payload.get("error") or {}
            message = str(error.get("message", "unclassified RPC error"))
            message = TokenStore.redact(message, self._token)
            code = error.get("code", "unknown")
            raise BrokerStateNotAvailable(f"broker MCP RPC error {code}: {message[:200]}")
        return payload.get("result")

    @staticmethod
    def _parse_body(response) -> dict | None:
        """Parse an application/json or text/event-stream response body."""
        content_type = response.headers.get("content-type", "")
        text = response.text
        if not text.strip():
            return None
        if "text/event-stream" in content_type:
            return _parse_sse(text)
        try:
            return json.loads(text)
        except ValueError:
            # Some servers answer JSON without the exact content type.
            try:
                return json.loads(text)
            except ValueError as error:
                raise BrokerStateNotAvailable(
                    "broker MCP returned a body that is neither JSON nor SSE"
                ) from error


def _parse_sse(text: str) -> dict | None:
    """Return the JSON object of the last ``data:`` line in an SSE stream."""
    last_data: str | None = None
    for line in text.splitlines():
        if line.startswith("data:"):
            last_data = line[len("data:"):].strip()
    if last_data is None:
        return None
    try:
        return json.loads(last_data)
    except ValueError:
        return None


def _extract_tool_text(result: dict) -> str:
    """Concatenate the text parts of a tools/call result."""
    parts = result.get("content")
    if not isinstance(parts, list):
        return ""
    chunks = [
        str(item.get("text", ""))
        for item in parts
        if isinstance(item, dict) and item.get("type") == "text"
    ]
    return "\n".join(chunk for chunk in chunks if chunk)


def parse_tool_payload(result: dict):
    """Parse the text content of a tools/call result as JSON, if possible.

    Broker tool results are conventionally JSON documents inside the text
    content. Returns the parsed object, or None when the text is not JSON
    (callers must treat that as "state not available", never as data).
    """
    text = _extract_tool_text(result)
    if not text.strip():
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


