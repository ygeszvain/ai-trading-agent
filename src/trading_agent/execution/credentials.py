"""Owner-managed credential store for the broker gateway token.

The MCP access token is created by the owner in their own browser session
with the broker (agent.robinhood.com) and pasted into the CLI during
``trading-agent broker setup``. It then lives in exactly one file: a JSON
document with 0600 permissions inside a 0700 directory.

Security invariants (build plan sections 6 and 20):
  * The token never appears in the database, logs, configuration, the
    website, or any exception message. Only a masked form is rendered.
  * The file is the single source of truth; nothing else may persist it.
  * Fail-closed: an unreadable store means "no token", never "unknown".
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from ..contracts.broker import BrokerError
from ..security.files import read_private_json, write_private_json


class CredentialError(BrokerError):
    """The credential store is missing or corrupt. Treated as 'no token'."""


class TokenStore:
    """File-backed store for a single bearer token."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path).expanduser()

    @property
    def path(self) -> Path:
        return self._path

    def exists(self) -> bool:
        return self._path.is_file()

    def save(self, token: str, *, note: str = "") -> None:
        """Write the token atomically with strict permissions.

        Creates the parent directory at 0700 and the file at 0600. The
        token is validated (non-empty, control characters rejected) but
        never transformed or logged.
        """
        token = token.strip()
        if not token:
            raise CredentialError("token is empty")
        if any(ord(ch) < 32 for ch in token):
            raise CredentialError("token contains control characters")
        self._path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        payload = {
            "scheme": "bearer",
            "token": token,
            "created_at": datetime.now(UTC).isoformat(),
            "note": note,
        }
        try:
            write_private_json(self._path, payload, replace=True)
        except (OSError, ValueError):
            raise CredentialError("credential store write failed") from None

    def load(self) -> str | None:
        """Return the token, or None when no usable store exists."""
        if not self.exists():
            return None
        try:
            payload = read_private_json(self._path)
            token = payload.get("token")
            if not isinstance(token, str) or not token or any(ord(ch) < 32 for ch in token):
                raise ValueError("credential value invalid")
        except (OSError, ValueError, TypeError) as error:
            raise CredentialError(
                f"credential store unreadable at {self._path}; treated as 'no token' (fail-closed)"
            ) from error
        return token or None

    def load_meta(self) -> dict:
        """Metadata only (never the token) for status displays."""
        if not self.exists():
            return {"present": False}
        try:
            payload = read_private_json(self._path)
        except (OSError, ValueError, TypeError):
            return {"present": False, "readable": False}
        return {
            "present": True,
            "readable": True,
            "created_at": payload.get("created_at"),
            "note": "[local private metadata]",
            "token_masked": self.mask(str(payload.get("token", ""))),
        }

    @staticmethod
    def mask(token: str) -> str:
        """A display-safe representation: ends only, never the value."""
        token = token.strip()
        if len(token) <= 8:
            return "\u2022" * 8
        return "[REDACTED]"

    @staticmethod
    def redact(text: str, token: str) -> str:
        """Remove any accidental token occurrence from server-derived text."""
        if token and token in text:
            return text.replace(token, "***")
        return text
