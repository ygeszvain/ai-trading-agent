"""Decision-level memory and the champion memory bank (plan M4).

Memory is keyed by ``decision_id`` — the stable identifier a decision carries
in the record — never by its position in a feed or a raw prompt string.
Entries hold decision fields plus *mature* outcome fields; entries freeze on
first maturity, after which only ``last_seen`` updates.  A ``MemoryBank`` is
a per-champion set of ``Memory`` blocks (``(challenger, strategy, instrument)
-> Memory``); champion retirement archives the champion's bank, and decay
scales each entry by the exponential schedule.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from hashlib import sha256
from typing import Any, Iterable, Mapping

from .challenger import Challenger, ChallengerStatus
from .labels import DecisionLabel, DecisionRecord, _digest


class MemoryError(ValueError):
    """Raised on invalid memory mutation attempts."""


def entry_from_record(record: DecisionRecord, *, label: DecisionLabel | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "decision_id": record.decision_id,
        "session": record.decision_session,
        "as_of": label.matured_as_of if label is not None else None,
        "action": record.action,
        "target_weight": record.target_weight,
        "model_id": record.model_version,
        "prompt_version": record.strategy_version,
        "label_digest": None,
        "record_digest": _digest(record.to_dict()),
        "horizons": [],
        "realized_return": None,
        "max_drawdown": None,
        "gapped": False,
        "matured": False,
        "matured_as_of": None,
        "last_seen": record.decision_session,
        "decay": Decimal("1"),
    }
    if label is not None:
        entry.update(
            label_digest=label.label_digest,
            horizons=[[h, v] for h, v in sorted(label.horizons.items())],
            realized_return=None,
            max_drawdown=label.max_drawdown,
            gapped=label.gapped,
            matured=label.matured,
            matured_as_of=label.matured_as_of,
            last_seen=label.matured_as_of,
        )
    return entry


class Memory:
    """A set of decision-level memory entries with immutable identity.

    Mutation is append/update via :meth:`upsert`; a matured entry never has
    its outcome fields overwritten (fail-closed freeze), only its
    ``last_seen``/``decay`` bookkeeping.
    """

    def __init__(self, memory_id: str, entries: Mapping[str, dict[str, Any]] | None = None) -> None:
        if not memory_id or "/" in memory_id:
            raise MemoryError(f"invalid memory id: {memory_id!r}")
        self.memory_id = memory_id
        self._by_decision: dict[str, dict[str, Any]] = {}
        for entry in (entries or {}).values():
            self._upsert_raw(entry)

    def _upsert_raw(self, entry: Mapping[str, Any]) -> None:
        decision_id = str(entry["decision_id"])
        existing = self._by_decision.get(decision_id)
        merged = dict(entry)
        if existing is not None:
            if existing["matured"] and label_digests_differ(existing, merged):
                merged.update(
                    label_digest=existing["label_digest"],
                    record_digest=existing["record_digest"],
                    horizons=existing["horizons"],
                    realized_return=existing["realized_return"],
                    max_drawdown=existing["max_drawdown"],
                    gapped=existing["gapped"],
                    matured=existing["matured"],
                    matured_as_of=existing["matured_as_of"],
                )
            merged["decay"] = existing["decay"]
        self._by_decision[decision_id] = merged

    def upsert_record(self, record: DecisionRecord, *, label: DecisionLabel | None = None) -> None:
        entry = entry_from_record(record, label=label)
        self._upsert_raw(entry)

    def upsert_label(self, label: DecisionLabel) -> None:
        entry = entry_from_label(label)
        self._upsert_raw(entry)

    def get(self, decision_id: str) -> dict[str, Any] | None:
        return self._by_decision.get(decision_id)

    def __len__(self) -> int:
        return len(self._by_decision)

    def decay(self, *, half_life: Decimal) -> None:
        if half_life <= 0:
            raise MemoryError("half_life must be positive")
        for entry in self._by_decision.values():
            age = entry["last_seen"] - entry["session"]
            if age > 0:
                factor = Decimal(0.5) ** (age / half_life)
                entry["decay"] = entry["decay"] * factor

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "entries": [self._by_decision[key] for key in sorted(self._by_decision)],
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> Memory:
        entries = {str(entry["decision_id"]): dict(entry) for entry in raw.get("entries", [])}
        return cls(str(raw["memory_id"]), entries)

    def digest(self) -> str:
        return sha256(
            ("memory\x1f" + self.memory_id + "\x1f" + "|".join(sorted(self._by_decision))).encode("utf-8")
        ).hexdigest()


def entry_from_label(label: DecisionLabel) -> dict[str, Any]:
    return {
        "decision_id": label.decision_id,
        "session": label.decision_session,
        "as_of": label.matured_as_of,
        "action": label.action,
        "target_weight": label.target_weight,
        "model_id": None,
        "prompt_version": None,
        "label_digest": label.label_digest,
        "record_digest": None,
        "horizons": [[h, v] for h, v in sorted(label.horizons.items())],
        "realized_return": None,
        "max_drawdown": label.max_drawdown,
        "gapped": label.gapped,
        "matured": label.matured,
        "matured_as_of": label.matured_as_of,
        "last_seen": label.matured_as_of,
        "decay": Decimal("1"),
    }


def label_digests_differ(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    return a.get("label_digest") != b.get("label_digest")


def from_records(
    records: Iterable[DecisionRecord],
    labels: Mapping[str, DecisionLabel] | None = None,
    *,
    memory_id: str,
) -> Memory:
    labels = labels or {}
    memory = Memory(memory_id)
    for record in records:
        memory.upsert_record(record, label=labels.get(record.decision_id))
    for label in labels.values():
        memory.upsert_label(label)
    return memory


@dataclass(frozen=True)
class Champion:
    champion_id: str
    strategy: str
    instrument: str
    status: ChallengerStatus
    rule_digest: str
    promoted_at: date
    promoted_from: str
    retired_at: date | None = None
    retired_reason: str | None = None
    digest: str = ""

    def retire(self, *, at: date, reason: str) -> Champion:
        if self.retired_at is not None:
            raise MemoryError(f"champion {self.champion_id} is already retired")
        return replace(
            self,
            retired_at=at,
            retired_reason=reason,
            digest=sha256(
                (self.champion_id, "retired", at.isoformat(), reason, self.rule_digest).encode()
            ).hexdigest(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "champion_id": self.champion_id,
            "strategy": self.strategy,
            "instrument": self.instrument,
            "status": getattr(self.status, "value", self.status),
            "rule_digest": self.rule_digest,
            "promoted_at": self.promoted_at.isoformat(),
            "promoted_from": self.promoted_from,
            "retired_at": self.retired_at.isoformat() if self.retired_at else None,
            "retired_reason": self.retired_reason,
            "digest": self.digest,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> Champion:
        return cls(
            champion_id=str(raw["champion_id"]),
            strategy=str(raw["strategy"]),
            instrument=str(raw["instrument"]),
            status=ChallengerStatus(raw["status"]),
            rule_digest=str(raw["rule_digest"]),
            promoted_at=date.fromisoformat(str(raw["promoted_at"])),
            promoted_from=str(raw["promoted_from"]),
            retired_at=date.fromisoformat(raw["retired_at"]) if raw.get("retired_at") else None,
            retired_reason=raw.get("retired_reason"),
            digest=str(raw.get("digest", "")),
        )


def champion_memory_id(challenger: Challenger, *, instrument: str) -> str:
    return f"champion:{challenger.strategy}:{instrument}:{challenger.rule_digest[:16]}"


class ChampionMemory:
    """Memory attached to a champion: its champion record plus memory blocks.

    Blocks are keyed by ``instrument``; the champion's bank digests its blocks
    so retirement archives the exact set the champion learned from.
    """

    def __init__(self, champion: Champion, blocks: Mapping[str, Memory] | None = None) -> None:
        self.champion = champion
        self._blocks: dict[str, Memory] = dict(blocks or {})

    def block_for(self, instrument: str) -> Memory:
        key = champion_memory_id(self._pseudo_challenger(), instrument=instrument)
        if key not in self._blocks:
            self._blocks[key] = Memory(key)
        return self._blocks[key]

    def _pseudo_challenger(self) -> Challenger:
        return Challenger(
            challenger_id=self.champion.champion_id,
            strategy=self.champion.strategy,
            rule_digest=self.champion.rule_digest,
            status=self.champion.status,
            instrument=self.champion.instrument,
        )

    def upsert_label(self, instrument: str, label: DecisionLabel) -> None:
        self.block_for(instrument).upsert_label(label)

    def decay(self, *, half_life: Decimal) -> None:
        for block in self._blocks.values():
            block.decay(half_life=half_life)

    def retire(self, *, at: date, reason: str) -> ChampionMemory:
        self.champion = self.champion.retire(at=at, reason=reason)
        return self

    @property
    def digest(self) -> str:
        payload = [self.champion.to_dict()] + [
            (key, block.digest()) for key, block in sorted(self._blocks.items())
        ]
        return sha256(repr(payload).encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "champion": self.champion.to_dict(),
            "blocks": {key: block.to_dict() for key, block in sorted(self._blocks.items())},
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> ChampionMemory:
        blocks = {key: Memory.from_dict(block) for key, block in raw.get("blocks", {}).items()}
        return cls(Champion.from_dict(raw["champion"]), blocks)


class MemoryBank:
    """All champion memory banks; ``((challenger, strategy, instrument) -> ChampionMemory)``."""

    def __init__(self, banks: Iterable[ChampionMemory] = ()) -> None:
        self._by_key: dict[tuple[str, str, str], ChampionMemory] = {}
        for bank in banks:
            self.add(bank)

    def add(self, bank: ChampionMemory) -> None:
        key = (bank.champion.challenger_id, bank.champion.strategy, bank.champion.instrument)
        if key in self._by_key:
            raise MemoryError(f"duplicate memory bank for {key}")
        self._by_key[key] = bank

    def get(self, challenger_id: str, strategy: str, instrument: str) -> ChampionMemory | None:
        return self._by_key.get((challenger_id, strategy, instrument))

    def __len__(self) -> int:
        return len(self._by_key)

    def decay(self, *, half_life: Decimal) -> None:
        for bank in self._by_key.values():
            bank.decay(half_life=half_life)

    def to_dict(self) -> dict[str, Any]:
        return {
            "banks": [
                {
                    "key": list(key),
                    "bank": bank.to_dict(),
                }
                for key, bank in sorted(self._by_key.items())
            ]
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> MemoryBank:
        banks = [
            ChampionMemory.from_dict(entry["bank"]) for entry in raw.get("banks", [])
        ]
        return cls(banks)

    def digest(self) -> str:
        return sha256(
            repr([(key, bank.digest()) for key, bank in sorted(self._by_key.items())]).encode()
        ).hexdigest()


__all__ = [
    "Memory",
    "MemoryBank",
    "MemoryError",
    "Champion",
    "ChampionMemory",
    "champion_memory_id",
    "entry_from_label",
    "entry_from_record",
    "from_records",
]
