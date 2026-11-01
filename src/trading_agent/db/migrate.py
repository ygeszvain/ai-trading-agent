"""Migration runner: applies alembic revisions to the local database."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

from ..config.models import TradingConfig
from ..exceptions import TradingAgentError


class MigrationError(TradingAgentError):
    """A database migration failed; startup must not continue on a partial schema."""


def _alembic_config(config: TradingConfig) -> Config:
    root = Path(__file__).resolve().parents[3]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    cfg.set_main_option("sqlalchemy.url", config.app.db_url)
    return cfg


def run_migrations(config: TradingConfig) -> str:
    """Upgrade the database to the latest revision; returns the head revision."""
    try:
        command.upgrade(_alembic_config(config), "head")
    except Exception as error:
        detail = f"{error.__class__.__name__}: {error}"
        raise MigrationError(f"database migration failed: {detail}") from error
    cfg = _alembic_config(config)
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(cfg)
    head = script.get_current_head()
    return head or "head"
