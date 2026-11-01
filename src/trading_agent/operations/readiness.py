"""Evidence classification never constitutes financial authorization."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from ..supervised.contracts import Record


class Evidence(Record):
    email_code: bool = False
    closeout_code: bool = False
    reconciliation_code: bool = False
    execution_controls_code: bool = False
    actual_email_delivery_and_ack: bool = False
    deployed_independent_monitor: bool = False
    actual_broker_integration: bool = False
    prospective_strategy_evidence: bool = False
    live_executor_available: Literal[False] = False
    owner_authorization_active: Literal[False] = False
    approved_live_capital: Literal[0] = 0
    # Software/integration/investment evidence cannot substitute for each other.
    notes: tuple[str, ...] = Field(default=(), max_length=20)


def readiness(evidence: Evidence) -> dict[str, object]:
    return {
        "authority": "LIVE_NOT_AUTHORIZED",
        "actual_dispatch_allowed": False,
        "software": {
            name: "CODE_PASS" if getattr(evidence, name) else "BLOCKED"
            for name in (
                "email_code",
                "closeout_code",
                "reconciliation_code",
                "execution_controls_code",
            )
        },
        "operations": {
            name: "OBSERVED_PASS" if getattr(evidence, name) else "EXTERNAL_VALIDATION_PENDING"
            for name in (
                "actual_email_delivery_and_ack",
                "deployed_independent_monitor",
                "actual_broker_integration",
            )
        },
        "investment": "OBSERVED_EVIDENCE_REQUIRES_OWNER_REVIEW"
        if evidence.prospective_strategy_evidence
        else "EXTERNAL_VALIDATION_PENDING",
        "activation": "BLOCKED",
        "approved_live_capital_usd": "0",
        "unmet": ["live_executor_unavailable", "real_owner_authorization_absent", "capital_zero"],
        "notes": evidence.notes,
    }
