"""File-based persistence for the learning layer.

The owner's application state lives in PostgreSQL; the learning layer keeps
its own read-mostly artifacts as JSON in a local store directory (default
``var/learning``) so it works without a database: challenger registry,
champion registry, memories, dataset snapshots, and an append-only audit
log. Writes are atomic (write to a temp file, then rename) and audit entries
are append-only: a learning artifact is never silently overwritten.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from ..exceptions import TradingAgentError


class LearningStoreError(TradingAgentError):
    """A learning store artifact is missing, unreadable, or corrupt."""


def ensure_dir(path: str | Path) -> Path:
    """Create the directory (and parents) if needed; return it."""
    directory = Path(path).expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def atomic_write_json(path: str | Path, payload: Any) -> Path:
    """Write JSON atomically (temp file + rename); parents are created."""
    target = Path(path).expanduser()
    ensure_dir(target.parent)
    payload_text = json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=target.name + ".", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(payload_text)
        os.replace(tmp_name, target)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return target


def load_json(path: str | Path, *, default: Any = None) -> Any:
    """Load a JSON artifact, or ``default`` when the file does not exist.

    Corrupt JSON is a hard error (classified), never silently replaced.
    """
    target = Path(path).expanduser()
    if not target.exists():
        return default
    try:
        return json.loads(target.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise LearningStoreError(f"cannot read learning artifact {target}: {error}") from error


def append_jsonl(path: str | Path, entry: dict[str, Any]) -> Path:
    """Append one JSON object per line to an append-only audit log."""
    target = Path(path).expanduser()
    ensure_dir(target.parent)
    with open(target, "a") as handle:
        handle.write(json.dumps(entry, sort_keys=True, default=str) + "\n")
    return target


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    """Read an append-only JSONL log; a missing file yields an empty list."""
    target = Path(path).expanduser()
    if not target.exists():
        return []
    entries: list[dict[str, Any]] = []
    for line in target.read_text().splitlines():
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError as error:
            raise LearningStoreError(f"corrupt audit entry in {target}: {error}") from error
    return entries


class LearningStore:
    """File-backed learning store with atomic writes and jsonl appends.

    Layout under ``root``:
    - ``challengers/<id>.json``
    - ``evals/<evaluation_id>.json``
    - ``promotions.json`` (jsonl of audit events)
    - ``decisions/ledger.jsonl`` (decision records)
    - ``labels/<record_digest>.json``
    - ``memory/champion.json``

    All writes are atomic (tmp + ``os.replace``); appends are idempotent.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = ensure_dir(root)
        self.challengers_dir = ensure_dir(self.root / "challengers")
        self.evals_dir = ensure_dir(self.root / "evals")
        self.decisions_dir = ensure_dir(self.root / "decisions")
        self.labels_dir = ensure_dir(self.root / "labels")
        self.memory_dir = ensure_dir(self.root / "memory")
        self.promotions_path = self.root / "promotions.json"

    # -- challengers ----------------------------------------------------
    def challenger_path(self, challenger_id: str) -> Path:
        if not challenger_id or "/" in challenger_id or challenger_id in (".", ".."):
            raise LearningStoreError(f"invalid challenger id: {challenger_id!r}")
        return self.challengers_dir / f"{challenger_id}.json"

    def save_challenger(self, payload: Mapping[str, Any]) -> Path:
        return atomic_write_json(self.challenger_path(str(payload["challenger_id"])), dict(payload))

    def load_challenger(self, challenger_id: str) -> dict[str, Any]:
        return load_json(self.challenger_path(challenger_id))

    def list_challengers(self) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for path in sorted(self.challengers_dir.glob("*.json")):
            data = load_json(path)
            if data is not None:
                entries.append(data)
        return entries

    # -- evaluations ----------------------------------------------------
    def save_evaluation(self, payload: Mapping[str, Any]) -> Path:
        evaluation_id = str(payload["evaluation_id"])
        if "/" in evaluation_id or evaluation_id in (".", ".."):
            raise LearningStoreError(f"invalid evaluation id: {evaluation_id!r}")
        return atomic_write_json(self.evals_dir / f"{evaluation_id}.json", dict(payload))

    def load_evaluation(self, evaluation_id: str) -> dict[str, Any]:
        return load_json(self.evals_dir / f"{evaluation_id}.json")

    # -- promotion audit -------------------------------------------------
    def record_promotion(self, entry: Mapping[str, Any]) -> None:
        append_jsonl(self.promotions_path, dict(entry))

    def promotions(self) -> list[dict[str, Any]]:
        return load_jsonl(self.promotions_path)

    # -- decision ledger / labels -----------------------------------------
    def append_decision(self, entry: Mapping[str, Any]) -> None:
        append_jsonl(self.decisions_dir / "ledger.jsonl", dict(entry))

    def decisions(self) -> list[dict[str, Any]]:
        return load_jsonl(self.decisions_dir / "ledger.jsonl")

    def save_label(self, payload: Mapping[str, Any]) -> Path:
        record_digest = str(payload.get("record_digest") or payload.get("label_digest"))
        if "/" in record_digest or record_digest in (".", ".."):
            raise LearningStoreError(f"invalid record digest: {record_digest!r}")
        return atomic_write_json(self.labels_dir / f"{record_digest}.json", dict(payload))

    def load_label(self, record_digest: str) -> dict[str, Any] | None:
        return load_json(self.labels_dir / f"{record_digest}.json")

    def labels(self) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for path in sorted(self.labels_dir.glob("*.json")):
            data = load_json(path)
            if data is not None:
                entries.append(data)
        return entries

    # -- memory -----------------------------------------------------------
    def memory_path(self) -> Path:
        return self.memory_dir / "champion.json"

    def save_memory(self, payload: Mapping[str, Any]) -> Path:
        return atomic_write_json(self.memory_path(), dict(payload))

    def load_memory(self) -> dict[str, Any] | None:
        return load_json(self.memory_path())
