"""Migration runner: applies alembic revisions to the local database."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from ..config.models import TradingConfig
from ..exceptions import TradingAgentError
from .engine import create_app_engine
from .schema import metadata


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
        verify_schema(config)
    except MigrationError:
        raise
    except Exception as error:
        detail = error.__class__.__name__
        raise MigrationError(f"database migration failed: {detail}") from error
    cfg = _alembic_config(config)
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(cfg)
    head = script.get_current_head()
    return head or "head"


def verify_schema(config: TradingConfig) -> None:
    """A revision stamp alone cannot certify compatibility with the read model."""
    engine = create_app_engine(config, pool="null")
    try:
        inspector = inspect(engine)
        missing = []
        for name, table in metadata.tables.items():
            if not inspector.has_table(name):
                missing.append(name)
                continue
            columns = {column["name"] for column in inspector.get_columns(name)}
            missing.extend(
                f"{name}.{column.name}" for column in table.columns if column.name not in columns
            )
        if missing:
            raise MigrationError(
                "database schema incompatible; reviewed migration required: " + ", ".join(missing)
            )
    finally:
        engine.dispose()
