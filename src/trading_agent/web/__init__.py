"""Local website for the trading agent (plan section 18, docs/website.md).

Loopback-only, owner-authenticated, read-only over the persisted ledger.
UI reads, filtering, charts, and exports never invoke model inference or
broker operations and never mutate financial state.
"""

from __future__ import annotations

from .app import build_app, serve
from .auth import (
    SESSION_COOKIE,
    AuthError,
    AuthStore,
    ensure_bootstrap,
    load_store,
    resolve_auth_path,
)

__all__ = [
    "AuthError",
    "AuthStore",
    "SESSION_COOKIE",
    "build_app",
    "ensure_bootstrap",
    "load_store",
    "resolve_auth_path",
    "serve",
]
