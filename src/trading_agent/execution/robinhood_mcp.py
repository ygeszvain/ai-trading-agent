"""Official Robinhood external-agent MCP gateway (build plan section 14).

M0 status: EXPLICITLY UNAVAILABLE. This module deliberately contains no MCP
client, no transport, and no credential handling. The real gateway (owner-run
authorization, capability discovery, tool allowlist, shadow reads) is the M4
deliverable (Prompt 7). Every call fails closed with ``BrokerUnavailable``
so that no code path — including a misconfigured live profile — can reach a
broker through this adapter.

Official endpoint (plan source [S1]): https://agent.robinhood.com/mcp/trading
"""

from __future__ import annotations

from ..contracts.broker import (
    AccountSnapshot,
    BrokerCapabilities,
    BrokerUnavailable,
    OrderRequest,
    OrderResult,
)
from .broker_interface import BrokerAdapter

OFFICIAL_MCP_URL = "https://agent.robinhood.com/mcp/trading"

_REASON = (
    "the Robinhood MCP gateway has no implementation in M0: no authenticated "
    "session, no capability discovery, and no client transport exist yet. "
    "Owner-run authorization and the official gateway arrive in M4 (Prompt 7). "
    "Current financial authority: LIVE_NOT_AUTHORIZED."
)


class RobinhoodMcpBrokerAdapter(BrokerAdapter):
    """Placeholder for the official Robinhood gateway. Never executes."""

    provider = "robinhood"

    def __init__(
        self,
        mcp_url: str = OFFICIAL_MCP_URL,
        approved_account_id: str | None = None,
        allowlisted_tool_schema_digest: str | None = None,
    ) -> None:
        self._mcp_url = mcp_url
        self._approved_account_id = approved_account_id
        self._allowlisted_tool_schema_digest = allowlisted_tool_schema_digest

    def capabilities(self) -> BrokerCapabilities:
        return BrokerCapabilities(
            provider=self.provider,
            connected=False,
            reads_enabled=False,
            execution_enabled=False,
            verified_capability_digest=None,
            notes=(
                f"no authenticated MCP session (endpoint {self._mcp_url})",
                "tool schemas unverified; unknown tools remain denied (plan section 14)",
                "M4 (Prompt 7) implements discovery, allowlist, and shadow reads",
            ),
        )

    def account_snapshot(self) -> AccountSnapshot:
        raise BrokerUnavailable(_REASON)

    def submit_order(self, request: OrderRequest) -> OrderResult:
        raise BrokerUnavailable(
            f"execution REJECTED before any transport: {_REASON} "
            f"(requested {request.side} {request.instrument}; nothing was sent)"
        )

    def cancel_order(self, broker_order_id: str) -> OrderResult:
        raise BrokerUnavailable(
            f"cancellation REJECTED before any transport: {_REASON} "
            f"(order {broker_order_id!r}; nothing was sent)"
        )
