"""Frozen M7 contracts. Synthetic attestations never establish real authority."""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime
from decimal import Decimal
from typing import Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from ..supervised.contracts import Amount, Digest, Identifier, Positive, Record

MOCK_OWNER_KEY = b"M7-PUBLIC-FIXTURE-OWNER-NOT-A-REAL-CREDENTIAL"
MOCK_MONITOR_KEY = b"M7-PUBLIC-FIXTURE-MONITOR-NOT-A-REAL-CREDENTIAL"


class Signed(Record):
    role: Literal["fixture_owner", "fixture_monitor"]
    payload_json: str = Field(max_length=40000)
    signature: Digest


def verify[T: Record](signed: Signed, kind: type[T], *, role: str) -> T:
    key = MOCK_OWNER_KEY if role == "fixture_owner" else MOCK_MONITOR_KEY
    if signed.role != role or not hmac.compare_digest(
        signed.signature, hmac.new(key, signed.payload_json.encode(), hashlib.sha256).hexdigest()
    ):
        raise ValueError("invalid synthetic role attestation")
    return kind.model_validate_json(signed.payload_json)


class Asset(Record):
    instrument: Identifier
    asset_class: Literal["unleveraged_etf"] = "unleveraged_etf"
    short: Literal[False] = False
    leverage: Literal[False] = False


class Session(Record):
    session_id: Identifier
    opens_at: AwareDatetime
    closes_at: AwareDatetime

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.opens_at >= self.closes_at:
            raise ValueError("invalid synthetic session")
        return self


class Artifact(Record):
    role: Literal[
        "code", "dependencies", "parameters", "features", "model", "prompt", "memory_policy"
    ]
    content_hash: Digest


class Champion(Record):
    domain: Literal["M7_MOCK_ONLY"] = "M7_MOCK_ONLY"
    champion_id: Identifier
    strategy_version: Identifier
    model_version: Identifier
    prompt_version: Identifier
    strategy_manifest_hash: Digest
    artifacts: tuple[Artifact, ...] = Field(min_length=7, max_length=7)
    rule: Literal["fixture_flat_entry_held_exit_v1"] = "fixture_flat_entry_held_exit_v1"
    quantity: Positive = Decimal(2)
    target_weight: Amount = Decimal("0.01")

    @model_validator(mode="after")
    def roles(self) -> Self:
        if (
            len({a.role for a in self.artifacts}) != 7
            or self.quantity != self.quantity.to_integral_value()
            or self.target_weight > 1
        ):
            raise ValueError("manifest roles/quantity/target invalid")
        return self


class Monitoring(Record):
    monitor_id: Identifier
    independent_process_required: Literal[True] = True
    max_heartbeat_age_seconds: int = Field(default=5, ge=1, le=10)
    escalation_channel: Literal["LOCAL_REVIEW_QUEUE"] = "LOCAL_REVIEW_QUEUE"
    operator: Literal["fixture-human"] = "fixture-human"
    acknowledgement_required: Literal[True] = True


class Envelope(Record):
    domain: Literal["M7_MOCK_ONLY"] = "M7_MOCK_ONLY"
    version: Literal["1"] = "1"
    envelope_id: Identifier
    owner: Literal["fixture-owner"] = "fixture-owner"
    mode: Literal["bounded_autonomous_live"] = "bounded_autonomous_live"
    account_key: Digest
    account_alias: Literal["m7-fixture"] = "m7-fixture"
    run_id: Identifier
    capital: Positive
    assets: tuple[Asset, ...] = Field(min_length=1, max_length=1)
    champion_hash: Digest
    configuration_hash: Digest
    risk_policy_hash: Digest
    database_schema_hash: Digest
    tool_schema_hash: Digest
    permissions_hash: Digest
    order_types: tuple[Literal["limit"], ...] = ("limit",)
    time_in_force: tuple[Literal["day"], ...] = ("day",)
    sessions: tuple[Session, ...] = Field(min_length=1, max_length=30)
    overnight_policy: Literal["FORBID", "EXPLICITLY_ALLOWED"] = "FORBID"
    monitoring: Monitoring
    starts_at: AwareDatetime
    expires_at: AwareDatetime
    protective_actions: tuple[Literal["cancel_entries"], ...] = ("cancel_entries",)
    protective_expires_at: AwareDatetime
    rollback_target: Digest
    permitted_automatic_change_class: Literal["NONE"] = "NONE"
    automatic_renewal: Literal[False] = False
    automatic_restart_resume: Literal[False] = False
    real_authorization: Literal[False] = False

    @model_validator(mode="after")
    def bounded(self) -> Self:
        if not self.starts_at < self.expires_at <= self.protective_expires_at:
            raise ValueError("authorization/protection interval invalid")
        if self.rollback_target != self.champion_hash or len(
            {a.instrument for a in self.assets}
        ) != len(self.assets):
            raise ValueError("exact rollback and unique approved assets required")
        if any(not a.instrument.startswith("MOCK_") for a in self.assets):
            raise ValueError("only fictional instruments may appear in a synthetic envelope")
        if any(s.opens_at < self.starts_at or s.closes_at > self.expires_at for s in self.sessions):
            raise ValueError("session outside envelope")
        ordered = sorted(self.sessions, key=lambda s: s.opens_at)
        if len({s.session_id for s in ordered}) != len(ordered) or any(
            a.closes_at > b.opens_at for a, b in zip(ordered, ordered[1:], strict=False)
        ):
            raise ValueError("duplicate or overlapping sessions")
        return self

    def session_at(self, at: datetime) -> Session | None:
        return next((s for s in self.sessions if s.opens_at <= at < s.closes_at), None)


class Runtime(Record):
    envelope_hash: Digest
    champion_hash: Digest
    artifact_set: Literal["primary", "backup"] = "primary"
    observed_schema_hash: Digest
    observed_permissions_hash: Digest
    authorized_generation: int | None = Field(default=None, ge=1)
    session_id: Identifier | None = None
    open_incidents: tuple[Digest, ...] = ()
    monitor_sequence: int = Field(default=0, ge=0)
    change_sequence: int = Field(default=0, ge=0)


class Heartbeat(Record):
    domain: Literal["M7_MOCK_ONLY"] = "M7_MOCK_ONLY"
    monitor_id: Identifier
    account_key: Digest
    envelope_hash: Digest
    champion_hash: Digest
    schema_hash: Digest
    permissions_hash: Digest
    executor_generation: int = Field(ge=0)
    observed_at: AwareDatetime
    healthy: bool
    process_id: int = Field(gt=0)
    sequence: int = Field(gt=0)
    issues: tuple[Identifier, ...] = ()


class OwnerResume(Record):
    domain: Literal["M7_MOCK_ONLY"] = "M7_MOCK_ONLY"
    account_key: Digest
    envelope_hash: Digest
    generation: int = Field(ge=1)
    state_revision: int = Field(ge=0)
    incident_cursor: int = Field(ge=0)
    issued_at: AwareDatetime
    expires_at: AwareDatetime


class OwnerAcknowledgement(Record):
    domain: Literal["M7_MOCK_ONLY"] = "M7_MOCK_ONLY"
    account_key: Digest
    envelope_hash: Digest
    incident_hash: Digest
    issued_at: AwareDatetime
    expires_at: AwareDatetime


class Rollback(Record):
    domain: Literal["M7_MOCK_ONLY"] = "M7_MOCK_ONLY"
    account_key: Digest
    envelope_hash: Digest
    target_champion_hash: Digest
    artifact_set: Literal["backup"] = "backup"
    issued_at: AwareDatetime
    expires_at: AwareDatetime


class EvidenceRules(Record):
    protocol_hash: Digest
    dataset_hash: Digest
    min_matured_labels: int = Field(ge=1)
    min_shadow_sessions: int = Field(ge=30)
    min_edge_lower_bound: Decimal = Field(gt=0)
    max_turnover: Amount
    max_drawdown: Amount
    max_changes: int = Field(default=1, ge=1, le=3)


class ChangeMandate(Record):
    """Future owner review of a narrow class; never executable activation in this build."""

    domain: Literal["M7_MOCK_ONLY"] = "M7_MOCK_ONLY"
    envelope_hash: Digest
    champion_hash: Digest
    permitted_class: Literal["PARAMETERS", "ALLOCATION"]
    parameter_bounds: tuple[tuple[Identifier, Decimal, Decimal], ...] = ()
    allocation_assets: tuple[Identifier, ...] = ()
    evidence: EvidenceRules
    starts_at: AwareDatetime
    expires_at: AwareDatetime
    rollback_target: Digest


class ChangeProposal(Record):
    domain: Literal["M7_MOCK_ONLY"] = "M7_MOCK_ONLY"
    envelope_hash: Digest
    champion_hash: Digest
    candidate_hash: Digest
    change_class: Literal[
        "PARAMETERS",
        "ALLOCATION",
        "CODE",
        "RISK",
        "CAPITAL",
        "TOOLS",
        "ASSETS",
        "PROMPT",
        "MODEL",
        "MEMORY",
    ]
    diff: tuple[tuple[Identifier, str, str], ...] = Field(min_length=1, max_length=12)
    dataset_hash: Digest
    protocol_hash: Digest
    all_trial_hashes: tuple[Digest, ...] = Field(min_length=1)
    evidence_hash: Digest
    matured_labels: int = Field(ge=0)
    shadow_sessions: int = Field(ge=0)
    edge_lower_bound: Decimal
    turnover: Amount
    drawdown: Amount
    safety_regressions: int = Field(ge=0)
    failed_trials_preserved: bool
    rollback_target: Digest


class OwnerRevocation(Record):
    domain: Literal["M7_MOCK_ONLY"] = "M7_MOCK_ONLY"
    account_key: Digest
    envelope_hash: Digest
    issued_at: AwareDatetime
    expires_at: AwareDatetime
