"""Unsigned M7 owner review worksheet, not an activation input."""

from typing import Any

from ..supervised.package import unsigned_package as m6_package


def unsigned_package() -> dict[str, Any]:
    package = m6_package()
    package.update(
        schema_version="M7-review-1",
        proposed_mode="bounded_autonomous_live",
        real_authorization=None,
        per_intent_approval_required="Synthetic envelope only; broker approvals preserved",
        automatic_change_class="NONE",
        automatic_renewal=False,
        automatic_resume=False,
        frozen_champion=None,
        authorization_envelope=None,
        independent_monitor_attestation=None,
        escalation_delivery_and_acknowledgement_evidence=None,
        rollback_artifact_verification=None,
        software_evidence="M7 offline simulation only; see bounded_autonomy_readiness.md",
        activation_prerequisites=[
            "Resolve earlier schema, recovery and economic failures",
            "Owner-signed exact expiring envelope",
            "Verified broker account, schemas, approval and revocation behavior",
            "Separated OS privileges and protected secrets",
            "Independent monitor/stop, alert delivery and explicit resume drills",
            "Prospective operational and investment evidence",
        ],
    )
    return package
