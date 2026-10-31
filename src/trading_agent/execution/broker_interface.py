"""Broker adapter interface (build plan section 7/14).

The interface is defined before provider-specific behavior. Implementations
must:
- report sanitized capabilities, never credentials or raw account numbers;
- classify every failure;
- return explicit rejections or explicitly unavailable state — never a
  fabricated brokerage success.
"""

from __future__ import annotations

import abc

from ..contracts.broker import (
    AccountSnapshot,
    BrokerCapabilities,
    OrderRequest,
    OrderResult,
)


class BrokerAdapter(abc.ABC):
    """A broker execution venue (simulator or official Robinhood gateway)."""

    provider: str

    @abc.abstractmethod
    def capabilities(self) -> BrokerCapabilities:
        """Sanitized capability report for this provider right now."""

    @abc.abstractmethod
    def account_snapshot(self) -> AccountSnapshot:
        """Timestamped cash/positions/open-orders view.

        M0 implementations have no persisted state and must raise
        ``BrokerStateNotAvailable`` rather than fabricate a snapshot.
        """

    @abc.abstractmethod
    def submit_order(self, request: OrderRequest) -> OrderResult:
        """Submit a typed, pre-authorized order.

        M0 implementations explicitly reject: they raise a classified
        ``BrokerError``. They never return a fabricated acceptance.
        """

    @abc.abstractmethod
    def cancel_order(self, broker_order_id: str) -> OrderResult:
        """Request cancellation of an existing broker order.

        M0 implementations explicitly reject, same invariant as submit.
        """
