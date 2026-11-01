"""The immutable labelled decision dataset (build plan section 12).

A ``LearningDataset`` is the *only* artifact that may influence what the
strategy does: a provenance-stamped, digest-stamped, snapshot of decisions
and their matured point-in-time labels. It enforces the core separation:

* training views may see every record; held-out (validation/test) views are
  decisions at or after the dataset's ``test_start`` boundary and are never
  mixed with training;
* records whose labels are not fully matured are excluded from any aggregate
  that informs behaviour (owner config: ``learning.require_matured_labels``);
* the dataset digest is part of every challenger and report provenance, so a
  model can be audited against the exact data that shaped it.

The dataset is a snapshot: it is written once and never mutated. Rebuilding
it from the ledger produces a new artifact (new digest, new created stamp).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from ..version import __version__ as CODE_VERSION
from .labels import DecisionLabel, DecisionRecord, _digest, mature_labels


@dataclass(frozen=True)
class DatasetProvenance:
    """Where the dataset came from, exactly (section 12: source, model, prompt, snapshot, code)."""

    source: str  # ledger | backtest | export
    run_ids: tuple[str, ...]
    instruments: tuple[str, ...]
    data_snapshot_ids: tuple[str, ...]
    data_sources: tuple[str, ...]  # e.g. ("synthetic",) or ("yahoo", "fred", "synthetic")
    created_at: str  # ISO-8601, UTC
    code_version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "run_ids": list(self.run_ids),
            "instruments": list(self.instruments),
            "data_snapshot_ids": list(self.data_snapshot_ids),
            "data_sources": list(self.data_sources),
            "created_at": self.created_at,
            "code_version": self.code_version,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> DatasetProvenance:
        return cls(
            source=str(raw["source"]),
            run_ids=tuple(str(r) for r in raw.get("run_ids", [])),
            instruments=tuple(str(i) for i in raw.get("instruments", [])),
            data_snapshot_ids=tuple(str(s) for s in raw.get("data_snapshot_ids", [])),
            data_sources=tuple(str(s) for s in raw.get("data_sources", [])),
            created_at=str(raw["created_at"]),
            code_version=str(raw.get("code_version", CODE_VERSION)),
        )


@dataclass(frozen=True)
class LearningDataset:
    """An immutable snapshot of decisions + matured labels + provenance."""

    dataset_id: str
    records: tuple[DecisionRecord, ...]
    labels: tuple[DecisionLabel, ...]
    horizons: tuple[int, ...]
    test_start: date  # records with decision_session >= test_start are held out
    provenance: DatasetProvenance
    created_at: str
    dataset_digest: str = ""

    def __post_init__(self) -> None:
        if len(self.records) != len(self.labels):
            raise ValueError(
                f"dataset {self.dataset_id}: {len(self.records)} records vs "
                f"{len(self.labels)} labels; a dataset is never partial"
            )
        if not self.labels or any(
            label.decision_id != record.decision_id
            for record, label in zip(self.records, self.labels, strict=True)
        ):
            raise ValueError(f"dataset {self.dataset_id}: records and labels are misaligned")
        if not self.dataset_digest:
            object.__setattr__(self, "dataset_digest", self.compute_digest())

    def compute_digest(self) -> str:
        return _digest(
            {
                "records": [record.to_dict() for record in self.records],
                "labels": [label.to_dict() for label in self.labels],
                "horizons": list(self.horizons),
                "test_start": self.test_start.isoformat(),
                "provenance": self.provenance.to_dict(),
            }
        )

    def is_real_data(self) -> bool:
        """True when any non-synthetic source contributed (promotion requires this)."""
        return any(source != "synthetic" for source in self.provenance.data_sources)

    def training_records(self) -> tuple[tuple[DecisionRecord, DecisionLabel], ...]:
        """Decisions strictly before ``test_start`` (may inform behaviour)."""
        pairs = []
        for record, label in zip(self.records, self.labels, strict=True):
            if record.decision_session < self.test_start:
                pairs.append((record, label))
        return tuple(pairs)

    def held_out_records(self) -> tuple[tuple[DecisionRecord, DecisionLabel], ...]:
        """Decisions at/after ``test_start`` -- evaluation only, never training."""
        pairs = []
        for record, label in zip(self.records, self.labels, strict=True):
            if record.decision_session >= self.test_start:
                pairs.append((record, label))
        return tuple(pairs)

    def matured_pairs(self) -> tuple[tuple[DecisionRecord, DecisionLabel], ...]:
        """All pairs whose labels are fully matured (memory gate)."""
        return tuple(
            (record, label)
            for record, label in zip(self.records, self.labels, strict=True)
            if label.is_fully_matured(self.horizons)
        )

    def session_span(self) -> int:
        """Number of distinct decision sessions in the dataset."""
        return len({record.decision_session for record in self.records})

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "records": [record.to_dict() for record in self.records],
            "labels": [label.to_dict() for label in self.labels],
            "horizons": list(self.horizons),
            "test_start": self.test_start.isoformat(),
            "provenance": self.provenance.to_dict(),
            "created_at": self.created_at,
            "dataset_digest": self.dataset_digest,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> LearningDataset:
        return cls(
            dataset_id=str(raw["dataset_id"]),
            records=tuple(DecisionRecord.from_dict(item) for item in raw["records"]),
            labels=tuple(DecisionLabel.from_dict(item) for item in raw["labels"]),
            horizons=tuple(int(h) for h in raw["horizons"]),
            test_start=date.fromisoformat(str(raw["test_start"])),
            provenance=DatasetProvenance.from_dict(raw["provenance"]),
            created_at=str(raw["created_at"]),
            dataset_digest=str(raw.get("dataset_digest", "")),
        )

    def save(self, store_dir: str | Path) -> Path:
        """Persist the snapshot as an immutable JSON artifact."""
        from .store import atomic_write_json

        return atomic_write_json(
            Path(store_dir).expanduser() / "datasets" / f"{self.dataset_id}.json", self.to_dict()
        )


def build_dataset(
    *,
    dataset_id: str,
    records: Sequence[DecisionRecord],
    series_by_instrument: Mapping[str, Any],
    as_of: date,
    horizons: Sequence[int],
    session_calendar: Sequence[date],
    test_start: date,
    provenance: DatasetProvenance,
    created_at: str | None = None,
) -> LearningDataset:
    """Assemble and label a dataset; the caller stamps provenance explicitly.

    Records are sorted by (decision_session, decision_id) so the digest is
    order-independent for a given content.
    """
    if not records:
        raise ValueError(
            "refusing to build an empty dataset (it would still be a learnable artifact)"
        )
    ordered = sorted(records, key=lambda r: (r.decision_session, r.decision_id))
    labels = mature_labels(
        ordered, series_by_instrument, as_of, horizons, session_calendar=session_calendar
    )
    label_list = tuple(labels[record.decision_id] for record in ordered)
    stamp = created_at or datetime.now(UTC).isoformat()
    dataset = LearningDataset(
        dataset_id=dataset_id,
        records=tuple(ordered),
        labels=label_list,
        horizons=tuple(sorted(set(int(h) for h in horizons))),
        test_start=test_start,
        provenance=provenance,
        created_at=stamp,
    )
    return dataset
