"""Deterministic live-activation gate (build plan section 17).

Activation requires ALL of: live-enabled flag, a live mode, nonzero approved
capital, the correct account, allowlists, a valid policy, an active strategy,
healthy reconciliation, and an unexpired owner authorization. A single
environment variable is never sufficient.

The gate is deterministic and re-evaluated before every financial mutation.
In M0 it can never authorize: the broker gateway is not connected, no
strategy is active, and no reconciliation state exists. Every unmet
prerequisite is reported explicitly so the owner sees exactly what is
missing, and the resulting authority is always LIVE_NOT_AUTHORIZED in M0.

From M1 on, callers may supply a ``RuntimeStatus`` built from the run's
persisted state; the reconciliation and strategy checks then reflect that
data instead of the fail-closed defaults.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from ..config.models import TradingConfig, is_live_mode
from ..contracts.orders import RuntimeStatus
from ..execution.broker_interface import BrokerAdapter

LIVE_AUTHORITY = "LIVE_AUTHORIZED"
NOT_AUTHORIZED = "LIVE_NOT_AUTHORIZED"


@dataclass(frozen=True)
class ActivationCheck:
    name: str
    satisfied: bool
    detail: str


@dataclass(frozen=True)
class ActivationDecision:
    authority: str
    authorized: bool
    checks: tuple[ActivationCheck, ...]

    @property
    def unmet(self) -> tuple[ActivationCheck, ...]:
        return tuple(check for check in self.checks if not check.satisfied)

    def summary(self) -> str:
        unmet = self.unmet
        if not unmet:
            return f"{self.authority}: all {len(self.checks)} activation checks satisfied"
        names = ", ".join(check.name for check in unmet)
        return f"{self.authority}: {len(unmet)} unmet prerequisite(s): {names}"


def evaluate_live_activation(
    config: TradingConfig,
    broker: BrokerAdapter,
    *,
    now: datetime | None = None,
    runtime: RuntimeStatus | None = None,
) -> ActivationDecision:
    """Evaluate every activation prerequisite; fails closed on any gap.

    ``runtime`` (from M1) carries the persisted runtime prerequisites: the
    last reconciliation status and the active strategy versions, built from
    the run's database state. When it is not supplied, those two checks stay
    unmet with the M0 fail-closed defaults; the gate never guesses at state
    it has not been given.
    """
    timestamp = now if now is not None else datetime.now(UTC)
    capabilities = broker.capabilities()
    live_mode = is_live_mode(config.app.mode)

    authorization = config.live.authorization_expires_at
    authorization_unexpired = authorization is not None and authorization > timestamp

    if runtime is None:
        reconciliation_check = ActivationCheck(
            "reconciliation_healthy",
            False,
            "no ledger or reconciliation service exists yet (M1)",
        )
        strategy_check = ActivationCheck(
            "strategy_active",
            False,
            "no strategy is implemented or activated yet (M1)",
        )
    else:
        reconciliation_check = ActivationCheck(
            "reconciliation_healthy",
            runtime.last_reconciliation_status == "consistent",
            "last reconciliation "
            + (
                f"{runtime.last_reconciliation_status}"
                if runtime.last_reconciliation_status is not None
                else "has no data yet; unmet, never guessed"
            ),
        )
        strategy_check = ActivationCheck(
            "strategy_active",
            bool(runtime.active_strategy_versions),
            "active strategy versions: "
            + (
                ", ".join(runtime.active_strategy_versions)
                if runtime.active_strategy_versions
                else "none"
            ),
        )

    checks = (
        ActivationCheck(
            "live_enabled_flag",
            config.live.enabled,
            "live.enabled is " + ("true" if config.live.enabled else "false"),
        ),
        ActivationCheck(
            "mode_is_live",
            live_mode,
            f"app.mode={config.app.mode.value} "
            + ("(live mode)" if live_mode else "(non-live mode)"),
        ),
        ActivationCheck(
            "approved_capital_nonzero",
            config.live.approved_capital_usd > 0,
            f"live.approved_capital_usd={config.live.approved_capital_usd} USD",
        ),
        ActivationCheck(
            "owner_authorization_recorded",
            config.live.owner_authorization_ref is not None,
            "owner authorization ref "
            + (
                f"present ({config.live.owner_authorization_ref})"
                if config.live.owner_authorization_ref
                else "missing; a recorded, scoped authorization is required"
            ),
        ),
        ActivationCheck(
            "authorization_unexpired",
            authorization_unexpired,
            "authorization expiry "
            + (
                f"{authorization.isoformat()}"
                if authorization is not None
                else "missing; an authorization without an expiry cannot activate"
            )
            + (" (expired)" if authorization is not None and not authorization_unexpired else ""),
        ),
        ActivationCheck(
            "account_alias_bound",
            config.broker.approved_account_id is not None,
            "approved account alias "
            + (
                f"bound ({config.broker.approved_account_id})"
                if config.broker.approved_account_id
                else "missing; the dedicated account is bound by the owner"
            ),
        ),
        ActivationCheck(
            "instrument_allowlist_configured",
            bool(config.universe.live_instrument_allowlist),
            f"{len(config.universe.live_instrument_allowlist)} live instruments allowlisted",
        ),
        ActivationCheck(
            "broker_provider_live",
            config.broker.provider == "robinhood",
            f"broker.provider={config.broker.provider} "
            + (
                "(official gateway)"
                if config.broker.provider == "robinhood"
                else "(not the official gateway)"
            ),
        ),
        ActivationCheck(
            "broker_connected",
            capabilities.connected,
            "gateway "
            + (
                "connected"
                if capabilities.connected
                else "not connected (no authenticated MCP session; M4)"
            ),
        ),
        ActivationCheck(
            "broker_capabilities_verified",
            capabilities.execution_enabled
            and capabilities.verified_capability_digest is not None
            and capabilities.verified_capability_digest
            == config.broker.allowlisted_tool_schema_digest,
            "tool-schema digest "
            + (
                "verified against allowlisted digest"
                if capabilities.verified_capability_digest is not None
                else "unverified; authenticated capability discovery is required (M4)"
            ),
        ),
        reconciliation_check,
        strategy_check,
    )

    authorized = all(check.satisfied for check in checks)
    return ActivationDecision(
        authority=LIVE_AUTHORITY if authorized else NOT_AUTHORIZED,
        authorized=authorized,
        checks=checks,
    )
