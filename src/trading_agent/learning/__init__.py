"""Research-only learning. New immutable workflow: records.py and workflow.py.

Legacy APIs remain for fixture compatibility; none may activate a strategy.
"""

from .challenger import (
    ALLOWED_TRANSITIONS,
    STRATEGY_TREND_MOMENTUM,
    Challenger,
    ChallengerError,
    ChallengerStatus,
    load_challengers,
    save_challenger,
)
from .dataset import DatasetProvenance, LearningDataset, build_dataset
from .eval import (
    ChallengerDecision,
    EvaluationReport,
    FoldResult,
    LearningGates,
    evaluate_challenger,
    gates_from_config,
)
from .labels import (
    DEFAULT_HORIZONS,
    DecisionLabel,
    DecisionRecord,
    LearningError,
    mature_label,
    mature_labels,
)
from .memory import Champion, ChampionMemory, Memory, MemoryBank
from .paper import PaperLifecycle, PaperStatus
from .records import DatasetSnapshot, RecordedDecision
from .store import (
    LearningStore,
    LearningStoreError,
    append_jsonl,
    atomic_write_json,
    ensure_dir,
    load_json,
    load_jsonl,
)
from .workflow import FrozenChampion, ResearchProtocol, SearchSpace, run_experiment

__all__ = [
    "DatasetSnapshot",
    "RecordedDecision",
    "FrozenChampion",
    "ResearchProtocol",
    "SearchSpace",
    "run_experiment",
    "STRATEGY_TREND_MOMENTUM",
    "ALLOWED_TRANSITIONS",
    "Challenger",
    "ChallengerError",
    "ChallengerStatus",
    "load_challengers",
    "save_challenger",
    "DatasetProvenance",
    "LearningDataset",
    "build_dataset",
    "ChallengerDecision",
    "EvaluationReport",
    "FoldResult",
    "LearningGates",
    "evaluate_challenger",
    "gates_from_config",
    "DEFAULT_HORIZONS",
    "DecisionLabel",
    "DecisionRecord",
    "LearningError",
    "mature_label",
    "mature_labels",
    "Champion",
    "ChampionMemory",
    "Memory",
    "MemoryBank",
    "PaperLifecycle",
    "PaperStatus",
    "LearningStore",
    "LearningStoreError",
    "append_jsonl",
    "atomic_write_json",
    "ensure_dir",
    "load_json",
    "load_jsonl",
]

__version__ = "0.3.0"
