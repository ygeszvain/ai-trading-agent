"""Authentication-only SQLite fixture; production financial persistence remains PostgreSQL."""

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from trading_agent.db.schema import web_auth, web_sessions
from trading_agent.web import auth


def auth_only_engine():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    web_auth.create(engine)
    web_sessions.create(engine)
    return engine


def register_cookie(engine, store):
    cookie = auth.issue_session(store)
    with Session(engine) as session:
        auth.record_login(session, store, cookie, datetime.now(UTC))
        session.commit()
    return cookie
