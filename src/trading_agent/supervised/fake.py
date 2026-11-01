"""In-memory injected transport: no sockets, URLs, tokens, SDKs or broker tools."""

from __future__ import annotations

from typing import Literal, cast

from .contracts import Digest, Fill, Identifier, Intent, Record


class Observation(Record):
    status: Literal[
        "acknowledged", "broker_approval_required", "cancelled", "filled", "unknown", "rejected"
    ]
    broker_order_id: Identifier | None = None
    broker_approval_ref: Identifier | None = None
    fills: tuple[Fill, ...] = ()


class FakeTransport:
    def __init__(self, *, account_key: Digest, scenario: str = "acknowledged") -> None:
        if scenario not in {
            "acknowledged",
            "broker_approval_required",
            "rejected",
            "timeout",
            "exception",
        }:
            raise ValueError("unknown fixture scenario")
        self.account_key = account_key
        self.scenario = scenario
        self.calls: list[tuple[str, str]] = []
        self.observations: dict[str, Observation] = {}

    def submit(self, intent: Intent) -> Observation:
        if intent.account_key != self.account_key:
            raise ValueError("fake transport account mismatch")
        self.calls.append(("submit", intent.intent_id))
        if self.scenario == "timeout":
            raise TimeoutError("fictional ambiguous submission")
        if self.scenario == "exception":
            raise RuntimeError("fictional transport exception")
        result = Observation(
            status=cast(
                Literal["acknowledged", "broker_approval_required", "rejected"], self.scenario
            ),
            broker_order_id="mock-order:" + intent.intent_id,
            broker_approval_ref="mock-approval:" + intent.intent_id
            if self.scenario == "broker_approval_required"
            else None,
        )
        self.observations[intent.intent_id] = result
        return result

    def observe(self, intent_id: str) -> Observation:
        self.calls.append(("observe", intent_id))
        return self.observations.get(intent_id, Observation(status="unknown"))

    def cancel(self, intent_id: str) -> Observation:
        self.calls.append(("cancel", intent_id))
        result = self.observations.get(intent_id, Observation(status="unknown"))
        if result.status == "filled":
            return result
        if result.status == "unknown":
            return result
        result = result.changed(status="cancelled")
        self.observations[intent_id] = result
        return result
