"""Internal simulated broker (build plan section 14/17, operational mode SIMULATION).

M0 status: explicit placeholder. The simulator execution engine (order
lifecycle, fills, reservations, ledger) is the M1 deliverable (Prompt 2).
Until then every execution call fails closed with a classified error and no
state is fabricated.
"""

from __future__ import annotations

from ..contracts.broker import (
    AccountSnapshot,
    BrokerCapabilities,
    BrokerExecutionNotAvailable,
    BrokerStateNotAvailable,
    OrderRequest,
    OrderResult,
)
from .broker_interface import BrokerAdapter

_M1 = (
    "the simulator engine is not implemented yet (M1, Prompt 2); "
    "M0 refuses to fabricate brokerage state or success"
)


class SimulatorBrokerAdapter(BrokerAdapter):
    """Local simulated execution venue. No external connection is required."""

    provider = "simulator"

    def capabilities(self) -> BrokerCapabilities:
        return BrokerCapabilities(
            provider=self.provider,
            connected=True,  # local venue: no external dependency
            reads_enabled=False,
            execution_enabled=False,
            verified_capability_digest=None,
            notes=(
                "M0 placeholder: engine lands in M1 (Prompt 2)",
                "no live account, no external network, no real money",
            ),
        )

    def account_snapshot(self) -> AccountSnapshot:
        raise BrokerStateNotAvailable(f"simulator account snapshot unavailable: {_M1}")

    def submit_order(self, request: OrderRequest) -> OrderResult:
        raise BrokerExecutionNotAvailable(
            f"simulator order submission rejected: {_M1}; "
            f"requested {request.side} {request.instrument} (not executed, no effect)"
        )

    def cancel_order(self, broker_order_id: str) -> OrderResult:
        raise BrokerExecutionNotAvailable(
            f"simulator cancellation rejected: {_M1}; order {broker_order_id!r} left untouched"
        )
