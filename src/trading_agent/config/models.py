"""Typed configuration models (build plan section 22 configuration contract).

Design rules:
- Every financial value is a Decimal parsed from a quoted string/int.
- Unknown top-level sections are rejected (strict, versioned contract).
- Live trading is fail-closed: a live configuration must supply every
  required value or startup fails with a clear, actionable error.
- v1-scope switches (cloud fallback, paid subscriptions, deferred asset
  classes, emergency liquidation, live auto-promotion) must remain off;
  turning any of them on is a configuration error, not a warning.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationInfo,
    field_validator,
    model_validator,
)

from ..money import parse_fraction, parse_money

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
SYNTHETIC_PREFIX = "TEST_"


class TradingMode(StrEnum):
    SIMULATION = "simulation"
    PAPER = "paper"
    SHADOW = "shadow"
    SUPERVISED_LIVE = "supervised_live"
    BOUNDED_AUTONOMOUS_LIVE = "bounded_autonomous_live"
    PAUSED = "paused"
    RECONCILIATION_REQUIRED = "reconciliation_required"


def is_live_mode(mode: TradingMode) -> bool:
    return mode in (TradingMode.SUPERVISED_LIVE, TradingMode.BOUNDED_AUTONOMOUS_LIVE)


def _decimal(value: Any, *, field: str, allow_negative: bool = False) -> Decimal:
    try:
        return parse_money(value, field=field, allow_negative=allow_negative)
    except ValueError as exc:
        raise ValueError(str(exc)) from None


def _fraction(value: Any, *, field: str) -> Decimal:
    try:
        return parse_fraction(value, field=field)
    except ValueError as exc:
        raise ValueError(str(exc)) from None


def _is_loopback_url(url: str) -> bool:
    lowered = url.strip().lower()
    for prefix in (
        "http://127.0.0.1",
        "https://127.0.0.1",
        "http://localhost",
        "https://localhost",
        "http://[::1]",
        "https://[::1]",
        "http://::1",
        "https://::1",
    ):
        if lowered.startswith(prefix):
            return True
    return False


class AppSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment: Literal["development", "staging", "production"] = "development"
    mode: TradingMode = TradingMode.SIMULATION
    display_timezone: str = "America/Chicago"
    exchange_timezone: str = "America/New_York"
    web_host: str = "127.0.0.1"
    web_port: int = Field(default=8000, ge=1024, le=65535)

    @field_validator("web_host")
    @classmethod
    def _validate_web_host(cls, value: str) -> str:
        if value.strip().lower() not in LOOPBACK_HOSTS:
            raise ValueError(
                f"app.web_host: {value!r} is not loopback; the website must bind to "
                "127.0.0.1/localhost (plan section 18)"
            )
        return value.strip()

    @field_validator("display_timezone", "exchange_timezone")
    @classmethod
    def _validate_timezone(cls, value: str) -> str:
        if not value or "/" not in value:
            raise ValueError(
                f"timezone {value!r} is not an IANA zone name (expected e.g. America/Chicago)"
            )
        return value


class LLMSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["lmstudio"] = "lmstudio"
    base_url: str = "http://127.0.0.1:1234/v1"
    model_id: str | None = None
    auth_token: SecretStr | None = None
    auth_token_secret_ref: str | None = None
    allow_cloud_fallback: bool = False
    max_calls_per_research_job: int = Field(default=4, ge=1)
    max_documents_per_job: int = Field(default=12, ge=1)
    job_timeout_seconds: int = Field(default=120, ge=1)

    @field_validator("base_url")
    @classmethod
    def _validate_base_url(cls, value: str) -> str:
        if not _is_loopback_url(value):
            raise ValueError(
                f"llm.base_url: {value!r} is not a loopback address; accidental cloud "
                "inference endpoints are rejected (plan section 9)"
            )
        return value

    @field_validator("allow_cloud_fallback")
    @classmethod
    def _validate_cloud_fallback(cls, value: bool) -> bool:
        if value:
            raise ValueError(
                "llm.allow_cloud_fallback: must be false in v1; cloud fallback is "
                "fail-closed (plan sections 9/22)"
            )
        return value

    def sanitized_summary(self) -> dict[str, Any]:
        """Serialization-safe summary; the token is never included."""
        return {
            "provider": self.provider,
            "base_url": self.base_url,
            "model_id": self.model_id,
            "auth_token_configured": self.auth_token is not None,
            "auth_token_secret_ref": self.auth_token_secret_ref,
            "allow_cloud_fallback": self.allow_cloud_fallback,
            "max_calls_per_research_job": self.max_calls_per_research_job,
            "max_documents_per_job": self.max_documents_per_job,
            "job_timeout_seconds": self.job_timeout_seconds,
        }


class BrokerSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["simulator", "robinhood"] = "simulator"
    robinhood_mcp_url: str = "https://agent.robinhood.com/mcp/trading"
    approved_account_id: str | None = None
    allowlisted_tool_schema_digest: str | None = None


class LiveSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    approved_capital_usd: Decimal = Decimal("0")
    owner_authorization_ref: str | None = None
    authorization_expires_at: datetime | None = None
    require_application_approval_per_intent: bool = True
    resume_after_restart: bool = False

    @field_validator("approved_capital_usd", mode="before")
    @classmethod
    def _validate_capital(cls, value: Any) -> Decimal:
        return _decimal(value, field="live.approved_capital_usd")

    @field_validator("authorization_expires_at", mode="before")
    @classmethod
    def _validate_expiry(cls, value: Any) -> datetime | None:
        if value in (None, ""):
            return None
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError(
                    f"live.authorization_expires_at: {value!r} is not an ISO-8601 timestamp"
                ) from exc
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=UTC)
            return value
        raise ValueError("live.authorization_expires_at: expected an ISO-8601 timestamp string")


class PaperSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    initial_cash_usd: Decimal = Decimal("100000")
    synthetic_fixture_universe: list[str] = ["TEST_A", "TEST_B"]

    @field_validator("initial_cash_usd", mode="before")
    @classmethod
    def _validate_cash(cls, value: Any) -> Decimal:
        return _decimal(value, field="paper.initial_cash_usd")

    @field_validator("synthetic_fixture_universe")
    @classmethod
    def _validate_universe(cls, value: list[str]) -> list[str]:
        cleaned = [symbol.strip() for symbol in value if symbol.strip()]
        if not cleaned:
            raise ValueError("paper.synthetic_fixture_universe: must not be empty")
        return cleaned


class UniverseSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    live_instrument_allowlist: list[str] = []
    allow_short_sales: bool = False
    allow_margin_borrowing: bool = False
    allow_options: bool = False
    allow_crypto: bool = False
    allow_leveraged_or_inverse_funds: bool = False
    allow_extended_hours: bool = False
    allow_fractional_orders: bool = False

    @field_validator("live_instrument_allowlist")
    @classmethod
    def _validate_allowlist(cls, value: list[str]) -> list[str]:
        cleaned = [symbol.strip() for symbol in value if symbol.strip()]
        synthetic = [symbol for symbol in cleaned if symbol.startswith(SYNTHETIC_PREFIX)]
        if synthetic:
            raise ValueError(
                f"universe.live_instrument_allowlist: {', '.join(synthetic)} are synthetic "
                f"{SYNTHETIC_PREFIX}* fixture identifiers and must never resolve to live "
                "instruments (plan section 22)"
            )
        return cleaned

    @model_validator(mode="after")
    def _validate_v1_scope(self) -> UniverseSettings:
        deferred = {
            "allow_short_sales": "short selling (deferred scope, plan section 3)",
            "allow_margin_borrowing": "margin borrowing (deferred scope, plan section 3)",
            "allow_options": "options (deferred scope, plan section 3)",
            "allow_crypto": "crypto (deferred scope, plan section 3)",
            "allow_leveraged_or_inverse_funds": "leveraged/inverse funds (plan section 3)",
            "allow_extended_hours": "extended-hours orders (deferred scope, plan section 3)",
            "allow_fractional_orders": "fractional orders (unverified for v1, plan sections 3/24)",
        }
        for flag, reason in deferred.items():
            if getattr(self, flag):
                raise ValueError(f"universe.{flag}: true is not permitted in v1 ({reason})")
        return self


class RiskSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_version: str = "paper-policy-v1"
    max_position_nav_fraction: Decimal = Decimal("0.05")
    max_gross_nav_fraction: Decimal = Decimal("0.25")
    max_positions: int = Field(default=5, ge=1)
    max_order_nav_fraction: Decimal = Decimal("0.02")
    max_pending_entry_nav_fraction: Decimal = Decimal("0.05")
    min_cash_nav_fraction: Decimal = Decimal("0.75")
    max_planned_daily_turnover_nav_fraction: Decimal = Decimal("0.10")
    daily_loss_pause_nav_fraction: Decimal = Decimal("0.01")
    trailing_drawdown_pause_fraction: Decimal = Decimal("0.05")
    max_entry_spread_bps: Decimal = Decimal("15")
    max_quote_age_seconds: int = Field(default=5, ge=1)
    max_account_state_age_seconds: int = Field(default=10, ge=1)
    max_clock_offset_seconds: int = Field(default=1, ge=1)
    max_participation_fraction: Decimal = Decimal("0.001")
    max_entry_orders_per_session: int = Field(default=10, ge=1)
    entry_cancel_request_after_seconds: int = Field(default=60, ge=1)
    default_order_type: Literal["limit", "market"] = "limit"
    default_time_in_force: Literal["day", "gtc", "ioc", "fok"] = "day"
    emergency_liquidation_enabled: bool = False

    @field_validator(
        "max_position_nav_fraction",
        "max_gross_nav_fraction",
        "max_order_nav_fraction",
        "max_pending_entry_nav_fraction",
        "min_cash_nav_fraction",
        "max_planned_daily_turnover_nav_fraction",
        "daily_loss_pause_nav_fraction",
        "trailing_drawdown_pause_fraction",
        "max_participation_fraction",
        mode="before",
    )
    @classmethod
    def _validate_fractions(cls, value: Any, info: ValidationInfo) -> Decimal:
        return _fraction(value, field=f"risk.{info.field_name}")

    @field_validator("max_entry_spread_bps", mode="before")
    @classmethod
    def _validate_spread(cls, value: Any) -> Decimal:
        return _decimal(value, field="risk.max_entry_spread_bps", allow_negative=False)

    @model_validator(mode="after")
    def _validate_relationships(self) -> RiskSettings:
        checks = [
            (
                self.max_order_nav_fraction <= self.max_position_nav_fraction,
                "risk.max_order_nav_fraction must not exceed risk.max_position_nav_fraction "
                "(a single order cannot be larger than the position it builds)",
            ),
            (
                self.max_pending_entry_nav_fraction <= self.max_gross_nav_fraction,
                "risk.max_pending_entry_nav_fraction must not exceed risk.max_gross_nav_fraction",
            ),
            (
                self.max_gross_nav_fraction + self.min_cash_nav_fraction <= Decimal(1),
                "risk.max_gross_nav_fraction + risk.min_cash_nav_fraction must not exceed 1.0 "
                "(gross exposure plus minimum cash cannot require more than the sleeve NAV)",
            ),
            (
                self.emergency_liquidation_enabled is False,
                "risk.emergency_liquidation_enabled: must be false until the emergency "
                "policy is separately approved and tested (plan section 13)",
            ),
        ]
        for ok, message in checks:
            if not ok:
                raise ValueError(message)
        return self


class LearningSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    live_auto_promotion_enabled: bool = False
    max_challenger_trials_per_week: int = Field(default=20, ge=0)
    allowed_live_change_classes: list[str] = []
    require_matured_labels: bool = True

    @model_validator(mode="after")
    def _validate_authority(self) -> LearningSettings:
        if self.live_auto_promotion_enabled:
            raise ValueError(
                "learning.live_auto_promotion_enabled: must be false in v1; every live "
                "promotion requires owner approval (plan section 12)"
            )
        if self.allowed_live_change_classes:
            raise ValueError(
                "learning.allowed_live_change_classes: must be empty in v1; no live change "
                "class is approved (plan section 12)"
            )
        return self


class CostSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paid_data_budget_usd_per_month: Decimal = Decimal("0")
    allow_paid_subscriptions: bool = False
    operating_cost_reporting_enabled: bool = True

    @field_validator("paid_data_budget_usd_per_month", mode="before")
    @classmethod
    def _validate_budget(cls, value: Any) -> Decimal:
        return _decimal(value, field="costs.paid_data_budget_usd_per_month")

    @model_validator(mode="after")
    def _validate_consistency(self) -> CostSettings:
        if self.allow_paid_subscriptions and self.paid_data_budget_usd_per_month <= 0:
            raise ValueError(
                "costs.allow_paid_subscriptions: true requires a positive "
                "costs.paid_data_budget_usd_per_month; the paid budget is USD 0 until "
                "the owner approves a provider and spending cap (plan section 8)"
            )
        return self


class TradingConfig(BaseModel):
    """Root configuration. Unknown sections are rejected (versioned contract)."""

    model_config = ConfigDict(extra="forbid")

    app: AppSettings = AppSettings()
    llm: LLMSettings = LLMSettings()
    broker: BrokerSettings = BrokerSettings()
    live: LiveSettings = LiveSettings()
    paper: PaperSettings = PaperSettings()
    universe: UniverseSettings = UniverseSettings()
    risk: RiskSettings = RiskSettings()
    learning: LearningSettings = LearningSettings()
    costs: CostSettings = CostSettings()

    def _fail(self, violations: list[str]) -> None:
        if violations:
            raise ValueError("; ".join(violations))

    @model_validator(mode="after")
    def _validate_cross_section(self) -> TradingConfig:
        violations: list[str] = []
        live_mode = is_live_mode(self.app.mode)
        if self.live.enabled and not live_mode:
            violations.append(
                f"app.mode={self.app.mode.value} with live.enabled=true: live flags require a "
                "live mode (supervised_live or bounded_autonomous_live)"
            )
        if live_mode and not self.live.enabled:
            violations.append(
                f"app.mode={self.app.mode.value} with live.enabled=false: a live mode requires "
                "live.enabled=true; use a non-live mode instead"
            )

        synthetic = set(self.paper.synthetic_fixture_universe)
        overlap = synthetic & set(self.universe.live_instrument_allowlist)
        if overlap:
            violations.append(
                "universe.live_instrument_allowlist overlaps the synthetic fixture universe "
                f"({', '.join(sorted(overlap))}); simulation and live symbol sets must be "
                "independent (plan section 22)"
            )

        if live_mode:
            if self.live.approved_capital_usd <= 0:
                violations.append(
                    "live.approved_capital_usd must be > 0 for a live mode "
                    "(currently zero; approved live capital is 0 until owner approval)"
                )
            if not self.live.owner_authorization_ref:
                violations.append(
                    "live.owner_authorization_ref is required for a live mode: a recorded, "
                    "scoped, unexpired owner authorization is mandatory (plan section 17)"
                )
            if self.live.authorization_expires_at is None:
                violations.append(
                    "live.authorization_expires_at is required for a live mode: an authorization "
                    "without an expiry cannot activate live trading (plan section 17)"
                )
            if self.broker.provider != "robinhood":
                violations.append(
                    f"broker.provider={self.broker.provider} cannot run a live mode; "
                    "live trading requires the official Robinhood gateway (provider=robinhood)"
                )
            if not self.broker.approved_account_id:
                violations.append(
                    "broker.approved_account_id is required for a live mode: the dedicated "
                    "account alias is bound by the owner, never by a developer"
                )
            if not self.universe.live_instrument_allowlist:
                violations.append(
                    "universe.live_instrument_allowlist must be non-empty for a live mode: "
                    'no implicit "all symbols"'
                )
        self._fail(violations)
        return self

    def authority(self) -> str:
        return "LIVE_AUTHORIZED" if self.live.enabled else "LIVE_NOT_AUTHORIZED"

    def sanitized_summary(self) -> dict[str, Any]:
        """Serialization-safe summary for logs/CLI; never includes secrets."""
        return {
            "app": {
                "environment": self.app.environment,
                "mode": self.app.mode.value,
                "display_timezone": self.app.display_timezone,
                "exchange_timezone": self.app.exchange_timezone,
                "web_host": self.app.web_host,
                "web_port": self.app.web_port,
            },
            "llm": self.llm.sanitized_summary(),
            "broker": {
                "provider": self.broker.provider,
                "approved_account_id": self.broker.approved_account_id,
                "allowlisted_tool_schema_digest": self.broker.allowlisted_tool_schema_digest,
            },
            "live": {
                "enabled": self.live.enabled,
                "approved_capital_usd": str(self.live.approved_capital_usd),
                "owner_authorization_ref": self.live.owner_authorization_ref,
                "authorization_expires_at": (
                    self.live.authorization_expires_at.isoformat()
                    if self.live.authorization_expires_at
                    else None
                ),
            },
            "paper": {
                "initial_cash_usd": str(self.paper.initial_cash_usd),
                "synthetic_fixture_universe": list(self.paper.synthetic_fixture_universe),
            },
            "universe": {
                "live_instrument_allowlist": list(self.universe.live_instrument_allowlist),
            },
            "risk": {
                "policy_version": self.risk.policy_version,
                "max_position_nav_fraction": str(self.risk.max_position_nav_fraction),
                "max_gross_nav_fraction": str(self.risk.max_gross_nav_fraction),
                "max_positions": self.risk.max_positions,
            },
            "costs": {
                "paid_data_budget_usd_per_month": str(self.costs.paid_data_budget_usd_per_month),
                "allow_paid_subscriptions": self.costs.allow_paid_subscriptions,
            },
            "authority": self.authority(),
        }
