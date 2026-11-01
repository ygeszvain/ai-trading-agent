"""Order, fill, reservation, and activity contracts (build plan section 14/16).

The normalized order status vocabulary matches the section 14 state machine.
Broker-raw statuses are retained alongside the normalized status. A canceled
order may retain fills; a cancellation request is not a cancellation
confirmation. A timed-out submission stays UNKNOWN until reconciliation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from .broker import NormalizedOrderStatus


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    LIMIT = "limit"


class TimeInForce(StrEnum):
    DAY = "day"


class AttemptOutcome(StrEnum):
    """Outcome of a submission attempt against the venue."""

    ACKNOWLEDGED = "acknowledged"
    REJECTED = "rejected"
    UNKNOWN = "unknown"  # response lost; order must stay UNKNOWN until reconciled

    def to_status(self) -> NormalizedOrderStatus:
        return {
            AttemptOutcome.ACKNOWLEDGED: NormalizedOrderStatus.ACKNOWLEDGED,
            AttemptOutcome.REJECTED: NormalizedOrderStatus.REJECTED,
            AttemptOutcome.UNKNOWN: NormalizedOrderStatus.UNKNOWN,
        }[self]


@dataclass(frozen=True)
class OrderIntent:
    """Application-level intent: what the strategy wants, with all bindings."""

    intent_id: str
    run_id: str
    decision_id: str
    account_alias: str
    instrument_id: str
    side: OrderSide
    quantity: Decimal
    limit_price: Decimal
    time_in_force: TimeInForce
    client_order_id: str
    created_at: datetime
    policy_version: str
    strategy_version: str


@dataclass(frozen=True)
class SubmissionAttempt:
    """One attempt to submit an order to the venue (plan section 16)."""

    attempt_id: str
    run_id: str
    order_id: str
    request_digest: str
    submitted_at: datetime
    outcome: AttemptOutcome
    raw_status: str
    error_class: str | None = None


@dataclass
class Order:
    """The application's order record (the "broker order" of the simulator).

    Mutable on purpose: the state machine advances it. Every transition is
    also appended to ``events`` and persisted, so the timeline is auditable
    and a restart never rewrites history.
    """

    order_id: str
    run_id: str
    intent_id: str
    client_order_id: str
    account_alias: str
    instrument_id: str
    side: OrderSide
    order_type: OrderType
    limit_price: Decimal
    quantity: Decimal
    time_in_force: TimeInForce
    created_at: datetime
    status: NormalizedOrderStatus = NormalizedOrderStatus.SUBMISSION_PENDING
    raw_status: str = "pending"
    filled_quantity: Decimal = Decimal("0")
    last_fill_price: Decimal | None = None
    updated_at: datetime | None = None
    expires_at: datetime | None = None
    cancel_requested_at: datetime | None = None
    events: list[tuple[datetime, NormalizedOrderStatus, str]] = field(default_factory=list)

    def remaining_quantity(self) -> Decimal:
        return self.quantity - self.filled_quantity

    def transition(self, to: NormalizedOrderStatus, at: datetime, reason: str) -> None:
        status = NormalizedOrderStatus
        allowed = {
            status.SUBMISSION_PENDING: {status.ACKNOWLEDGED, status.REJECTED, status.UNKNOWN},
            status.ACKNOWLEDGED: {
                status.PARTIALLY_FILLED,
                status.FILLED,
                status.CANCEL_PENDING,
                status.CANCELLED,
                status.EXPIRED,
                status.UNKNOWN,
            },
            status.PARTIALLY_FILLED: {
                status.PARTIALLY_FILLED,
                status.FILLED,
                status.CANCEL_PENDING,
                status.CANCELLED,
                status.EXPIRED,
                status.UNKNOWN,
            },
            status.CANCEL_PENDING: {
                status.PARTIALLY_FILLED,
                status.FILLED,
                status.CANCELLED,
                status.EXPIRED,
                status.UNKNOWN,
            },
            status.UNKNOWN: {
                status.RECONCILING,
                status.MANUAL_REVIEW,
                status.ACKNOWLEDGED,
                status.PARTIALLY_FILLED,
                status.FILLED,
                status.CANCELLED,
                status.EXPIRED,
                status.REJECTED,
            },
            status.RECONCILING: {
                status.ACKNOWLEDGED,
                status.PARTIALLY_FILLED,
                status.FILLED,
                status.CANCELLED,
                status.EXPIRED,
                status.REJECTED,
                status.MANUAL_REVIEW,
                status.UNKNOWN,
            },
            status.MANUAL_REVIEW: {status.RECONCILING},
        }
        initial = (
            self.status is status.SUBMISSION_PENDING
            and to is self.status
            and not self.events
            and self.updated_at is None
        )
        if not initial and to not in allowed.get(self.status, set()):
            raise ValueError(f"illegal order transition {self.status.value} -> {to.value}")
        if at.tzinfo is None or (self.updated_at is not None and at < self.updated_at):
            raise ValueError("order event timestamp is naive or precedes prior event")
        if self.filled_quantity < 0 or self.filled_quantity > self.quantity:
            raise ValueError("filled quantity outside order bounds")
        if to is status.FILLED and self.filled_quantity != self.quantity:
            raise ValueError("FILLED requires exact complete quantity")
        self.events.append((at, to, reason))
        self.status = to
        self.updated_at = at


@dataclass(frozen=True)
class Fill:
    """One fill with a stable id; the ledger applies each raw id exactly once."""

    fill_id: str
    run_id: str
    order_id: str
    instrument_id: str
    side: OrderSide
    ts: datetime
    quantity: Decimal
    price: Decimal
    fee: Decimal
    raw_fill_id: str
    source: str = "simulator"
    corrected_by: str | None = None


class ReservationKind(StrEnum):
    CASH = "cash"
    INVENTORY = "inventory"
    EXPOSURE = "exposure"
    POSITION_SLOT = "position_slot"


class ReservationStatus(StrEnum):
    ACTIVE = "active"
    CONSUMED = "consumed"  # fully used by confirmed fills
    RELEASED = "released"  # order cancelled/expired; capacity returned


@dataclass(frozen=True)
class Reservation:
    """A transactional reservation against cash/exposure/slots (plan section 16)."""

    reservation_id: str
    run_id: str
    kind: ReservationKind
    order_id: str
    intent_id: str
    instrument_id: str
    amount: Decimal  # cash: worst-case USD; exposure: NAV fraction; slot: 1
    status: ReservationStatus = ReservationStatus.ACTIVE
    reserved_at: datetime | None = None
    resolved_at: datetime | None = None
    fencing_token: int = 0


class EventOrigin(StrEnum):
    STRATEGY = "strategy"
    RISK = "risk"
    EXECUTION = "execution"
    RECONCILIATION = "reconciliation"
    SYSTEM = "system"


@dataclass(frozen=True)
class ActivityEvent:
    """Durable, cursor-ordered activity feed record (plan section 16 outbox)."""

    event_id: str
    cursor: int
    run_id: str
    account_alias: str
    mode: str
    ts: datetime
    origin: EventOrigin
    event_type: str
    correlation: dict[str, str]  # decision/order/fill/reservation references
    payload: dict[str, str]  # sanitized; Decimal values serialized as strings
    corrected_by: str | None = None


@dataclass(frozen=True)
class RuntimeStatus:
    """Runtime prerequisites the activation gate can observe (plan section 17).

    ``None`` means "no data yet" — the gate treats that as unmet and never
    guesses. The demo/serve paths build this from persisted state.
    """

    last_reconciliation_status: str | None = None  # consistent | needs-review
    active_strategy_versions: tuple[str, ...] = ()
