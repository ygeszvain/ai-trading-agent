"""Minimal, dependency-free MCP (Model Context Protocol) client.

Build plan sections 6/14: the only official way to reach Robinhood is
``https://agent.robinhood.com/mcp/trading`` — an OAuth-protected JSON-RPC
over HTTP (Streamable HTTP transport). This package implements exactly the
subset the trading agent needs:

  * ``credentials.CredentialStore`` — encrypted-at-rest OAuth token vault
    with digest auditing (never logs full tokens).
  * ``transport.JsonRpcTransport`` — JSON-RPC 2.0 over httpx: request
    posting, single SSE stream and plain-JSON response framing.
  * ``client.McpOAuthClient`` — metadata discovery (RFC 8414 / 9728),
    dynamic client registration (RFC 7591), authorization-code + PKCE,
    single-flight token refresh, session lifecycle, classified errors.

Hard boundaries: no execution tools are ever exposed through this client
without an explicit capability-verification + digest-allowlist pass
(see ``trading_agent.execution.capability``), and every tool call is
audited (``trading_agent.execution.audit``).
"""

from .client import (
    McpOAuthClient,
    McpSessionError,
    McpStateError,
    OAuthMetadata,
    TokenRefreshRequired,
)
from .credentials import CredentialStore, TokenRecord, TokenStoreError
from .transport import JsonRpcTransport, RpcError

__all__ = [
    "CredentialStore",
    "JsonRpcTransport",
    "McpOAuthClient",
    "McpSessionError",
    "McpStateError",
    "OAuthMetadata",
    "RpcError",
    "TokenRecord",
    "TokenRefreshRequired",
    "TokenStoreError",
]
