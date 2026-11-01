"""Tests for the filesystem learning store (atomic, idempotent, path-safe)."""

from trading_agent.learning import LearningError, LearningStore


def challenger_dict() -> dict:
    return {
        "challenger_id": "c1",
        "name": "mom",
        "description": "d",
        "strategy": "trend-momentum",
        "instrument": "SPX",
        "rule": {
            "lookback": 10,
            "entry_momentum": "0.01",
            "exit_momentum": "-0.01",
            "target_weight": "1",
        },
        "origin": "hand",
        "source_dataset_digest": None,
        "protocol_digest": None,
        "status": "shadow",
        "created_at": "2025-01-06T00:00:00+00:00",
        "retired_at": None,
        "retired_reason": None,
    }


def test_challenger_roundtrip_and_listing(tmp_path):
    store = LearningStore(tmp_path)
    store.save_challenger(challenger_dict())
    loaded = store.load_challenger("c1")
    assert loaded["name"] == "mom"
    assert store.load_challenger("missing") is None
    assert [item["challenger_id"] for item in store.list_challengers()] == ["c1"]


def test_evaluation_roundtrip(tmp_path):
    store = LearningStore(tmp_path)
    store.save_evaluation(
        {
            "evaluation_id": "ev1",
            "challenger_id": "c1",
            "instrument": "SPX",
            "created_at": "2025-01-06T00:00:00+00:00",
            "rule_digest": "x" * 64,
            "dataset_digest": None,
            "protocol_digest": None,
            "cost": {"fee_rate": "0.0005", "slippage_rate": "0.001"},
            "fold_size": 60,
            "seed": 0,
            "data_start": None,
            "data_end": None,
            "folds": [],
            "gates": [],
            "gate_reasons": [],
            "gates_passed": False,
            "paper": None,
            "champion": None,
        }
    )
    loaded = store.load_evaluation("ev1")
    assert loaded["challenger_id"] == "c1"
    assert store.load_evaluation("missing") is None


def test_decision_append_and_list(tmp_path):
    store = LearningStore(tmp_path)
    store.append_decision(
        {
            "decision_id": "d1",
            "run_id": "run1",
            "action": "enter",
            "session": "2025-01-06",
            "instrument_id": "SPX",
        }
    )
    store.append_decision(
        {
            "decision_id": "d2",
            "run_id": "run1",
            "action": "exit",
            "session": "2025-01-07",
            "instrument_id": "SPX",
        }
    )
    assert [d["decision_id"] for d in store.decisions()] == ["d1", "d2"]


def test_path_traversal_rejected(tmp_path):
    store = LearningStore(tmp_path)
    try:
        store.save_challenger(challenger_dict() | {"challenger_id": "../evil"})
    except LearningError:
        pass
    else:
        raise AssertionError("expected LearningError for path traversal")
