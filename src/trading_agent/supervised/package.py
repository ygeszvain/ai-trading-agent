"""Unsigned owner decision worksheet. It is not loadable as an authorization."""

from __future__ import annotations

from typing import Any


def unsigned_package() -> dict[str, Any]:
    return {
        "schema_version": "M6-draft-1",
        "status": "UNSIGNED_BLOCKED",
        "authority": "LIVE_NOT_AUTHORIZED",
        "requested_capital_ceiling_usd": "1000",
        "runtime_approved_capital_usd": "0",
        "request_source": "Build plan section 24: owner request, not approval or funding",
        "owner_identity": None,
        "owner_signature": None,
        "authorization_id": None,
        "proposed_mode": "supervised_live",
        "owner_selected_mode": None,
        "dedicated_account_alias": None,
        "verified_account_fingerprint": None,
        "account_eligibility": None,
        "approved_capital_usd": None,
        "approved_universe": None,
        "instrument_eligibility_evidence": None,
        "frozen_strategy_manifest": None,
        "risk_policy_digest": None,
        "overnight_exposure_policy": None,
        "limits": {
            name: None
            for name in (
                "order_size",
                "position_size",
                "gross_exposure",
                "pending_exposure",
                "minimum_cash",
                "turnover",
                "daily_loss_pause",
                "cash_flow_adjusted_drawdown_pause",
                "order_count",
                "quote_age",
                "state_age",
                "clock_skew",
                "participation",
                "working_order_age",
            )
        },
        "starts_at": None,
        "expires_at": None,
        "pilot_observation_period_and_minimum_decisions": None,
        "monitoring_operator_and_channel": None,
        "independent_stop_and_acknowledgement_evidence": None,
        "broker_approval_setting_and_behavior": None,
        "broker_idempotency_semantics": "UNATTESTED; local deduplication only",
        "exclusive_executor_identity": None,
        "protected_runtime_secret_injection": None,
        "startup_reconciliation_evidence": None,
        "explicit_resume_authorization": None,
        "recovery_backup_restore_and_broker_revocation_evidence": None,
        "software_evidence": "See supervised-readiness tests; "
        "fixtures cannot certify deployed readiness",
        "integration_evidence": "EXTERNAL_VALIDATION_PENDING",
        "investment_evidence": "EXTERNAL_VALIDATION_PENDING",
        "blocking_dependencies": [
            "Prompt 10 migration/schema FAIL",
            "prior pipeline/accounting/recovery gaps",
            "three preserved economic-evaluation failures",
            "M4 account-scoped gateway/OAuth quarantined",
            "M5 prospective record incomplete",
            "independent monitoring and OS privilege separation not deployed",
        ],
        "per_intent_approval_required": True,
        "automatic_resume": False,
        "live_dispatch_implemented": False,
    }
