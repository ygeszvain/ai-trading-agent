"""Typed decision and risk-evaluation contracts (build plan sections 10 and 13).

The decision contract follows plan section 10: strict schema, explicit HOLD,
identity/time/policy/account bindings supplied by the application (never
trusted from a model), and Decimal amounts. M1 decisions are produced by a
deterministic strategy; the model fields exist for M2 and stay None in M1.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class DecisionAction(StrEnum):
    HOLD = "HOLD"
    ENTER = "ENTER"
    EXIT = "EXIT"


class RiskOutcome(StrEnum):
    PASS = "pass"
    REDUCE = "reduce"
    REJECT = "reject"


@dataclass(frozen=True)
class Decision:
    """One instrument-level trading decision (or explicit HOLD)."""

    decision_id: str
    run_id: str
    account_alias: str
    mode: str
    instrument_id: str
    decision_at: datetime  # UTC
    expires_at: datetime  # UTC; execution after expiry is invalid
    action: DecisionAction
    target_weight: Decimal  # fraction of book equity (0.05 == 5%)
    strategy_version: str
    model_version: str | None  # None in M1: deterministic decision
    data_snapshot_id: str
    rationale: str
    invalidation_conditions: tuple[str, ...] = field(default=())
    risk_policy_version: str = "paper-policy-v1"


@dataclass(frozen=True)
class RiskEvaluation:
    """The deterministic risk engine's verdict on one decision.

    ``reasons`` carries machine-readable check names plus a human detail for
    each failed (or, when reduced, affected) check. ``limits`` records the
    calculated policy limits actually applied, for audit (plan section 16).
    """

    evaluation_id: str
    run_id: str
    decision_id: str
    policy_version: str
    evaluated_at: datetime
    outcome: RiskOutcome
    reasons: tuple[tuple[str, str], ...]  # (check_name, detail)
    limits: dict[str, str]  # limit name -> Decimal-as-string, computed

    @property
    def passed(self) -> bool:
        return self.outcome in (RiskOutcome.PASS, RiskOutcome.REDUCE)
