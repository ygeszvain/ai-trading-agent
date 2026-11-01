"""Immutable intent/consent contracts. All signatures in this module are MOCK ONLY."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from functools import wraps
from typing import Annotated, Any, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.:-]{1,96}$")]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Amount = Annotated[Decimal, Field(ge=0, max_digits=20, decimal_places=8)]
Positive = Annotated[Decimal, Field(gt=0, max_digits=20, decimal_places=8)]
# Public fixture material, deliberately incapable of authenticating a real owner.
_FIXTURE_KEY = b"M6-MOCK-ONLY-NOT-AN-OWNER-CREDENTIAL"
AUTHORITY: Literal["LIVE_NOT_AUTHORIZED"] = "LIVE_NOT_AUTHORIZED"


def digest(value: Any) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def money_context[**P, T](function: Callable[P, T]) -> Callable[P, T]:
    @wraps(function)
    def call(*args: P.args, **kwargs: P.kwargs) -> T:
        with localcontext(Context(prec=28, rounding=ROUND_HALF_EVEN)):
            return function(*args, **kwargs)

    return call


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, allow_inf_nan=False)

    def digest(self) -> str:
        return digest(self)

    def changed(self, **values: Any) -> Self:
        return type(self).model_validate(self.model_dump() | values)


class Intent(Record):
    domain: Literal["M6_MOCK_ONLY", "M7_MOCK_ONLY"] = "M6_MOCK_ONLY"
    intent_id: Identifier
    run_id: Identifier
    account_alias: Identifier
    account_key: Digest  # exact protected-runtime identity fingerprint, never an account number
    mode: Literal["supervised_live", "bounded_autonomous_live"] = "supervised_live"
    instrument: Identifier
    side: Literal["buy", "sell"]
    quantity: Positive
    target_weight: Annotated[Decimal, Field(ge=0, le=1)]
    limit_price: Positive
    price_lower: Positive
    price_upper: Positive
    max_fee: Amount
    order_type: Literal["limit"] = "limit"
    time_in_force: Literal["day"] = "day"
    strategy_version: Identifier
    policy_version: Identifier
    strategy_hash: Digest
    policy_hash: Digest
    evidence_hashes: tuple[Digest, ...] = Field(min_length=1, max_length=12)
    risk_snapshot_hash: Digest
    created_at: AwareDatetime
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def bounds(self) -> Self:
        if not self.price_lower <= self.limit_price <= self.price_upper:
            raise ValueError("price constraints inconsistent")
        if self.expires_at <= self.created_at or self.quantity != self.quantity.to_integral_value():
            raise ValueError("intent requires a positive lifetime and whole shares")
        return self


class Grant(Record):
    domain: Literal["M6_MOCK_ONLY"] = "M6_MOCK_ONLY"
    authorization_id: Identifier
    owner: Literal["fixture-owner"] = "fixture-owner"
    account_alias: Identifier
    account_key: Digest
    mode: Literal["supervised_live"] = "supervised_live"
    capital: Positive
    universe: tuple[Identifier, ...] = Field(min_length=1)
    policy_hash: Digest
    strategy_hash: Digest
    starts_at: AwareDatetime
    expires_at: AwareDatetime


class Approval(Record):
    domain: Literal["M6_MOCK_ONLY"] = "M6_MOCK_ONLY"
    approval_id: Identifier
    owner: Literal["fixture-owner"] = "fixture-owner"
    intent_hash: Digest  # canonical hash binds EVERY intent field, including evidence and target
    authorization_hash: Digest
    epoch: int = Field(ge=0)
    issued_at: AwareDatetime
    expires_at: AwareDatetime


class Resume(Record):
    resume_id: Identifier
    state_revision: int = Field(ge=0)
    domain: Literal["M6_MOCK_ONLY"] = "M6_MOCK_ONLY"
    account_key: Digest
    boot_id: Identifier
    epoch: int = Field(ge=0)
    issued_at: AwareDatetime
    expires_at: AwareDatetime


class Signed(Record):
    payload_json: str = Field(max_length=24000)
    signature: Digest


def mock_sign(record: Record) -> Signed:
    """Test owner control plane only; never exported as a real authorization method."""
    payload = record.model_dump_json()
    return Signed(
        payload_json=payload,
        signature=hmac.new(_FIXTURE_KEY, payload.encode(), hashlib.sha256).hexdigest(),
    )


def verify[T: Record](signed: Signed, kind: type[T]) -> T:
    expected = hmac.new(_FIXTURE_KEY, signed.payload_json.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signed.signature):
        raise ValueError("invalid MOCK consent signature")
    return kind.model_validate_json(signed.payload_json)


class Health(Record):
    status: Literal["healthy", "unknown", "failed"] = "unknown"
    as_of: AwareDatetime | None = None


class Quote(Record):
    instrument: Identifier
    price: Positive
    mark: Positive
    volume: Amount
    as_of: AwareDatetime
    eligible: bool = False
    asset_class: Literal["unleveraged_etf", "unsupported"] = "unsupported"
    tradable: bool = False
    regular_session: bool = False
    minimum_quantity: Positive = Decimal(1)
    price_tick: Positive = Decimal("0.01")


class Holding(Record):
    instrument: Identifier
    quantity: Amount
    average_cost: Amount
    realized_pnl: Decimal = Field(default=Decimal(0), max_digits=20, decimal_places=8)


class StrategyManifest(Record):
    code_hash: Digest
    dependency_hash: Digest
    model_hash: Digest
    prompt_hash: Digest
    feature_hash: Digest
    strategy_settings_json: str = Field(max_length=16000)


class State(Record):
    domain: Literal["M6_MOCK_ONLY", "M7_MOCK_ONLY"] = "M6_MOCK_ONLY"
    account_alias: Identifier
    account_key: Digest
    observed_account_key: Digest
    run_id: Identifier
    config_json: str = Field(max_length=64000)
    authorization: Signed | None = None
    strategy_hash: Digest
    strategy_frozen: bool = False
    strategy_manifest: StrategyManifest
    data: Health = Health()
    reconciliation: Health = Health()
    audit: Health = Health()
    eligibility_as_of: AwareDatetime | None = None
    account_as_of: AwareDatetime | None = None
    quote: Quote
    cash: Amount
    reserved_cash: Amount = Decimal(0)
    holdings: tuple[Holding, ...] = ()
    high_water_mark: Positive
    day_start_nav: Positive
    daily_turnover: Amount = Decimal(0)
    entry_attempts: int = Field(default=0, ge=0)
    epoch: int = Field(default=0, ge=0)
    executor_generation: int = Field(default=0, ge=0)
    boot_id: Identifier = "not-started"
    resumed: bool = False
    revoked: bool = False
    paused: bool = True
    revision: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def unique_holdings(self) -> Self:
        if len({p.instrument for p in self.holdings}) != len(self.holdings):
            raise ValueError("duplicate holdings")
        return self

    def risk_hash(self) -> str:
        return digest(
            {
                key: self.model_dump(mode="json")[key]
                for key in (
                    "account_key",
                    "observed_account_key",
                    "cash",
                    "holdings",
                    "quote",
                    "account_as_of",
                    "high_water_mark",
                    "day_start_nav",
                    "strategy_hash",
                    "config_json",
                )
            }
        )


class Fill(Record):
    fill_id: Identifier
    order_id: Identifier
    account_key: Digest
    instrument: Identifier
    side: Literal["buy", "sell"]
    quantity: Positive
    price: Positive
    fee: Amount
    at: AwareDatetime


class Order(Record):
    intent: Intent
    approval_id: Identifier
    authorization_hash: Digest
    epoch: int
    boot_id: Identifier
    status: Literal[
        "submission_pending",
        "acknowledged",
        "broker_approval_required",
        "unknown",
        "rejected",
        "partially_filled",
        "cancel_pending",
        "cancelled",
        "filled",
        "manual_review",
    ]
    reserved_cash: Amount
    remaining_quantity: Amount
    filled_quantity: Amount = Decimal(0)
    fees: Amount = Decimal(0)
    broker_order_id: Identifier | None = None
    broker_approval_ref: Identifier | None = None
    before_hash: Digest
    dispatch_started: bool = False
    executor_generation: int = Field(default=0, ge=0)


class Check(Record):
    name: str
    satisfied: bool
    detail: str


class Readiness(Record):
    authority: Literal["LIVE_NOT_AUTHORIZED"] = AUTHORITY
    actual_dispatch_allowed: Literal[False] = False
    mock_controls_satisfied: bool
    checks: tuple[Check, ...]


class Permit(Record):
    """An execution-side check result, never an issued owner authorization."""

    authorization_hash: Digest
    report: Readiness
