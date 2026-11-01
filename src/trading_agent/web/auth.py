"""Owner authentication for the local website (plan section 18, docs/website.md).

Design rules (all enforced here, never in the templates):

- The owner token lives in a protected local file (``chmod 600``) outside the
  repository. The first ``serve`` bootstraps it without printing it; a shared
  default password is never shipped and bootstrap secrets never enter source
  control.
- Sessions are HMAC-SHA256 signed cookies with a 12 hour expiry. The cookie
  is ``HttpOnly; SameSite=Strict; Path=/``. ``Secure`` is deliberately
  omitted: the site is loopback HTTP only, and the browser would reject a
  Secure cookie on a plain-HTTP origin.
- The Host header must match the configured loopback bind on every request;
  the login POST additionally requires a matching Origin.
- ``web_auth`` / ``web_sessions`` rows are written only on login and
  logout -- never per request -- so no read interaction mutates the database.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config.models import TradingConfig
from ..db.schema import web_auth, web_sessions
from ..exceptions import TradingAgentError
from ..security.files import read_private_json, write_private_json

SESSION_COOKIE = "ta_session"
SESSION_TTL = timedelta(hours=12)
AUTH_FILE_ENV = "TRADING_AGENT_WEB_AUTH_FILE"


class AuthError(TradingAgentError):
    """Authentication failed or the owner token cannot be resolved."""


def default_auth_path() -> Path:
    return Path.home() / ".trading-agent" / "webauth.json"


def resolve_auth_path(env: dict[str, str] | None = None) -> Path:
    data = os.environ if env is None else env
    override = (data.get(AUTH_FILE_ENV) or "").strip()
    return Path(override).expanduser() if override else default_auth_path()


@dataclass(frozen=True)
class AuthStore:
    """The owner token plus the per-installation session signing secret."""

    path: Path
    owner_token: str
    session_secret: str


def ensure_bootstrap(path: Path | None = None) -> tuple[Path, bool]:
    """Create the owner token file if missing; never overwrites an existing one.

    Returns ``(path, created)``.
    """
    target = path if path is not None else resolve_auth_path()
    payload = {
        "token": secrets.token_urlsafe(24),
        "session_secret": secrets.token_urlsafe(32),
    }
    return target, write_private_json(target, payload, replace=False)


def load_store(path: Path | None = None) -> AuthStore:
    target = path if path is not None else resolve_auth_path()
    if not target.exists():
        raise AuthError(f"owner token file missing at {target}; run serve first to bootstrap")
    try:
        payload = read_private_json(target)
        token = payload["token"]
        secret = payload["session_secret"]
        if not isinstance(token, str) or not isinstance(secret, str):
            raise ValueError("private auth fields must be strings")
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise AuthError(f"owner token file {target} is unreadable or malformed") from error
    if not token or not secret:
        raise AuthError(f"owner token file {target} has an empty token or secret")
    return AuthStore(path=target, owner_token=token, session_secret=secret)


def _b64url(data: bytes) -> bytes:
    return base64.urlsafe_b64encode(data).rstrip(b"=")


def _sha256(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def issue_session(store: AuthStore, now: datetime | None = None) -> str:
    """Mint a signed session cookie value for the owner."""
    timestamp = now if now is not None else datetime.now(UTC)
    payload = json.dumps(
        {
            "sub": "owner",
            "sid": secrets.token_urlsafe(16),
            "exp": (timestamp + SESSION_TTL).isoformat(),
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    signature = hmac.new(store.session_secret.encode("utf-8"), payload, hashlib.sha256).digest()
    return f"{_b64url(payload).decode('ascii')}.{_b64url(signature).decode('ascii')}"


def verify_session(store: AuthStore, cookie: str | None, now: datetime | None = None) -> bool:
    """Verify a session cookie: structure, HMAC, subject, and expiry."""
    if not cookie or len(cookie) > 2048 or cookie.count(".") != 1:
        return False
    payload_part, signature_part = cookie.split(".", 1)
    try:
        body = base64.urlsafe_b64decode(
            payload_part.encode("ascii") + b"=" * (-len(payload_part) % 4)
        )
        provided = base64.urlsafe_b64decode(
            signature_part.encode("ascii") + b"=" * (-len(signature_part) % 4)
        )
    except Exception:  # noqa: BLE001 - malformed input is simply unauthenticated
        return False
    expected = hmac.new(store.session_secret.encode("utf-8"), body, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, provided):
        return False
    try:
        document = json.loads(body.decode("utf-8"))
        if not isinstance(document, dict) or set(document) != {"sub", "sid", "exp"}:
            return False
        if not isinstance(document["sid"], str) or not document["sid"]:
            return False
        expires = datetime.fromisoformat(str(document.get("exp")))
    except ValueError:
        return False
    if document.get("sub") != "owner" or expires.tzinfo is None:
        return False
    timestamp = now if now is not None else datetime.now(UTC)
    return expires > timestamp


def expected_origin(config: TradingConfig) -> str:
    host = f"[{config.app.web_host}]" if ":" in config.app.web_host else config.app.web_host
    return f"http://{host}:{config.app.web_port}"


def host_matches(config: TradingConfig, host_header: str | None) -> bool:
    """Host header (hostname part) must equal the configured loopback bind."""
    if host_header is None:
        return False
    return host_header.lower() == expected_origin(config).split("://", 1)[1].lower()


def session_registered(session: Session, cookie: str, *, now: datetime | None = None) -> bool:
    timestamp = now or datetime.now(UTC)
    return (
        session.execute(
            select(web_sessions.c.session_sha256).where(
                web_sessions.c.session_sha256 == _sha256(cookie),
                web_sessions.c.expires_at > timestamp,
            )
        ).first()
        is not None
    )


def record_login(session: Session, store: AuthStore, cookie: str, at: datetime) -> None:
    """Persist the bootstrap token hash and the new session (login only)."""
    existing = session.execute(
        select(web_auth).where(web_auth.c.kind == "bootstrap")
    ).scalar_one_or_none()
    if existing is None:
        session.execute(
            web_auth.insert().values(
                kind="bootstrap", token_sha256=_sha256(store.owner_token), created_at=at
            )
        )
    session.execute(
        web_sessions.insert().values(
            session_sha256=_sha256(cookie),
            created_at=at,
            expires_at=at + SESSION_TTL,
            last_seen_at=at,
        )
    )


def record_logout(session: Session, cookie: str | None) -> None:
    """Forget the session row (logout only)."""
    if not cookie:
        return
    session.execute(web_sessions.delete().where(web_sessions.c.session_sha256 == _sha256(cookie)))
