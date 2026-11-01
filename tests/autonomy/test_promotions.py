import json
from datetime import timedelta
from decimal import Decimal

import pytest

from tests.autonomy.test_envelope import system as system
from trading_agent.autonomy.artifacts import ArtifactVault
from trading_agent.autonomy.contracts import ChangeMandate, ChangeProposal, EvidenceRules
from trading_agent.autonomy.fixtures import KEY, NOW
from trading_agent.autonomy.owner_fixture import sign_fixture
from trading_agent.autonomy.promotion import ReviewEvidence, TrialEvidence, activate, prepare_review
from trading_agent.supervised.journal import Denied


def proposal_fixture(s):
    vault = ArtifactVault(s.root / "primary")
    with s.store.transaction() as conn:
        state = s.store.state(conn, KEY)
    artifact = next(a for a in s.champion.artifacts if a.role == "parameters")
    params = json.loads(vault.get(artifact.content_hash))
    params["entry_momentum"] = "0.06"
    from trading_agent.config.models import StrategySettings

    cfg = StrategySettings.model_validate(params)
    new_params = vault.put(cfg.model_dump_json().encode())
    manifest = state.strategy_manifest.changed(strategy_settings_json=cfg.model_dump_json())
    candidate = s.champion.changed(
        champion_id="future-review-only",
        strategy_manifest_hash=manifest.digest(),
        artifacts=tuple(
            a.changed(content_hash=new_params) if a.role == "parameters" else a
            for a in s.champion.artifacts
        ),
    )
    candidate_hash = vault.put(candidate.model_dump_json().encode())
    dataset = vault.put(b'{"kind":"synthetic_fixture_labels"}')
    protocol = vault.put(b'{"kind":"frozen_synthetic_protocol"}')
    trials = tuple(
        TrialEvidence(
            trial_id="trial-" + str(i),
            status="FAILED" if i == 0 else "EVALUATED",
            result_hash=vault.put(
                json.dumps({"trial": i, "status": "FAILED" if i == 0 else "EVALUATED"}).encode()
            ),
        )
        for i in range(2)
    )
    evidence = ReviewEvidence(
        dataset_hash=dataset,
        protocol_hash=protocol,
        registered_trial_ids=tuple(t.trial_id for t in trials),
        all_trials=trials,
        matured_labels=100,
        shadow_session_ids=tuple("shadow-" + str(i) for i in range(30)),
        edge_lower_bound=Decimal(".02"),
        turnover=Decimal(".1"),
        drawdown=Decimal(".01"),
        safety_regressions=0,
    )
    ehash = vault.put(evidence.model_dump_json().encode())
    proposal = ChangeProposal(
        envelope_hash=s.envelope.digest(),
        champion_hash=s.envelope.champion_hash,
        candidate_hash=candidate_hash,
        change_class="PARAMETERS",
        diff=(("entry_momentum", "0.05", "0.06"),),
        dataset_hash=dataset,
        protocol_hash=protocol,
        all_trial_hashes=tuple(t.result_hash for t in trials),
        evidence_hash=ehash,
        matured_labels=100,
        shadow_sessions=30,
        edge_lower_bound=Decimal(".02"),
        turnover=Decimal(".1"),
        drawdown=Decimal(".01"),
        safety_regressions=0,
        failed_trials_preserved=True,
        rollback_target=s.envelope.rollback_target,
    )
    mandate = ChangeMandate(
        envelope_hash=s.envelope.digest(),
        champion_hash=s.envelope.champion_hash,
        permitted_class="PARAMETERS",
        parameter_bounds=(("entry_momentum", Decimal(".04"), Decimal(".07")),),
        evidence=EvidenceRules(
            protocol_hash=protocol,
            dataset_hash=dataset,
            min_matured_labels=50,
            min_shadow_sessions=30,
            min_edge_lower_bound=Decimal(".01"),
            max_turnover=Decimal(".2"),
            max_drawdown=Decimal(".02"),
        ),
        starts_at=NOW,
        expires_at=NOW + timedelta(hours=1),
        rollback_target=s.envelope.rollback_target,
    )
    return vault, proposal, mandate


def test_default_NONE_requires_separate_owner_class_and_never_activates(system):
    s = system
    vault, p, m = proposal_fixture(s)
    blocked = prepare_review(s.store, KEY, p, vault, now=NOW)
    assert blocked["status"] == "BLOCKED_REVIEW" and blocked["active_change_class"] == "NONE"
    reviewed = prepare_review(s.store, KEY, p, vault, now=NOW, mandate_proof=sign_fixture(m))
    assert (
        reviewed["status"] == "REVIEW_READY_NO_ACTIVATION"
        and not reviewed["actual_activation_allowed"]
    )
    assert not reviewed["synthetic_automatic_activation_allowed"]
    with pytest.raises(Denied):
        activate(reviewed)
    with s.store.transaction() as conn:
        assert s.store.envelope(conn, KEY).digest() == s.envelope.digest()
        assert s.store.runtime(conn, KEY).champion_hash == s.envelope.champion_hash


@pytest.mark.parametrize(
    "kind", ["CODE", "RISK", "CAPITAL", "TOOLS", "ASSETS", "PROMPT", "MODEL", "MEMORY"]
)
def test_never_permit_dangerous_change_class_even_with_owner_fixture_mandate(system, kind):
    s = system
    vault, p, m = proposal_fixture(s)
    result = prepare_review(
        s.store, KEY, p.changed(change_class=kind), vault, now=NOW, mandate_proof=sign_fixture(m)
    )
    assert result["status"] == "BLOCKED_REVIEW" and "change_class_forbidden" in result["reasons"]


@pytest.mark.parametrize(
    "change",
    [
        {"shadow_sessions": 29},
        {"matured_labels": 0},
        {"edge_lower_bound": Decimal("-.1")},
        {"failed_trials_preserved": False},
        {"safety_regressions": 1},
        {"rollback_target": "0" * 64},
        {"all_trial_hashes": ("0" * 64,)},
        {"protocol_hash": "0" * 64},
    ],
)
def test_inadequate_or_hidden_evidence_does_not_pass_review(system, change):
    s = system
    vault, p, m = proposal_fixture(s)
    result = prepare_review(
        s.store, KEY, p.changed(**change), vault, now=NOW, mandate_proof=sign_fixture(m)
    )
    assert result["status"] == "BLOCKED_REVIEW"


def test_hidden_candidate_code_change_and_expired_mandate_are_rejected(system):
    s = system
    vault, p, m = proposal_fixture(s)
    candidate = vault.champion(p.candidate_hash)
    altered = candidate.changed(
        artifacts=tuple(
            a.changed(content_hash=vault.put(b"new unapproved execution"))
            if a.role == "code"
            else a
            for a in candidate.artifacts
        )
    )
    p = p.changed(candidate_hash=vault.put(altered.model_dump_json().encode()))
    result = prepare_review(
        s.store, KEY, p, vault, now=NOW, mandate_proof=sign_fixture(m.changed(expires_at=NOW))
    )
    assert result["status"] == "BLOCKED_REVIEW"
    assert "hidden_code_model_prompt_feature_or_quantity_change" in result["reasons"]
