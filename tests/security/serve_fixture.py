"""Destructive fixture seed on the dedicated disposable review DB; never an owner DB."""

import os
from pathlib import Path

import uvicorn
from sqlalchemy import create_engine

from tests.security.conftest import REVIEW_URL
from tests.security.test_web_persisted import seed_history
from trading_agent.config.loading import load_config
from trading_agent.db.schema import metadata
from trading_agent.web.app import build_app
from trading_agent.web.auth import AuthStore

if os.environ.get("TRADING_AGENT_REVIEW_DB") != REVIEW_URL:
    raise SystemExit("explicit disposable TRADING_AGENT_REVIEW_DB required")
engine = create_engine(REVIEW_URL)
metadata.create_all(engine)
with engine.begin() as conn:
    for table in reversed(metadata.sorted_tables):
        conn.execute(table.delete())
seed_history(engine)
config = load_config("config/simulation.yaml", env={})
config.app.db_url = REVIEW_URL
config.app.web_port = 8020
store = AuthStore(
    Path(".data/security-review/fixture-auth"),
    "fixture-browser-owner",
    "fixture-browser-signing-secret",
)
app = build_app(config, auth_store=store)
uvicorn.run(app, host="127.0.0.1", port=8020, access_log=False)
