"""Sealed, content-addressed champion bytes; operational notes are never inputs."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

from .contracts import Champion


class ArtifactVault:
    def __init__(self, root: Path) -> None:
        self.root = root

    def put(self, content: bytes) -> str:
        if len(content) > 1048576:
            raise ValueError("artifact exceeds budget")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        key = hashlib.sha256(content).hexdigest()
        path = self.root / (key + ".blob")
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            if self.get(key) != content:
                raise ValueError("immutable artifact conflict") from None
            return key
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        return key

    def get(self, key: str) -> bytes:
        if len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
            raise ValueError("invalid artifact identity")
        fd = os.open(self.root / (key + ".blob"), os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > 1048576:
                raise ValueError("artifact not bounded regular file")
            content = handle.read(1048577)
        if hashlib.sha256(content).hexdigest() != key:
            raise ValueError("frozen artifact changed")
        return content

    def champion(self, key: str) -> Champion:
        champion = Champion.model_validate_json(self.get(key))
        for artifact in champion.artifacts:
            self.get(artifact.content_hash)
        return champion


def dependency_bytes() -> bytes:
    return (Path(__file__).resolve().parents[3] / "uv.lock").read_bytes()


def execution_code_bytes() -> bytes:
    """Only named repository modules, never generated code or operational memory."""
    import json

    base = Path(__file__).resolve().parents[1]
    names = (
        "autonomy/engine.py",
        "autonomy/contracts.py",
        "autonomy/artifacts.py",
        "autonomy/store.py",
        "autonomy/monitor.py",
        "supervised/executor.py",
        "supervised/contracts.py",
        "supervised/journal.py",
        "supervised/readiness.py",
        "operations/closeout.py",
        "operations/reconciliation.py",
        "operations/email.py",
        "operations/journal.py",
        "operations/monitor.py",
        "operations/readiness.py",
        "risk/engine.py",
        "money.py",
        "config/models.py",
    )
    return json.dumps(
        {name: hashlib.sha256((base / name).read_bytes()).hexdigest() for name in names},
        sort_keys=True,
    ).encode()
