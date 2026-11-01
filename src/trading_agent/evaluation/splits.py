"""Chronological split planning with purge/embargo enforcement (plan section 15).

Rules:
- Everything is time-ordered. A window may never reference data outside its
  range, and windows never overlap except for the explicit warmup history.
- For every label horizon ``h``, the final ``h`` sessions of the training
  window are *purged*: a label for session ``t`` with horizon ``h`` would
  need closes up to ``t + h``, which may land in the validation/test window.
  Purging removes those straddling labels so no training label can see the
  future window.
- An *embargo* gap of ``embargo_days`` sessions separates train from
  validation, and validation from test, as a belt-and-braces buffer beyond
  the label purge.
- The final ``holdout_days`` window is carved off the end and is evaluated
  exactly once; it never participates in candidate selection.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

from pydantic import BaseModel

from .protocol import SplitSettings

_WINDOW_ORDER = ("train", "validation", "test")


class LeakageError(RuntimeError):
    """Raised when a split plan or transformation violates the chronology."""


@dataclass(frozen=True)
class Split:
    """One named window of sessions (inclusive dates)."""

    name: str  # "train" | "validation" | "test" | "holdout"
    start: date
    end: date
    sessions: list[date] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.sessions)

    def contains(self, session: date) -> bool:
        return bool(self.sessions) and self.sessions[0] <= session <= self.sessions[-1]


@dataclass(frozen=True)
class Fold:
    """One walk-forward fold: its three windows."""

    fold_index: int
    train: Split
    validation: Split
    test: Split


@dataclass(frozen=True)
class SplitPlan:
    """The full plan: a sequence of folds plus the single final holdout."""

    folds: list[Fold]
    holdout: Split | None
    embargo_days: int
    purge_days: int
    warmup_days: int

    def all_sessions(self) -> list[date]:
        seen: set[date] = set()
        ordered: list[date] = []
        for container in [*self.folds, self.holdout]:
            if container is None:
                continue
            splits = (
                (container,)
                if isinstance(container, Split)
                else (container.train, container.validation, container.test)
            )
            for part in splits:
                if part is None:
                    continue
                for session in part.sessions:
                    if session not in seen:
                        seen.add(session)
                        ordered.append(session)
        ordered.sort()
        return ordered

    def digest(self) -> str:
        payload = json.dumps(
            {
                "folds": [
                    {
                        "i": fold.fold_index,
                        "train": (
                            fold.train.start.isoformat(),
                            fold.train.end.isoformat(),
                            len(fold.train),
                        ),
                        "validation": (
                            fold.validation.start.isoformat(),
                            fold.validation.end.isoformat(),
                            len(fold.validation),
                        ),
                        "test": (
                            fold.test.start.isoformat(),
                            fold.test.end.isoformat(),
                            len(fold.test),
                        ),
                    }
                    for fold in self.folds
                ],
                "holdout": None
                if self.holdout is None
                else (
                    self.holdout.start.isoformat(),
                    self.holdout.end.isoformat(),
                    len(self.holdout),
                ),
                "embargo_days": self.embargo_days,
                "purge_days": self.purge_days,
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _window(sessions: list[date], name: str, start_idx: int, count: int) -> Split:
    chunk = sessions[start_idx : start_idx + count]
    if len(chunk) < count:
        raise LeakageError(
            f"not enough sessions for the {name} window (need {count}, have {len(chunk)})"
        )
    return Split(name=name, start=chunk[0], end=chunk[-1], sessions=list(chunk))


def plan_splits(
    sessions: Sequence[date | BaseModel],
    settings: SplitSettings,
    purge_days: int,
) -> SplitPlan:
    """Build the walk-forward plan from the full chronological session list.

    ``sessions`` must be strictly increasing and duplicate-free; anything
    else raises ``LeakageError`` (duplicate timestamps make point-in-time
    semantics ambiguous).
    """
    raw = [s if isinstance(s, date) else s.model_dump() for s in sessions]
    # Accept plain dates; normalize anything else (e.g. close objects) via iso.
    normalized: list[date] = []
    for item in raw:
        if isinstance(item, date):
            normalized.append(item)
        elif isinstance(item, dict) and "close" in item:
            if not isinstance(item["close"], date):
                raise LeakageError("session close timestamp must be a date")
            normalized.append(item["close"])
        else:  # pragma: no cover - defensive
            raise LeakageError(f"unrecognizable session entry: {item!r}")
    if not normalized:
        raise LeakageError("cannot plan splits on an empty session list")
    if normalized != sorted(set(normalized)):
        raise LeakageError("session list must be strictly increasing and duplicate-free")

    total = len(normalized)
    # Warmup history precedes every fold; holdout is carved from the tail.
    available = total - max(0, settings.holdout_days)
    folds: list[Fold] = []
    index = settings.warmup_days
    while (
        index
        + settings.train_days
        + settings.embargo_days
        + settings.validation_days
        + settings.embargo_days
        + settings.test_days
        <= available
    ):
        window = normalized[
            index : index + purge_days + settings.embargo_days + settings.validation_days
        ]
        if len(window) < purge_days + settings.embargo_days + settings.validation_days:
            break
        # Train window = the block's sessions minus the tail purge/embargo.
        kept = window[: -(purge_days + settings.embargo_days)]
        train_purged = Split(
            name="train",
            start=kept[0],
            end=kept[-1],
            sessions=list(kept),
        )
        val_index = index + settings.train_days + settings.embargo_days
        validation = _window(normalized, "validation", val_index, settings.validation_days)
        test = _window(
            normalized,
            "test",
            val_index + settings.validation_days + settings.embargo_days,
            settings.test_days,
        )
        folds.append(Fold(len(folds), train_purged, validation, test))
        index += settings.advance_days

    holdout = None
    if settings.holdout_days and total > settings.holdout_days:
        holdout = _window(
            normalized, "holdout", total - settings.holdout_days, settings.holdout_days
        )
        _assert_disjoint(folds, holdout)

    if not folds:
        raise LeakageError(
            f"history too short for at least one fold "
            f"(have {total} sessions; need warmup {settings.warmup_days} + train "
            f"{settings.train_days}"
            f"+ embargo/val {settings.embargo_days + settings.validation_days} "
            f"+ embargo/test {settings.embargo_days + settings.test_days} + holdout "
            f"{settings.holdout_days})"
        )
    return SplitPlan(
        folds=folds,
        holdout=holdout,
        embargo_days=settings.embargo_days,
        purge_days=purge_days,
        warmup_days=settings.warmup_days,
    )


def _assert_disjoint(folds: list[Fold], holdout: Split | None) -> None:
    if holdout is None:
        return
    for fold in folds:
        for part in (fold.train, fold.validation, fold.test):
            overlap = set(part.sessions) & set(holdout.sessions)
            if overlap:
                raise LeakageError(
                    f"fold {fold.fold_index} {part.name} window overlaps the holdout: "
                    f"{sorted(overlap)[:3]}"
                )


def assert_no_leakage(plan: SplitPlan) -> None:
    """Verify the plan's chronology; raise ``LeakageError`` on any violation.

    Checks: within each fold, train/validation/test are strictly separated
    (embargo gaps); consecutive folds advance in time and their test windows
    never overlap (each test session is scored exactly once); the holdout is
    disjoint from every fold window; every window is internally increasing.
    """
    for fold in plan.folds:
        for part in (fold.train, fold.validation, fold.test):
            if part.sessions != sorted(set(part.sessions)) or not part.sessions:
                raise LeakageError(
                    f"fold {fold.fold_index} {part.name} window is not strictly increasing"
                )
        if fold.train.end >= fold.validation.start:
            raise LeakageError(
                f"fold {fold.fold_index}: train ends {fold.train.end} but validation starts "
                f"{fold.validation.start} (windows must be strictly separated by the embargo)"
            )
        if fold.validation.end >= fold.test.start:
            raise LeakageError(
                f"fold {fold.fold_index}: validation ends {fold.validation.end} but test starts "
                f"{fold.test.start}"
            )
    for earlier, later in zip(plan.folds, plan.folds[1:], strict=False):
        if later.test.start <= earlier.test.end:
            raise LeakageError(
                f"test window of fold {later.fold_index} overlaps fold {earlier.fold_index} "
                f"(each test session must be evaluated exactly once)"
            )
    if plan.holdout is not None:
        _assert_disjoint(plan.folds, plan.holdout)


class TrainOnlyPreprocessor:
    """A minimal fitted transform (scale/center) that may only ever be fit
    on the training window and applied elsewhere.

    This is the unit-testable core of the "preprocessor fit only on train"
    rule: the fitted parameters are a pure function of the train values,
    hashed so a run can prove which parameters it used.
    """

    def __init__(self) -> None:
        self._mean: float | None = None
        self._std: float | None = None

    def fit(self, values: Sequence[float]) -> TrainOnlyPreprocessor:
        if len(values) < 2:
            raise LeakageError("cannot fit the preprocessor on fewer than two train values")
        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
        self._mean = mean
        self._std = max(variance**0.5, 1e-9)
        return self

    def transform(self, values: Sequence[float]) -> list[float]:
        if self._mean is None or self._std is None:
            raise LeakageError("preprocessor is not fitted; fit it on the train window first")
        return [(v - self._mean) / self._std for v in values]

    def fitted_digest(self) -> str:
        if self._mean is None or self._std is None:
            return "unfitted"
        payload = f"{self._mean:.12f}:{self._std:.12f}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
