"""Engine and session construction for the application database."""

from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from ..config.models import TradingConfig
from ..exceptions import TradingAgentError


class DatabaseUnavailable(TradingAgentError):
    """The local database cannot be reached; fail clearly, never improvise."""


def create_app_engine(config: TradingConfig, *, pool: str = "default") -> Engine:
    """Create an engine for the configured loopback database.

    Raises DatabaseUnavailable (classified, no credentials in the message)
    when the server cannot be reached.
    """
    try:
        poolclass = NullPool if pool == "null" else None
        engine = create_engine(config.app.db_url, poolclass=poolclass)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return engine
    except Exception as error:  # SQLAlchemy wraps driver errors variously
        raise DatabaseUnavailable(
            f"cannot reach the local database at host "
            f"{config.app.db_url.split('@')[-1].split('/')[0]}: {error.__class__.__name__}. "
            "Start it with: docker compose up -d"
        ) from error


def open_session(engine: Engine) -> Session:
    """A plain transactional session; the caller commits or rolls back."""
    return Session(engine, expire_on_commit=False)
