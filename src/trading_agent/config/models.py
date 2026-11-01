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

import os
import re
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

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
from ..security.loopback import is_loopback_url as _is_loopback_url

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


class SourceId(StrEnum):
    """M3 data-source registry identifiers (plan section 8: registry-driven)."""

    SYNTHETIC = "synthetic"
    FRED = "fred"
    ALPHAVANTAGE = "alpha_vantage"
    COINGECKO = "coingecko"
    COINDESK = "coindesk"
    YAHOO = "yahoo"
    COINBASE = "coinbase"


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


class AppSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment: Literal["development", "staging", "production"] = "development"
    mode: TradingMode = TradingMode.SIMULATION
    display_timezone: str = "America/Chicago"
    exchange_timezone: str = "America/New_York"
    web_host: str = "127.0.0.1"
    web_port: int = Field(default=8000, ge=1024, le=65535)
    db_url: str = "postgresql+psycopg://trading_agent@127.0.0.1:5433/trading_agent"

    @field_validator("web_host")
    @classmethod
    def _validate_web_host(cls, value: str) -> str:
        if value.strip().lower() not in LOOPBACK_HOSTS:
            raise ValueError(
                f"app.web_host: {value!r} is not loopback; the website must bind to "
                "127.0.0.1/localhost (plan section 18)"
            )
        return value.strip()

    @field_validator("db_url")
    @classmethod
    def _validate_db_url(cls, value: str) -> str:
        from urllib.parse import urlparse

        parsed = urlparse(value)
        host = parsed.hostname or ""
        if host.lower() not in LOOPBACK_HOSTS:
            raise ValueError(
                f"app.db_url: host {host!r} is not loopback; the application database must be local"
            )
        return value

    @field_validator("display_timezone", "exchange_timezone")
    @classmethod
    def _validate_timezone(cls, value: str) -> str:
        if not value or "/" not in value:
            raise ValueError(
                f"timezone {value!r} is not an IANA zone name (expected e.g. America/Chicago)"
            )
        return value


class WebSettings(BaseModel):
    """Website settings (M5, website spec section 22: off by default).

    The token has exactly three possible sources, in precedence order:
    1. an explicit value (``web.token``, e.g. via the TRADING_AGENT_WEB_TOKEN
       environment variable),
    2. an environment-variable reference (``web.token_env``: the *name* of the
       variable, never its value, in this file),
    3. a bootstrap file (``web.token_file``) generated for local development.
    A live mode requires source 1 or 2 — never the bootstrap file.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False  # the website is OFF by default (website spec 22)
    token: SecretStr | None = None
    token_env: str | None = None
    token_file: str = ".data/web_token"
    session_ttl_seconds: int = Field(default=28800, ge=60)  # 8h, max age for web cookies
    stream_poll_seconds: float = Field(default=5.0, gt=0, le=60)
    stream_idle_timeout_seconds: float = Field(default=900, gt=0, le=3600)
    login_rate_limit: int = Field(default=10, ge=1)
    login_rate_window_seconds: int = Field(default=900, ge=10)
    logout_invalidates: bool = True

    @field_validator("token_env")
    @classmethod
    def _validate_token_env(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
            raise ValueError(f"web.token_env: {value!r} is not a valid environment variable name")
        return value

    @model_validator(mode="after")
    def _validate_token_sources(self) -> WebSettings:
        if self.token is not None and self.token_env is not None:
            raise ValueError(
                "web: set exactly one of web.token (explicit value) or "
                "web.token_env (environment variable reference)"
            )
        if self.token is not None and not self.token.get_secret_value().strip():
            raise ValueError("web.token: an explicit token must be non-empty")
        return self

    def resolved_token(self) -> str | None:
        """The token to use, if configured. Never logged, never echoed."""
        if self.token_env:
            value = os.environ.get(self.token_env)
            return value.strip() if value and value.strip() else None
        if self.token is not None:
            value = self.token.get_secret_value().strip()
            return value if value else None
        return None

    def token_source(self) -> Literal["value", "env", "file", "none"]:
        if self.token is not None:
            return "value"
        if self.token_env:
            return "env"
        return "file" if self.enabled else "none"

    def sanitized_summary(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "token_source": self.token_source(),
            "token_configured": self.resolved_token() is not None
            or (self.enabled and bool(self.token_file)),
            "session_ttl_seconds": self.session_ttl_seconds,
            "stream_poll_seconds": self.stream_poll_seconds,
        }


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
                "llm.base_url: endpoint is not a loopback address; accidental cloud "
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


class ResearchSettings(BaseModel):
    """M2 research overlay: local LLM evaluations, sanitized and persisted.

    Research is an opt-in, non-executing overlay: it can never change the
    deterministic strategy's decisions, risk checks, or ledger. Invalid or
    unavailable model output degrades to a recorded HOLD (plan section 9).
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    prompt_template: Literal["research-v1", "research-v2"] = "research-v1"
    evaluations_per_job: int = Field(default=2, ge=1)
    max_response_chars: int = Field(default=8_000, ge=500, le=32_000)
    monthly_call_budget: int = Field(default=200, ge=1)
    closes_per_brief: int = Field(default=1, ge=1)
    compare_with_strategy: bool = True


class BrokerSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["simulator", "robinhood"] = "simulator"
    robinhood_mcp_url: str = "https://agent.robinhood.com/mcp/trading"
    approved_account_id: str | None = None
    allowlisted_tool_schema_digest: str | None = None
    # M4 shadow mode (plan section 14): read-only observation of the owner's
    # own Robinhood account via the official MCP. Execution stays disabled.
    shadow_enabled: bool = False
    # Which provider the persistent shadow gateway observes. Defaults to the
    # engine's ``provider`` when null. Lets paper runs keep the simulator
    # while the gateway watches the real account (plan section 14/17).
    shadow_provider: Literal["simulator", "robinhood"] | None = None
    shadow_poll_seconds: float = Field(default=30.0, ge=5.0, le=3600.0)
    account_number: str | None = None
    token_store_path: str = ".data/robinhood_mcp_token.json"
    capability_allowlist_path: str = ".data/robinhood_tool_allowlist.json"
    request_timeout_seconds: float = Field(default=20.0, ge=1.0, le=120.0)

    @field_validator("robinhood_mcp_url")
    @classmethod
    def _official_endpoint(cls, value: str) -> str:
        from ..security.loopback import require_official_broker_url

        require_official_broker_url(value)
        return value


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
    research_store_dir: Path = Path(".data/learning")
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


class SourceRefreshSpec(BaseModel):
    """Freshness thresholds for one registry source (explicit, never guessed)."""

    model_config = ConfigDict(extra="forbid")

    max_age_minutes: int = Field(default=1440, ge=1)
    backfill_sessions: int = Field(default=10, ge=0)


class SourceSpec(BaseModel):
    """One entry of the M3 data-source registry (plan section 8).

    ``api_key_env`` names the environment variable holding an API key; the key
    value itself never appears in configuration files or summaries. An enabled
    source whose API cannot be reached is reported ``unreachable`` and the rest
    of the system proceeds on the sources that did deliver: data availability
    is fail-closed, execution authority is always live_not_authorized.
    """

    model_config = ConfigDict(extra="forbid")

    id: SourceId
    enabled: bool = False
    symbols: list[str] = []
    asset_classes: list[str] = []
    api_base_url: str | None = None  # per-source override (tests / mirrors)
    api_key_env: str | None = None
    refresh: SourceRefreshSpec = SourceRefreshSpec()

    @field_validator("api_base_url")
    @classmethod
    def _data_origin(cls, value: str | None) -> str | None:
        if value not in (None, "https://api.stlouisfed.org"):
            raise ValueError("unapproved data origin")
        return value

    @field_validator("symbols")
    @classmethod
    def _validate_symbols(cls, value: list[str]) -> list[str]:
        cleaned = [symbol.strip() for symbol in value if symbol.strip()]
        for symbol in cleaned:
            if symbol.startswith(SYNTHETIC_PREFIX):
                raise ValueError(
                    f"data.registry: {symbol} is a synthetic {SYNTHETIC_PREFIX}* fixture "
                    "identifier and must not be registered against a real data source"
                )
        return cleaned

    @field_validator("asset_classes")
    @classmethod
    def _validate_asset_classes(cls, value: list[str]) -> list[str]:
        allowed = {
            "us_equity",
            "global_equity",
            "us_bond",
            "global_bond",
            "us_fx",
            "global_fx",
            "us_commodity",
            "crypto",
            "synthetic-equity",
        }
        cleaned = [item.strip() for item in value if item.strip()]
        for asset_class in cleaned:
            if asset_class not in allowed:
                raise ValueError(
                    f"data.registry asset_classes: {asset_class!r} is not a v1 asset class "
                    f"(expected one of: {', '.join(sorted(allowed))})"
                )
        return cleaned


class DataSettings(BaseModel):
    """Market data selection plus the M3 registry-driven source registry."""

    model_config = ConfigDict(extra="forbid")

    source: Literal["synthetic"] = "synthetic"
    fixture_seed: int = Field(default=20260504, ge=1)
    start_session: date = date(2026, 5, 4)
    sessions: int = Field(default=128, ge=10)
    stale_after_sessions: int = Field(default=10, ge=1)
    missing_scenarios: list[dict[str, str]] = []
    scenarios: list[Literal["lost_ack"]] = []
    registry: list[SourceSpec] = Field(
        default_factory=lambda: [SourceSpec(id=SourceId.SYNTHETIC, enabled=True)]
    )
    # On-disk cache for registry sources (data sync/status commands).
    registry_root: Path = Path("data/registry")

    @model_validator(mode="after")
    def _validate_registry(self) -> DataSettings:
        seen: set[str] = set()
        for entry in self.registry:
            if entry.id in seen:
                raise ValueError(f"data.registry: duplicate source id {entry.id!r}")
            seen.add(entry.id)
            if entry.id == SourceId.SYNTHETIC and entry.enabled and entry.symbols:
                raise ValueError(
                    "data.registry: the synthetic source derives its universe from "
                    "paper.synthetic_fixture_universe; do not list symbols for it"
                )
            if entry.enabled and entry.id != SourceId.SYNTHETIC and not entry.symbols:
                raise ValueError(
                    f"data.registry: enabled source {entry.id!r} must list at least one symbol"
                )
        return self


class StrategySettings(BaseModel):
    """The first deterministic strategy (rules documented before tuning)."""

    model_config = ConfigDict(extra="forbid")

    name: str = "trend-momentum"
    version: str = "momentum-v1"
    lookback_days: int = Field(default=20, ge=2)
    entry_momentum: Decimal = Decimal("0.05")
    exit_momentum: Decimal = Decimal("0")
    target_weight: Decimal = Decimal("0.05")
    order_slice_weight: Decimal = Decimal("0.02")

    @model_validator(mode="after")
    def _validate_weights(self) -> StrategySettings:
        if self.order_slice_weight > self.target_weight:
            raise ValueError("strategy.order_slice_weight must not exceed strategy.target_weight")
        if self.target_weight > 1:
            raise ValueError("strategy.target_weight must be <= 1")
        return self


class EngineSettings(BaseModel):
    """Simulated venue and benchmark conventions (engineering fixtures)."""

    model_config = ConfigDict(extra="forbid")

    decision_offset_minutes: int = Field(default=30, ge=1)
    commission_bps: Decimal = Decimal("0")
    spread_bps: Decimal = Decimal("5")
    cash_yield_annual: Decimal = Decimal("0.045")
    passive_basket: list[str] = ["TEST_A", "TEST_B", "TEST_C"]

    @field_validator("commission_bps", "spread_bps", mode="before")
    @classmethod
    def _validate_engine_bps(cls, value: Any, info: ValidationInfo) -> Decimal:
        return _decimal(value, field=f"engine.{info.field_name}", allow_negative=False)

    @field_validator("cash_yield_annual", mode="before")
    @classmethod
    def _validate_engine_yield(cls, value: Any, info: ValidationInfo) -> Decimal:
        return _fraction(value, field="engine.cash_yield_annual")


class BacktestCostSettings(BaseModel):
    """Per-fill cost model for backtests (plan section 11, M3 prompt)."""

    model_config = ConfigDict(extra="forbid")

    fee_rate: Decimal = Decimal("0.000418")  # 0.0418% of traded notional
    slippage_rate: Decimal = Decimal("0.0015")  # 0.15% of traded notional

    @field_validator("fee_rate", "slippage_rate", mode="before")
    @classmethod
    def _validate_rates(cls, value: Any, info: ValidationInfo) -> Decimal:
        return _fraction(value, field=f"backtest.cost.{info.field_name}")


class WalkForwardSettings(BaseModel):
    """Time-ordered walk-forward evaluation (train/validate/test, M3).

    Every candidate parameter set is fitted only on data strictly before its
    test fold; the fold's test window is never used to choose parameters.
    """

    model_config = ConfigDict(extra="forbid")

    fold_days: int = Field(default=183, ge=10)
    min_train_days: int = Field(default=126, ge=10)
    score: str = "sharpe"  # or cagr
    lookback_candidates: list[int] = [10, 20, 40]
    entry_candidates: list[Decimal] = [Decimal("0.03"), Decimal("0.05"), Decimal("0.10")]
    exit_candidates: list[Decimal] = [Decimal("0.00")]

    @field_validator("entry_candidates", "exit_candidates", mode="before")
    @classmethod
    def _validate_candidates(cls, value: Any, info: ValidationInfo) -> list[Decimal]:
        if isinstance(value, (list, tuple)) and value:
            return [
                _fraction(item, field=f"backtest.walk_forward.{info.field_name}") for item in value
            ]
        raise ValueError(f"backtest.walk_forward.{info.field_name} must be a non-empty list")

    @model_validator(mode="after")
    def _validate_folds(self) -> WalkForwardSettings:
        if self.fold_days < self.min_train_days:
            raise ValueError(
                f"backtest.walk_forward.fold_days ({self.fold_days}) must be at least "
                f"min_train_days ({self.min_train_days})"
            )
        if not self.lookback_candidates or min(self.lookback_candidates) < 2:
            raise ValueError("backtest.walk_forward.lookback_candidates must contain values >= 2")
        if self.score not in {"sharpe", "cagr"}:
            raise ValueError("backtest.walk_forward.score must be 'sharpe' or 'cagr'")
        return self


class BacktestSettings(BaseModel):
    """Backtest run settings (M3). Inert for live/paper runs (None default)."""

    model_config = ConfigDict(extra="forbid")

    range_start: date
    range_end: date
    initial_cash_usd: Decimal = Decimal("10000")
    cash_yield_annual: Decimal = Decimal("0.045")
    cost: BacktestCostSettings = BacktestCostSettings()
    walk_forward: WalkForwardSettings = WalkForwardSettings()
    include_synthetic: bool = False  # deterministic synthetic demo of the same engine
    output_dir: str = "reports"

    @field_validator("range_start", "range_end", mode="before")
    @classmethod
    def _validate_range(cls, value: Any, info: ValidationInfo) -> date:
        if isinstance(value, str):
            return date.fromisoformat(value)
        return value

    @field_validator("initial_cash_usd", mode="before")
    @classmethod
    def _validate_cash(cls, value: Any) -> Decimal:
        return _decimal(value, field="backtest.initial_cash_usd")

    @field_validator("cash_yield_annual", mode="before")
    @classmethod
    def _validate_yield(cls, value: Any) -> Decimal:
        return _fraction(value, field="backtest.cash_yield_annual")

    @model_validator(mode="after")
    def _validate_consistency(self) -> BacktestSettings:
        if self.initial_cash_usd <= 0:
            raise ValueError("backtest.initial_cash_usd must be positive")
        if self.range_start >= self.range_end:
            raise ValueError("backtest.range_start must be before backtest.range_end")
        return self


class TradingConfig(BaseModel):
    """Root configuration. Unknown sections are rejected (versioned contract)."""

    model_config = ConfigDict(extra="forbid")

    app: AppSettings = AppSettings()
    web: WebSettings = WebSettings()
    llm: LLMSettings = LLMSettings()
    broker: BrokerSettings = BrokerSettings()
    live: LiveSettings = LiveSettings()
    paper: PaperSettings = PaperSettings()
    universe: UniverseSettings = UniverseSettings()
    risk: RiskSettings = RiskSettings()
    learning: LearningSettings = LearningSettings()
    costs: CostSettings = CostSettings()
    data: DataSettings = DataSettings()
    strategy: StrategySettings = StrategySettings()
    engine: EngineSettings = EngineSettings()
    research: ResearchSettings = ResearchSettings()
    backtest: BacktestSettings | None = None

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

        if self.research.enabled and live_mode:
            violations.append(
                "research.enabled=true is not permitted in a live mode yet: M2 research "
                "is a simulation-only overlay (plan section 9); enable it in a non-live mode"
            )
        if self.research.evaluations_per_job > self.llm.max_calls_per_research_job:
            violations.append(
                f"research.evaluations_per_job={self.research.evaluations_per_job} exceeds "
                f"llm.max_calls_per_research_job={self.llm.max_calls_per_research_job}: the "
                "per-job call budget is the enforcement ceiling (plan section 9)"
            )

        if live_mode:
            if self.web.enabled and self.web.resolved_token() is None:
                violations.append(
                    "live mode with web.enabled=true requires an explicit website token "
                    "(web.token or web.token_env set, e.g. TRADING_AGENT_WEB_TOKEN): the "
                    "bootstrap file is a development convenience and is forbidden in live"
                )
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
        return "LIVE_NOT_AUTHORIZED"

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
                "db_url_host": (urlparse(self.app.db_url).hostname or ""),
            },
            "web": self.web.sanitized_summary(),
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
            "data": {
                "source": self.data.source,
                "fixture_seed": self.data.fixture_seed,
                "start_session": self.data.start_session.isoformat(),
                "sessions": self.data.sessions,
                "registry": [
                    {
                        "id": entry.id,
                        "enabled": entry.enabled,
                        "symbols": entry.symbols,
                        "asset_classes": entry.asset_classes,
                        "api_base_url": entry.api_base_url,
                        "api_key_configured": bool(
                            entry.api_key_env and os.environ.get(entry.api_key_env)
                        ),
                        "refresh": entry.refresh.model_dump(mode="json"),
                    }
                    for entry in self.data.registry
                ],
            },
            "strategy": {
                "name": self.strategy.name,
                "version": self.strategy.version,
                "lookback_days": self.strategy.lookback_days,
            },
            "research": {
                "enabled": self.research.enabled,
                "prompt_template": self.research.prompt_template,
                "evaluations_per_job": self.research.evaluations_per_job,
            },
            "authority": self.authority(),
        }
