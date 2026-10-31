"""Broker contracts (M0 slice of build plan section 14).

M0 intentionally defines only what the broker interface and the live
activation gate need. The full order/fill/ledger contracts arrive in M1
(Prompt 2). The central invariant is that no M0 code path can return a
fabricated brokerage success: results are either explicit rejections or
explicitly unavailable state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class BrokerError(Exception):
    """Base class for classified broker errors. Safe to display."""


class BrokerUnavailable(BrokerError):
    """The broker is not connected/authenticated; nothing can be done."""


class BrokerStateNotAvailable(BrokerError):
    """Reads: no persisted state exists yet; never fabricate a snapshot."""


class BrokerExecutionNotAvailable(BrokerError):
    """The execution engine for this provider is not implemented yet."""


class BrokerExecutionDenied(BrokerError):
    """Execution was explicitly denied by policy or the activation gate."""


class NormalizedOrderStatus(StrEnum):
    """Application-normalized lifecycle states (plan section 14 diagram)."""

    PROPOSED = "proposed"
    REJECTED = "rejected"
    AWAITING_APPROVAL = "awaiting_approval"
    AUTHORIZED = "authorized"
    RESERVED = "reserved"
    SUBMISSION_PENDING = "submission_pending"
    UNKNOWN = "unknown"
    ACKNOWLEDGED = "acknowledged"
    PARTIALLY_FILLED = "partially_filled"
    CANCEL_PENDING = "cancel_pending"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    FILLED = "filled"
    RECONCILING = "reconciling"
    MANUAL_REVIEW = "manual_review"


@dataclass(frozen=True)
class BrokerCapabilities:
    """Sanitized capability report for one broker provider."""

    provider: str
    connected: bool
    reads_enabled: bool
    execution_enabled: bool
    verified_capability_digest: str | None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class OrderRequest:
    """Minimal typed submission request (M1 will extend with approval/policy bindings)."""

    instrument: str
    side: str  # "buy" | "sell"
    quantity: Decimal
    limit_price: Decimal | None
    time_in_force: str
    client_order_id: str


@dataclass(frozen=True)
class AccountSnapshot:
    """Timestamped account view. M0 adapters never report available=True."""

    available: bool
    reason: str
    as_of: datetime | None = None


@dataclass(frozen=True)
class OrderResult:
    """Outcome of a submission/cancellation attempt.

    ``accepted`` is always False in M0: no implementation can fabricate a
    brokerage success. ``rejection_reason`` names the classified cause.
    """

    accepted: bool = False
    status: NormalizedOrderStatus = NormalizedOrderStatus.REJECTED
    rejection_reason: str = ""
    broker_order_id: str | None = None
    error_class: str | None = field(default=None)
