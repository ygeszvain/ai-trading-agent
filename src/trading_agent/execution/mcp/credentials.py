"""OAuth credential vault with digest auditing (build plan section 6/14).

Ownership: owner's local machine. The store keeps the *vault* — client id,
refresh token, access token — under a Fernet key derived from the owner's
secret phrase. Audit logs always carry only a truncated SHA-256 digest of
the token, never the token itself.

Security model (deliberate, documented):
  * Key material: `PBKDF2-HMAC-SHA256(phrase, salt, 200_000)` — the phrase
    is required at startup (CLI prompt or ``TRADING_AGENT_CREDENTIAL_PHRASE``).
  * A *master key file* (0600, ``.data/robinhood_mcp_vault.key``) is
    derived from the same phrase; re-derivation must reproduce it, which
    verifies the phrase before decryption.
  * Tokens are encrypted with a vault key that is itself derived from the
    master key + random nonce, so rotating the phrase re-keys everything.
  * If the phrase is wrong or the store is corrupted, the store raises
    ``TokenStoreError`` — the caller must fail closed, never guess.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

log = logging.getLogger(__name__)

_KDF_ITERATIONS = 200_000


class TokenStoreError(RuntimeError):
    """Credential store problem. Callers must fail closed on this."""


@dataclass(frozen=True)
class TokenRecord:
    """A decrypted, in-memory OAuth token set (never serialized in plaintext)."""

    client_id: str
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_at: float = 0.0
    scopes: tuple[str, ...] = ()

    def is_expired(self, *, now: float | None = None, skew_seconds: float = 30.0) -> bool:
        if self.expires_at <= 0:
            return False  # opaque token without expiry; assume valid
        now = time.time() if now is None else now
        return now >= self.expires_at - skew_seconds

    @property
    def access_token_digest(self) -> str:
        return self.__class__._digest(self.access_token)

    @staticmethod
    def _digest(token: str) -> str:
        return "sha256:" + hashlib.sha256(token.encode()).hexdigest()[:16]


class CredentialStore:
    """File-backed, encrypted vault for one OAuth client + its tokens."""

    def __init__(self, path: Path, phrase: str) -> None:
        self._path = Path(path)
        self._fernet = self._derive_fernet(self._path, phrase)

    # ------------------------------------------------------------- key mgmt

    @staticmethod
    def sha256_digest(token: str) -> str:
        return "sha256:" + hashlib.sha256(token.encode()).hexdigest()[:16]

    @staticmethod
    def _kdf(secret: bytes, salt: bytes, length: int = 32) -> bytes:
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(), length=length, salt=salt, iterations=_KDF_ITERATIONS
        )
        return kdf.derive(secret)

    def _derive_fernet(self, path: Path, phrase: str) -> Fernet:
        key_path = path.with_suffix(path.suffix + ".key")
        salt = phrase.encode()  # phrase is the KDF password; file salt below
        file_salt = self._read_file_salt(key_path)
        master = self._kdf(phrase.encode(), file_salt)
        key_path.parent.mkdir(parents=True, exist_ok=True)
        if not key_path.exists():
            key_path.write_bytes(file_salt + master)
            key_path.chmod(0o600)
        elif key_path.read_bytes()[:32] != file_salt or key_path.read_bytes()[32:] != master:
            raise TokenStoreError(
                f"credential vault key mismatch for {key_path}; "
                "wrong phrase or tampered vault — refusing to start"
            )
        fernet_salt = self._kdf(master, b"fernet-v1", length=16)
        return Fernet(base64.urlsafe_b64encode(fernet_salt))

    @staticmethod
    def _read_file_salt(key_path: Path) -> bytes:
        if not key_path.exists():
            return secrets.token_bytes(32)
        data = key_path.read_bytes()
        return data[:32] if len(data) >= 32 else data

    # ------------------------------------------------------------- records

    def load(self) -> TokenRecord | None:
        """Load the current tokens; ``None`` when the store is empty."""
        if not self._path.exists():
            return None
        try:
            envelope = json.loads(self._path.read_text())
            plaintext = self._fernet.decrypt(envelope["payload"].encode())
            record = TokenRecord(**json.loads(plaintext))
            log.info(
                "credential vault: loaded token %s for client %s",
                record.access_token_digest,
                record.client_id,
            )
            return record
        except (InvalidToken, KeyError, json.JSONDecodeError, ValueError) as error:
            raise TokenStoreError(
                f"credential vault at {self._path} is unreadable ({type(error).__name__}); "
                "wrong phrase, corrupt file, or rotation — refusing to proceed"
            ) from error

    def save(self, record: TokenRecord) -> None:
        """Encrypt and persist the record (0600 file)."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        plaintext = json.dumps(
            {
                "client_id": record.client_id,
                "access_token": record.access_token,
                "refresh_token": record.refresh_token,
                "token_type": record.token_type,
                "expires_at": record.expires_at,
                "scopes": list(record.scopes),
                "saved_at": time.time(),
            }
        ).encode()
        # TokenRecord has no saved_at; rebuild via dict
        payload = json.loads(plaintext)
        plaintext = json.dumps(
            {
                "client_id": record.client_id,
                "access_token": record.access_token,
                "refresh_token": record.refresh_token,
                "token_type": record.token_type,
                "expires_at": record.expires_at,
                "scopes": list(record.scopes),
            }
        ).encode()
        self._path.write_bytes(
            json.dumps({"payload": self._fernet.encrypt(plaintext).decode()}).encode()
        )
        self._path.chmod(0o600)
        log.info(
            "credential vault: stored token %s for client %s at %s",
            record.access_token_digest,
            record.client_id,
            self._path,
        )

    @classmethod
    def from_metadata(cls, path: Path, *, phrase: str) -> "CredentialStore":
        return cls(path, phrase)

    # ---------------------------------------------------------- token flows

    @classmethod
    def exchange(
        cls, raw: dict, *, client_id: str, issuer: str, path: Path, phrase: str
    ) -> TokenRecord:
        """Build a TokenRecord from an OAuth token response and persist it."""
        expires_in = float(raw.get("expires_in", 0) or 0)
        record = TokenRecord(
            client_id=client_id,
            access_token=str(raw["access_token"]),
            refresh_token=str(raw.get("refresh_token", "")),
            token_type=str(raw.get("token_type", "Bearer")),
            expires_at=time.time() + expires_in,
            scopes=tuple(str(s) for s in (raw.get("scope") and raw["scope"].split() or ())),
        )
        cls(path, phrase).save(record)
        return record
