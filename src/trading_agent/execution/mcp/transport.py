"""JSON-RPC 2.0 over HTTP with SSE/streaming response support.

The MCP Streamable HTTP transport accepts ``POST /mcp`` and answers with
either a single JSON document or a Server-Sent Events stream. This client
supports both: if the response body is JSON it is parsed directly; if it
is an SSE stream, the first non-`ping` data event that matches the request
id is the result.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from ...security.loopback import require_official_broker_url
from ..mcp_client import _parse_sse

log = logging.getLogger(__name__)


class RpcError(RuntimeError):
    """A classified JSON-RPC transport error. ``code`` is the JSON-RPC code."""

    def __init__(self, code: int, message: str, *, data: Any = None) -> None:
        super().__init__(f"RPC error {code}: {message}")
        self.code = code
        self.message = message
        self.data = data


class JsonRpcTransport:
    """Minimal MCP Streamable-HTTP client for one endpoint URL.

    The transport owns one httpx client and one ``Mcp-Session-Id`` header
    value for the lifetime of the MCP session.
    """

    def __init__(self, endpoint_url: str, *, http: httpx.Client, timeout: float = 30.0) -> None:
        require_official_broker_url(endpoint_url)
        self._endpoint_url = endpoint_url
        self._http = http
        self._timeout = timeout
        self._session_id: str | None = None
        self._next_id = 0

    @property
    def session_id(self) -> str | None:
        return self._session_id

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Send a JSON-RPC request and return the result dict (raises on error).

        Returns the raw result object; for ``tools/list``-style methods this
        is the result payload (e.g. ``{"tools": [...]}``).
        """
        if method not in {"initialize", "tools/list"}:
            raise RpcError(-32000, "legacy transport tool dispatch is disabled")
        require_official_broker_url(self._endpoint_url)
        self._next_id += 1
        body = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": method,
        }
        if params is not None:
            body["params"] = params
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        response = self._http.post(
            self._endpoint_url,
            content=json.dumps(body),
            headers=headers,
            timeout=self._timeout,
            follow_redirects=False,
        )
        if "Mcp-Session-Id" in response.headers:
            self._session_id = response.headers["Mcp-Session-Id"]
        if response.status_code in (401, 403):
            response.raise_for_status()  # caller classifies auth failures
        if response.status_code == 405:
            raise RpcError(-32000, f"{method} is a notification-only method (HTTP 405)")
        response.raise_for_status()
        return self._decode(response)

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        if method != "notifications/initialized":
            raise RpcError(-32000, "legacy transport notification denied")
        body: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            body["params"] = params
        headers = {"Content-Type": "application/json"}
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        self._http.post(
            self._endpoint_url,
            content=json.dumps(body),
            headers=headers,
            timeout=self._timeout,
            follow_redirects=False,
        )

    # ------------------------------------------------------------- decoding

    def _decode(self, response: httpx.Response) -> dict[str, Any]:
        content_type = response.headers.get("Content-Type", "")
        if "text/event-stream" in content_type:
            result = _parse_sse(response.text, self._next_id)
        else:
            result = json.loads(response.text)
        if (
            not isinstance(result, dict)
            or result.get("jsonrpc") != "2.0"
            or type(result.get("id")) is not int
            or result.get("id") != self._next_id
        ):
            raise RpcError(-32000, "response identity mismatch")
        if "error" in result:
            raise RpcError(-32000, "broker returned a classified RPC error")
        return result.get("result") or {}

    @staticmethod
    def _decode_sse(text: str) -> dict[str, Any]:
        """Parse the first JSON-RPC message from an SSE body."""
        for line in text.splitlines():
            if not line.startswith("data:"):
                continue
            payload = line[len("data:") :].strip()
            if not payload or payload == " ":
                continue
            try:
                message = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if "id" in message and message["id"] is not None:
                return message
        raise RpcError(-32000, "no JSON-RPC message found in SSE stream")

    def close(self) -> None:
        try:
            self._http.close()
        except Exception:  # noqa: BLE001 - best-effort shutdown
            pass
