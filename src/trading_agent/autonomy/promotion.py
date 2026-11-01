"""Prepare bounded change reviews. NONE is the active class; no activation method."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import Field

from ..supervised.contracts import Digest, Identifier, Record
from ..supervised.journal import Denied
from .artifacts import ArtifactVault
from .contracts import ChangeMandate, ChangeProposal, Signed, verify
from .store import Store


class TrialEvidence(Record):
    trial_id: Identifier
    status: Literal["FAILED", "EVALUATED", "BUDGET_EXHAUSTED"]
    result_hash: Digest


class ReviewEvidence(Record):
    source_kind: Literal["synthetic"] = "synthetic"
    dataset_hash: Digest
    protocol_hash: Digest
    registered_trial_ids: tuple[Identifier, ...]
    all_trials: tuple[TrialEvidence, ...]
    matured_labels: int = Field(ge=0)
    shadow_session_ids: tuple[Identifier, ...]
    edge_lower_bound: Decimal
    turnover: Decimal
    drawdown: Decimal
    safety_regressions: int = Field(ge=0)


def prepare_review(
    store: Store,
    key: str,
    proposal: ChangeProposal,
    vault: ArtifactVault,
    *,
    now: datetime,
    mandate_proof: Signed | None = None,
) -> dict[str, Any]:
    reasons = []
    with store.transaction() as conn:
        state = store.state(conn, key)
        envelope = store.envelope(conn, key)
        if (
            proposal.envelope_hash != envelope.digest()
            or proposal.champion_hash != envelope.champion_hash
        ):
            reasons.append("scope_mismatch")
        if proposal.change_class not in {"PARAMETERS", "ALLOCATION"}:
            reasons.append("change_class_forbidden")
        if proposal.rollback_target != envelope.rollback_target:
            reasons.append("rollback_mismatch")
        if not envelope.starts_at <= now < envelope.expires_at:
            reasons.append("expired_envelope")
        mandate = None
        if mandate_proof is None:
            reasons.append("active_class_NONE_separate_owner_mandate_required")
        else:
            try:
                mandate = verify(mandate_proof, ChangeMandate, role="fixture_owner")
            except ValueError:
                reasons.append("invalid_owner_mandate")
        if mandate is not None:
            if (
                mandate.envelope_hash != envelope.digest()
                or mandate.champion_hash != envelope.champion_hash
                or mandate.permitted_class != proposal.change_class
                or not envelope.starts_at
                <= mandate.starts_at
                <= now
                < mandate.expires_at
                <= envelope.expires_at
                or mandate.rollback_target != envelope.rollback_target
            ):
                reasons.append("mandate_scope_class_or_expiry")
            try:
                evidence = ReviewEvidence.model_validate_json(vault.get(proposal.evidence_hash))
                for content_hash in (
                    evidence.dataset_hash,
                    evidence.protocol_hash,
                    *(trial.result_hash for trial in evidence.all_trials),
                ):
                    vault.get(content_hash)
                rules = mandate.evidence
                actual_ids = tuple(t.trial_id for t in evidence.all_trials)
                if (
                    len(set(actual_ids)) != len(actual_ids)
                    or set(actual_ids) != set(evidence.registered_trial_ids)
                    or tuple(t.result_hash for t in evidence.all_trials)
                    != proposal.all_trial_hashes
                    or not proposal.failed_trials_preserved
                ):
                    reasons.append("missing_or_hidden_trials")
                if (
                    evidence.dataset_hash != rules.dataset_hash
                    or proposal.dataset_hash != rules.dataset_hash
                    or evidence.protocol_hash != rules.protocol_hash
                    or proposal.protocol_hash != rules.protocol_hash
                    or evidence.matured_labels != proposal.matured_labels
                    or evidence.matured_labels < rules.min_matured_labels
                    or len(set(evidence.shadow_session_ids)) != len(evidence.shadow_session_ids)
                    or len(evidence.shadow_session_ids) != proposal.shadow_sessions
                    or proposal.shadow_sessions < rules.min_shadow_sessions
                    or evidence.edge_lower_bound != proposal.edge_lower_bound
                    or proposal.edge_lower_bound < rules.min_edge_lower_bound
                    or evidence.turnover != proposal.turnover
                    or proposal.turnover > rules.max_turnover
                    or evidence.drawdown != proposal.drawdown
                    or proposal.drawdown > rules.max_drawdown
                    or evidence.safety_regressions != proposal.safety_regressions
                    or proposal.safety_regressions
                ):
                    reasons.append("inadequate_evidence_or_protocol_drift")
                champion = vault.champion(envelope.champion_hash)
                params = json.loads(
                    vault.get(
                        next(a.content_hash for a in champion.artifacts if a.role == "parameters")
                    )
                )
                candidate = vault.champion(proposal.candidate_hash)
                old_artifacts = {a.role: a.content_hash for a in champion.artifacts}
                new_artifacts = {a.role: a.content_hash for a in candidate.artifacts}
                new_params = json.loads(vault.get(new_artifacts["parameters"]))
                if (
                    any(
                        old_artifacts[role] != new_artifacts[role]
                        for role in old_artifacts
                        if role != "parameters"
                    )
                    or candidate.rule != champion.rule
                    or candidate.quantity != champion.quantity
                    or candidate.model_version != champion.model_version
                    or candidate.prompt_version != champion.prompt_version
                    or candidate.strategy_version != champion.strategy_version
                ):
                    reasons.append("hidden_code_model_prompt_feature_or_quantity_change")
                from ..config.models import StrategySettings

                settings = StrategySettings.model_validate(new_params)
                expected_manifest = state.strategy_manifest.changed(
                    strategy_settings_json=settings.model_dump_json()
                )
                if candidate.strategy_manifest_hash != expected_manifest.digest():
                    reasons.append("candidate_manifest_mismatch")
                actual_diff = {
                    field
                    for field in set(params) | set(new_params)
                    if params.get(field) != new_params.get(field)
                }
                declared = {field for field, _, _ in proposal.diff}
                if proposal.change_class == "PARAMETERS":
                    if actual_diff != declared or candidate.target_weight != champion.target_weight:
                        reasons.append("undeclared_parameter_or_allocation_change")
                    if any(str(new_params.get(field)) != new for field, _, new in proposal.diff):
                        reasons.append("candidate_diff_mismatch")
                else:
                    if actual_diff - {"target_weight"}:
                        reasons.append("hidden_allocation_parameter_change")
                    if Decimal(str(new_params.get("target_weight"))) != candidate.target_weight:
                        reasons.append("allocation_manifest_mismatch")
                if proposal.change_class == "PARAMETERS":
                    bounds = {name: (low, high) for name, low, high in mandate.parameter_bounds}
                    if not bounds:
                        reasons.append("parameter_bounds_absent")
                    for field, old, new in proposal.diff:
                        if (
                            field not in {"lookback_days", "entry_momentum", "exit_momentum"}
                            or field not in bounds
                            or field not in params
                        ):
                            reasons.append("field_outside_bounded_class")
                            continue
                        if (
                            Decimal(str(params[field])) != Decimal(old)
                            or not bounds[field][0] <= Decimal(new) <= bounds[field][1]
                        ):
                            reasons.append("parameter_diff_or_bounds")
                elif proposal.change_class == "ALLOCATION":
                    allowed = {a.instrument for a in envelope.assets}
                    if (
                        not mandate.allocation_assets
                        or not set(mandate.allocation_assets) <= allowed
                    ):
                        reasons.append("allocation_assets_not_approved")
                    weights = []
                    for field, old, new in proposal.diff:
                        if (
                            not field.startswith("allocation.")
                            or field[11:] not in mandate.allocation_assets
                        ):
                            reasons.append("allocation_scope")
                            continue
                        if Decimal(old) != champion.target_weight or not Decimal(0) <= Decimal(
                            new
                        ) <= Decimal(".05"):
                            reasons.append("allocation_bound")
                        if Decimal(new) != candidate.target_weight:
                            reasons.append("allocation_diff_mismatch")
                        weights.append(Decimal(new))
                    if sum(weights, Decimal(0)) > Decimal(".25"):
                        reasons.append("allocation_gross_bound")
            except (ValueError, OSError, ArithmeticError, StopIteration):
                reasons.append("evidence_or_diff_unavailable")
        result = {
            "domain": "M7_MOCK_ONLY",
            "status": "BLOCKED_REVIEW" if reasons else "REVIEW_READY_NO_ACTIVATION",
            "reasons": sorted(set(reasons)),
            "envelope_hash": envelope.digest(),
            "proposal": proposal.model_dump(mode="json"),
            "owner_mandate_hash": mandate.digest() if mandate else None,
            "active_change_class": "NONE",
            "actual_activation_allowed": False,
            "synthetic_automatic_activation_allowed": False,
            "authority": "LIVE_NOT_AUTHORIZED",
            "investment_evidence": "EXTERNAL_VALIDATION_PENDING",
        }
        store.record_change(conn, state, now, "PROMOTION_REVIEW", result)
        return result


def activate(*_args: Any, **_kwargs: Any) -> None:
    raise Denied("automatic_change_class_NONE_no_activation_service")
