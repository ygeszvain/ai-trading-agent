"""Challenger strategies: fixed, versioned, provenance-stamped candidates.

A challenger is the unit that gets evaluated, promoted, and remembered.
Per the owner's design (decision D6 in this layer), v1 challengers are
*fixed deterministic rules* -- currently the owner's ``MomentumRule`` -- so
that the champion cycle works end to end without a live model. The schema
carries room for model-based challengers (``origin`` records research job,
model, and prompt version) but v1 refuses to *promote* a challenger whose
origin is a model: models propose, deterministic rules decide (the research
layer already treats LLM output as advisory).

Lifecycle (owner plan section 12):

    proposed -> evaluating -> candidate -> shadow -> promoted
               |                 |            |
               +-> rejected <+<--+   rejected |  archived

Every status change is recorded in ``status_history`` with the actor and
the report digest that justified it, so the full trajectory of any
challenger is auditable. The digest covers the rule *and* its provenance,
so two challengers that "look the same" but were shaped by different data
are different challengers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from decimal import Decimal
from typing import Any, Mapping, Sequence

from ..backtest.engine import MomentumRule
from .labels import _digest

class ChallengerStatus:
    """Challenger lifecycle states (immutable transition-enforced)."""

    PROPOSED = "proposed"
    EVALUATING = "evaluating"
    CANDIDATE = "candidate"
    SHADOW = "shadow"
    PROMOTED = "promoted"
    REJECTED = "rejected"
    ARCHIVED = "archived"

ALL_STATUSES: tuple[str, ...] = (
    ChallengerStatus.PROPOSED,
    ChallengerStatus.EVALUATING,
    ChallengerStatus.CANDIDATE,
    ChallengerStatus.SHADOW,
    ChallengerStatus.PROMOTED,
    ChallengerStatus.REJECTED,
    ChallengerStatus.ARCHIVED,
)

#: The only transitions the lifecycle permits.
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    ChallengerStatus.PROPOSED: frozenset({ChallengerStatus.EVALUATING, ChallengerStatus.REJECTED}),
    ChallengerStatus.EVALUATING: frozenset(
        {ChallengerStatus.CANDIDATE, ChallengerStatus.REJECTED, ChallengerStatus.ARCHIVED}
    ),
    ChallengerStatus.CANDIDATE: frozenset(
        {ChallengerStatus.SHADOW, ChallengerStatus.EVALUATING, ChallengerStatus.REJECTED, ChallengerStatus.ARCHIVED}
    ),
    ChallengerStatus.SHADOW: frozenset(
        {ChallengerStatus.PROMOTED, ChallengerStatus.REJECTED, ChallengerStatus.ARCHIVED}
    ),
    ChallengerStatus.PROMOTED: frozenset({ChallengerStatus.ARCHIVED, ChallengerStatus.SHADOW}),
    ChallengerStatus.REJECTED: frozenset({ChallengerStatus.ARCHIVED}),
    ChallengerStatus.ARCHIVED: frozenset(),
}

#: The only strategy families v1 can express as a challenger rule.
STRATEGY_TREND_MOMENTUM = "trend-momentum"

_LOOKBACK_RANGE = (5, 250)
_WEIGHT_MAX = Decimal("1")


class ChallengerError(Exception):
    """Invalid challenger definition or disallowed lifecycle transition."""


@dataclass(frozen=True)
class Challenger:
    """A fixed-rule strategy candidate with full provenance."""

    challenger_id: str
    name: str
    description: str
    strategy: str  # STRATEGY_TREND_MOMENTUM in v1
    lookback: int
    entry_momentum: Decimal
    exit_momentum: Decimal
    target_weight: Decimal
    origin: str  # "hand" | "walk-forward:<report-id>" | "research:<job-id>:<model>:<prompt>"
    source_dataset_digest: str | None
    protocol_digest: str | None
    created_at: str
    status: str = ChallengerStatus.PROPOSED
    status_history: tuple[dict[str, Any], ...] = ()
    challenger_digest: str = ""
    instrument: str = "SPX"

    def __post_init__(self) -> None:
        if self.status not in ALL_STATUSES:
            raise ChallengerError(f"unknown challenger status {self.status!r}")
        self.validate_parameters()
        if not self.challenger_digest:
            object.__setattr__(self, "challenger_digest", self.compute_digest())

    def validate_parameters(self) -> None:
        """Fail clearly on rule parameters that would make evaluation meaningless."""
        low, high = _LOOKBACK_RANGE
        if not low <= self.lookback <= high:
            raise ChallengerError(
                f"lookback {self.lookback} outside the allowed range {low}..{high}"
            )
        if not Decimal(0) < self.target_weight <= _WEIGHT_MAX:
            raise ChallengerError(f"target_weight {self.target_weight} must be in (0, 1]")
        if not self.entry_momentum > self.exit_momentum:
            raise ChallengerError(
                f"entry_momentum {self.entry_momentum} must exceed exit_momentum "
                f"{self.exit_momentum} (hysteresis prevents entry/exit flapping)"
            )
        if not (-Decimal("1") < self.exit_momentum < Decimal("10")):
            raise ChallengerError(f"exit_momentum {self.exit_momentum} is outside sane range")
        if not (-Decimal("1") < self.entry_momentum < Decimal("10")):
            raise ChallengerError(f"entry_momentum {self.entry_momentum} is outside sane range")
        if self.strategy != STRATEGY_TREND_MOMENTUM:
            raise ChallengerError(
                f"unsupported challenger strategy {self.strategy!r} (v1: {STRATEGY_TREND_MOMENTUM})"
            )

    @property
    def rule(self) -> MomentumRule:
        """The owner's strategy rule this challenger evaluates as."""
        return MomentumRule(
            lookback=self.lookback,
            entry_momentum=self.entry_momentum,
            exit_momentum=self.exit_momentum,
            target_weight=self.target_weight,
        )

    @property
    def rule_digest(self) -> str:
        """Digest of the rule parameters (matches ``MomentumRule.digest``)."""
        return self.rule.digest()

    @property
    def is_model_origin(self) -> bool:
        return self.origin.startswith("research:")

    def compute_digest(self) -> str:
        return _digest(
            {
                "name": self.name,
                "strategy": self.strategy,
                "lookback": self.lookback,
                "entry_momentum": str(self.entry_momentum),
                "exit_momentum": str(self.exit_momentum),
                "target_weight": str(self.target_weight),
                "origin": self.origin,
                "source_dataset_digest": self.source_dataset_digest,
                "protocol_digest": self.protocol_digest,
                "created_at": self.created_at,
            }
        )

    def transition(self, new_status: str, *, actor: str, report_digest: str | None = None) -> "Challenger":
        """Return a new challenger in ``new_status``; reject illegal edges."""
        if new_status not in ALL_STATUSES:
            raise ChallengerError(f"unknown status {new_status!r}")
        if new_status not in ALLOWED_TRANSITIONS[self.status]:
            raise ChallengerError(
                f"challenger {self.challenger_id}: {self.status} -> {new_status} is not an allowed transition"
            )
        entry: dict[str, Any] = {
            "from": self.status,
            "to": new_status,
            "actor": actor,
            "at": datetime.now(timezone.utc).isoformat(),
        }
        if report_digest is not None:
            entry["report_digest"] = report_digest
        return Challenger(
            challenger_id=self.challenger_id,
            name=self.name,
            description=self.description,
            strategy=self.strategy,
            lookback=self.lookback,
            entry_momentum=self.entry_momentum,
            exit_momentum=self.exit_momentum,
            target_weight=self.target_weight,
            origin=self.origin,
            source_dataset_digest=self.source_dataset_digest,
            protocol_digest=self.protocol_digest,
            created_at=self.created_at,
            status=new_status,
            status_history=self.status_history + (entry,),
            challenger_digest=self.challenger_digest,
            instrument=self.instrument,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "challenger_id": self.challenger_id,
            "name": self.name,
            "description": self.description,
            "strategy": self.strategy,
            "lookback": self.lookback,
            "entry_momentum": str(self.entry_momentum),
            "exit_momentum": str(self.exit_momentum),
            "target_weight": str(self.target_weight),
            "origin": self.origin,
            "source_dataset_digest": self.source_dataset_digest,
            "protocol_digest": self.protocol_digest,
            "created_at": self.created_at,
            "status": self.status,
            "status_history": [dict(item) for item in self.status_history],
            "challenger_digest": self.challenger_digest,
            "instrument": self.instrument,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> Challenger:
        return cls(
            challenger_id=str(raw["challenger_id"]),
            name=str(raw["name"]),
            description=str(raw.get("description", "")),
            strategy=str(raw["strategy"]),
            lookback=int(raw["lookback"]),
            entry_momentum=Decimal(str(raw["entry_momentum"])),
            exit_momentum=Decimal(str(raw["exit_momentum"])),
            target_weight=Decimal(str(raw["target_weight"])),
            origin=str(raw["origin"]),
            source_dataset_digest=None if raw.get("source_dataset_digest") is None else str(raw["source_dataset_digest"]),
            protocol_digest=None if raw.get("protocol_digest") is None else str(raw["protocol_digest"]),
            created_at=str(raw["created_at"]),
            status=str(raw.get("status", ChallengerStatus.PROPOSED)),
            status_history=tuple(dict(item) for item in raw.get("status_history", [])),
            challenger_digest=str(raw.get("challenger_digest", "")),
            instrument=str(raw.get("instrument", "SPX")),
        )


def load_challengers(store_dir) -> dict[str, Challenger]:
    """Load all challenger artifacts from the learning store."""
    from .store import load_json

    directory = Path(store_dir).expanduser() / "challengers"
    challengers: dict[str, Challenger] = {}
    if directory.exists():
        for path in sorted(directory.glob("*.json")):
            raw = load_json(path, default=None)
            if raw is not None:
                challenger = Challenger.from_dict(raw)
                challengers[challenger.challenger_id] = challenger
    return challengers


def save_challenger(challenger: Challenger, store_dir) -> Path:
    """Persist a challenger artifact (full state; status history included)."""
    from .store import atomic_write_json

    return atomic_write_json(
        Path(store_dir).expanduser() / "challengers" / f"{challenger.challenger_id}.json",
        challenger.to_dict(),
    )
