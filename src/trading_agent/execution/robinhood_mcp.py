"""Robinhood official MCP broker adapter (M4 — shadow mode).

Real gateway access is quarantined pending verified account-scoped integration.
An explicitly injected mocked HTTP client can exercise the shadow read contracts.
Normal construction does not load a credential or connect to the broker.

Security invariants, enforced in code (not documentation):
  * **No execution, ever, in this build.** ``submit_order`` and
    ``cancel_order`` refuse every request: the 1,000 USD live pilot
    boundary requires a separately owner-approved live build with the
    section 17 gate. The refusal is audited as a gateway event.
  * **Capability verification is a hard gate.** The discovered tool set
    is digested and must match the owner-allowlisted digest in the
    configuration before any read proceeds. A mismatch stops the cycle.
  * **Account identity verification.** When the owner has configured
    their account number, the account returned by the broker must match
    it before any position data is accepted. A mismatch is treated as a
    failed cycle; data is never displayed from a mismatched account.
  * **No secrets at rest or in transit to the UI.** The token lives only
    in the 0600 store file; the account number is persisted masked;
    snapshots carry sanitized positions only (plan section 14).
  * **Fail-closed everywhere.** Missing token, mismatched capability,
    unreachable endpoint, or unreadable data all yield
    ``available=False`` snapshots with a classified reason. Nothing is
    ever invented.
"""

from __future__ import annotations

import secrets
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from httpx import Client as HttpxClient
from sqlalchemy.orm import Session

from ..config import TradingConfig
from ..contracts.broker import (
    AccountSnapshot,
    BrokerCapabilities,
    BrokerError,
    BrokerStateNotAvailable,
    BrokerUnavailable,
    NormalizedOrderStatus,
    OpenOrderView,
    OrderRequest,
    OrderResult,
    PositionView,
)
from ..db.schema import broker_gateway_events, broker_snapshots
from .broker_interface import BrokerAdapter
from .capability import CapabilityReport, ToolAllowlist, ToolSchema, verify_capability
from .credentials import TokenStore
from .mcp_client import McpClient, parse_tool_payload

EXECUTION_DISABLED_REASON = (
    "broker execution is permanently disabled in this build (shadow-mode only); "
    "the 1,000 USD live pilot boundary requires a separately approved live build"
)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(16)}"


def _to_decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
        return parsed if parsed.is_finite() else None
    except InvalidOperation:
        return None


def _string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _mask_account_number(number: str | None) -> str | None:
    """Display-safe account identity: only the last four characters."""
    if not number:
        return None
    number = str(number).strip()
    if len(number) <= 4:
        return "\u2022" * len(number)
    return "\u2022" * max(1, len(number) - 4) + number[-4:]


class RobinhoodMcpBrokerAdapter(BrokerAdapter):
    """Shadow-mode gateway to the Robinhood official MCP endpoint."""

    provider = "robinhood"

    def __init__(
        self,
        config: TradingConfig | None = None,
        *,
        session: Session | None = None,
        http: HttpxClient | None = None,
    ) -> None:
        self._config = config
        self._session = session
        self._broker_cfg = config.broker if config is not None else None
        self._token_store: TokenStore | None
        if self._broker_cfg is not None and self._broker_cfg.shadow_enabled and http is not None:
            self._token_store = TokenStore(self._broker_cfg.token_store_path)
            self._token = self._token_store.load()
            self._allowlist = ToolAllowlist.from_file(self._broker_cfg.capability_allowlist_path)
        else:
            self._token_store = None
            self._token = None
            self._allowlist = None
        self._http = http
        self._client: McpClient | None = None
        self._capability: CapabilityReport | None = None
        self._last_snapshot: AccountSnapshot | None = None
        self._last_cycle_at: str | None = None
        if self._broker_cfg is not None:
            self._account_number = (self._broker_cfg.account_number or "").strip() or None
            self._alias = self._broker_cfg.approved_account_id or "unbound"
        else:
            self._account_number = None
            self._alias = "unbound"

    # ------------------------------------------------------------ lifecycle

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> RobinhoodMcpBrokerAdapter:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # --------------------------------------------------------- capabilities

    def capabilities(self) -> BrokerCapabilities:
        """Honest capability report derived from the last verified cycle.

        A freshly constructed adapter (no cycle yet) reports disconnected:
        the activation gate stays fail-closed until a real verification
        pass has occurred.
        """
        shadow_on = self._broker_cfg.shadow_enabled if self._broker_cfg is not None else False
        notes: list[str] = []
        if self._broker_cfg is None:
            notes.append("broker not configured - run 'trading-agent broker setup'")
        if self._token is None:
            notes.append("no MCP token stored - run 'trading-agent broker setup'")
        if not shadow_on:
            notes.append("shadow mode disabled in configuration")
        verified = bool(self._capability is not None and self._capability.verified)
        connected = self._token is not None and verified
        return BrokerCapabilities(
            provider=self.provider,
            connected=connected,
            reads_enabled=connected and shadow_on,
            execution_enabled=False,
            verified_capability_digest=(
                self._capability.digest if self._capability and verified else None
            ),
            notes=tuple(notes),
        )

    # -------------------------------------------------------------- cycle

    def account_snapshot(self, *, now: datetime | None = None) -> AccountSnapshot:
        """One shadow cycle: connect, verify, identity-check, read, persist.

        Never raises for broker-side conditions: every failure path returns
        an ``available=False`` snapshot with a classified reason, and each
        path is audited via ``broker_gateway_events``.
        """
        as_of = now or datetime.now(UTC)
        if self._broker_cfg is None or not self._broker_cfg.shadow_enabled:
            self._log_event(
                "shadow_unconfigured",
                "LIVE_NOT_AUTHORIZED: shadow mode not enabled in configuration",
            )
            raise BrokerUnavailable("LIVE_NOT_AUTHORIZED")
        if self._http is None:
            return self._fail(
                as_of,
                "real_gateway_disabled",
                "account-scoped real gateway integration is not validated",
            )
        if self._token is None:
            self._log_event(
                "token_missing",
                "LIVE_NOT_AUTHORIZED: no MCP token stored; run 'trading-agent broker setup'",
            )
            raise BrokerUnavailable(
                "LIVE_NOT_AUTHORIZED: no MCP token stored; run 'trading-agent broker setup'"
            )

        if not self._account_number or self._alias == "unbound":
            return self._fail(
                as_of, "account_unverified", "exact account binding required before reads"
            )
        capability = None
        try:
            client = self._open_client()
        except BrokerError as error:
            self._log_event("session_failed", str(error))
            return self._fail(as_of, "session_failed", str(error))
        except Exception as error:  # noqa: BLE001 - audit everything
            self._log_event("session_failed", f"unexpected: {type(error).__name__}")
            return self._fail(as_of, "session_failed", "unexpected client error")

        try:
            schemas = self._list_schemas(client)
        except BrokerError as error:
            self._log_event("discovery_failed", str(error))
            return self._fail(as_of, "discovery_failed", str(error))

        capability = verify_capability(
            schemas,
            allowlisted_digest=self._broker_cfg.allowlisted_tool_schema_digest,
        )
        self._capability = capability
        self._log_event(
            "capability_verified" if capability.verified else "capability_mismatch",
            capability.mismatch_detail or f"digest={(capability.digest or 'UNKNOWN')[:16]}",
            {"tool_count": len(capability.tools), "digest": capability.digest},
        )
        if not capability.verified:
            return self._fail(
                as_of,
                "capability_mismatch",
                capability.mismatch_detail or "capability digest mismatch",
                capability_digest=capability.digest,
            )

        # Account identity verification (hard gate when configured).
        account_payload, account_error = self._read_tool(client, "account", "account_read")
        if account_error is not None:
            self._log_event("account_read_failed", account_error)
            return self._fail(
                as_of,
                "account_read_failed",
                account_error,
                capability_digest=capability.digest,
            )
        if self._account_number:
            returned = self._extract_account_number(account_payload)
            if returned is None:
                self._log_event(
                    "account_read_failed",
                    "broker account payload did not include an account number; "
                    "cannot verify identity (fail-closed)",
                )
                return self._fail(
                    as_of,
                    "account_unverified",
                    "could not read account number to verify identity",
                    capability_digest=capability.digest,
                )
            if returned != self._account_number:
                self._log_event(
                    "account_mismatch",
                    f"broker returned a different account than the configured "
                    f"{_mask_account_number(self._account_number)}",
                )
                return self._fail(
                    as_of,
                    "account_mismatch",
                    "broker account does not match the configured account; "
                    "no data will be displayed",
                    capability_digest=capability.digest,
                )
            self._log_event("account_verified", "account number matches configuration")

        # Shadow reads (positions, open orders). Each is best-effort: a failed
        # or unmapped read degrades that field, never the whole snapshot.
        cash = self._extract_cash(account_payload)
        positions_payload, positions_error = self._read_tool(client, "positions", "positions_read")
        open_orders_payload, open_orders_error = self._read_tool(
            client, "open_orders", "open_orders_read"
        )
        positions = self._extract_positions(positions_payload) if positions_error is None else None
        open_orders = (
            self._extract_open_orders(open_orders_payload) if open_orders_error is None else None
        )

        degraded: list[str] = []
        if positions_error is not None:
            degraded.append(f"positions: {positions_error}")
        if open_orders_error is not None:
            degraded.append(f"open_orders: {open_orders_error}")
        if cash is None and positions is None and open_orders is None:
            return self._fail(
                as_of,
                "read_failed",
                "all shadow reads returned no data",
                capability_digest=capability.digest,
            )

        if degraded:
            self._log_event("read_degraded", "; ".join(degraded))

        snapshot = AccountSnapshot(
            available=True,
            reason="ok" if not degraded else f"partial ({'; '.join(degraded)})",
            as_of=as_of,
            cash=cash,
            positions=() if positions is None else positions,
            open_orders=() if open_orders is None else open_orders,
        )
        self._persist_snapshot(
            snapshot, capability.digest, as_of, status="ok" if not degraded else "partial"
        )
        return snapshot

    # ------------------------------------------------------- no execution

    def submit_order(self, request: OrderRequest) -> OrderResult:
        """Permanently refused in this build. Audited, never transmitted."""
        if self._broker_cfg is None or not self._broker_cfg.shadow_enabled:
            self._log_event(
                "execution_refused",
                "LIVE_NOT_AUTHORIZED: submit_order before shadow configuration",
            )
            raise BrokerUnavailable("LIVE_NOT_AUTHORIZED")
        self._log_event(
            "execution_refused",
            "submit_order invoked; refused by build policy",
            {"client_order_id": request.client_order_id, "instrument_id": request.instrument},
        )
        return self._refusal()

    def cancel_order(self, broker_order_id: str) -> OrderResult:
        if self._broker_cfg is None or not self._broker_cfg.shadow_enabled:
            self._log_event(
                "execution_refused",
                "LIVE_NOT_AUTHORIZED: cancel_order before shadow configuration",
            )
            raise BrokerUnavailable("LIVE_NOT_AUTHORIZED")
        self._log_event(
            "execution_refused",
            "cancel_order invoked; refused by build policy",
            {"broker_order_id": broker_order_id},
        )
        return self._refusal()

    def _refusal(self) -> OrderResult:
        return OrderResult(
            accepted=False,
            status=NormalizedOrderStatus.REJECTED,
            broker_order_id=None,
            rejection_reason=EXECUTION_DISABLED_REASON,
        )

    # ------------------------------------------------------------- client

    def _open_client(self) -> McpClient:
        if self._broker_cfg is None:
            raise BrokerUnavailable("broker configuration unavailable")
        if self._allowlist is None:
            self._log_event(
                "session_failed",
                "capability allowlist missing; fail-closed, no transport opened",
            )
            raise BrokerUnavailable("allowlist_missing: run 'trading-agent broker setup'")
        client = McpClient(
            self._broker_cfg.robinhood_mcp_url,
            token=self._token or "",
            timeout_seconds=self._broker_cfg.request_timeout_seconds,
            http=self._http,
        )
        client.initialize()
        self._client = client
        self._log_event("session_open", "MCP session established")
        return client

    def _list_schemas(self, client: McpClient) -> list[ToolSchema]:
        raw = client.list_tools()
        schemas = [ToolSchema.from_api(tool) for tool in raw if tool.get("name")]
        if not schemas:
            raise BrokerStateNotAvailable("broker listed zero tools")
        self._log_event(
            "tools_listed",
            f"{len(schemas)} tools",
            {"tools": sorted(s.name for s in schemas)},
        )
        return schemas

    def _read_tool(
        self, client: McpClient, role: str, event_prefix: str
    ) -> tuple[object, str | None]:
        """Call the mapped tool for a role. Returns (payload, error|None)."""
        if self._allowlist is None:
            raise BrokerUnavailable("verified tool allowlist unavailable")
        tool_name = self._allowlist.tool_name(role)
        if tool_name is None:
            self._log_event(
                f"{event_prefix}_skipped",
                f"role '{role}' has no tool name in the allowlist",
            )
            return None, None  # unmapped: degrades silently, noted in reason
        permitted = self._allowlist.read_tool_names()
        try:
            result = client.call_tool(tool_name, {}, permitted=permitted)
        except BrokerError as error:
            self._log_event(f"{event_prefix}_failed", str(error))
            return None, str(error)
        payload = parse_tool_payload(result)
        if payload is None:
            self._log_event(
                f"{event_prefix}_unparsed",
                f"tool '{tool_name}' returned non-JSON text; treated as no data",
            )
            return None, None
        return payload, None

    # ------------------------------------------------------ field extract

    @staticmethod
    def _extract_cash(payload: object) -> Decimal | None:
        if not isinstance(payload, dict):
            return None
        for key in ("cash", "cash_usd", "cashBalance", "cash_value"):
            value = _to_decimal(payload.get(key))
            if value is not None:
                return value
        balances = payload.get("balances") or payload.get("bal")
        if isinstance(balances, dict):
            return _to_decimal(balances.get("cashBalance"))
        return None

    @staticmethod
    def _extract_account_number(payload: object) -> str | None:
        if not isinstance(payload, dict):
            return None
        candidates = [payload.get("accountNumber"), payload.get("account_number")]
        user = payload.get("user")
        if isinstance(user, dict):
            candidates.extend([user.get("accountNumber"), user.get("account_number")])
        for candidate in candidates:
            if candidate is not None and str(candidate).strip():
                return str(candidate).strip()
        return None

    @staticmethod
    def _extract_positions(payload: object) -> tuple[PositionView, ...]:
        if not isinstance(payload, dict):
            return ()
        rows = payload.get("positions") or payload.get("data") or []
        if isinstance(rows, dict):
            rows = rows.get("positions") or []
        if not isinstance(rows, list):
            return ()
        views: list[PositionView] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            symbol = _string(row.get("symbol"))
            if symbol is None:
                continue
            views.append(
                PositionView(
                    instrument_id=f"RH:{symbol.upper()}",
                    quantity=_to_decimal(row.get("quantity")) or Decimal("0"),
                    avg_price=_to_decimal(row.get("avgPrice") or row.get("avg_price")),
                    market_value=_to_decimal(row.get("marketValue") or row.get("market_value")),
                )
            )
        return tuple(views)

    @staticmethod
    def _extract_open_orders(payload: object) -> tuple[OpenOrderView, ...]:
        if not isinstance(payload, dict):
            return ()
        rows = payload.get("openOrders") or payload.get("open_orders") or payload.get("data") or []
        if isinstance(rows, dict):
            rows = rows.get("openOrders") or rows.get("open_orders") or []
        if not isinstance(rows, list):
            return ()
        views: list[OpenOrderView] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            symbol = _string(row.get("symbol"))
            if symbol is None:
                continue
            views.append(
                OpenOrderView(
                    broker_order_id=_string(row.get("id")) or _string(row.get("order_id")) or "",
                    instrument_id=f"RH:{symbol.upper()}",
                    side=str(row.get("side") or "unknown").upper(),
                    quantity=_to_decimal(row.get("quantity")) or Decimal("0"),
                    limit_price=_to_decimal(row.get("limitPrice") or row.get("limit_price")),
                    status=str(row.get("status") or "open").lower(),
                )
            )
        return tuple(views)

    # ---------------------------------------------------------- persistence

    def _fail(
        self,
        as_of: datetime,
        status: str,
        reason: str,
        *,
        capability_digest: str | None = None,
    ) -> AccountSnapshot:
        self._log_event(
            "cycle_failed",
            f"{status}: {reason}",
            {"status": status, "reason": reason},
        )
        snapshot = AccountSnapshot(
            available=False,
            reason=f"{status}: {reason}",
            as_of=as_of,
        )
        self._persist_snapshot(
            snapshot,
            capability_digest or (self._capability.digest if self._capability else None),
            as_of,
            status=status,
        )
        return snapshot

    def _persist_snapshot(
        self,
        snapshot: AccountSnapshot,
        capability_digest: str | None,
        as_of: datetime,
        *,
        status: str,
    ) -> None:
        if self._session is None:
            return
        self._session.execute(
            broker_snapshots.insert().values(
                snapshot_id=_new_id("bsnap"),
                provider=self.provider,
                account_alias=self._alias,
                account_number_masked=_mask_account_number(self._account_number),
                session_date=as_of.date() if as_of else date.today(),
                cash_usd=snapshot.cash,
                positions_json=[
                    {
                        "instrument_id": p.instrument_id,
                        "quantity": str(p.quantity),
                        "avg_price": str(p.avg_price) if p.avg_price is not None else None,
                        "market_value": str(p.market_value) if p.market_value is not None else None,
                    }
                    for p in snapshot.positions
                ],
                open_orders_json=[
                    {
                        "broker_order_id": o.broker_order_id,
                        "instrument_id": o.instrument_id,
                        "side": o.side,
                        "quantity": str(o.quantity),
                        "limit_price": str(o.limit_price) if o.limit_price is not None else None,
                        "status": o.status,
                    }
                    for o in snapshot.open_orders
                ],
                capability_digest=capability_digest,
                status=status,
                detail=snapshot.reason,
                fetched_at=as_of,
            )
        )
        self._last_snapshot = snapshot
        self._last_cycle_at = as_of.isoformat()

    def _log_event(
        self, event_type: str, detail: str | None = None, payload: dict[str, object] | None = None
    ) -> None:
        self._log_event_impl(event_type, detail, payload)

    def log_cycle_error(self, detail: str) -> None:
        """Audit hook used by the shadow loop for unexpected exceptions."""
        self._log_event("cycle_error", detail)

    def _log_event_impl(
        self, event_type: str, detail: str | None, payload: dict[str, object] | None
    ) -> None:
        if self._session is None:
            return
        self._session.execute(
            broker_gateway_events.insert().values(
                event_id=_new_id("bgevt"),
                provider=self.provider,
                ts=datetime.now(UTC),
                event_type=event_type,
                detail=detail,
                payload_json=payload,
            )
        )
