"""Only explicitly opted-in, newly created review databases are mutated."""

import os
import uuid

import pytest
from sqlalchemy import create_engine, text

URL = "postgresql+psycopg://review@127.0.0.1:55433/stabilization"


@pytest.fixture
def database():
    if os.environ.get("TRADING_AGENT_STABILIZATION_DB") != URL:
        pytest.skip("dedicated disposable stabilization PostgreSQL URL required")
    name = "stabilization_" + uuid.uuid4().hex
    admin = create_engine(URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text('CREATE DATABASE "' + name + '"'))
    try:
        yield URL.rsplit("/", 1)[0] + "/" + name
    finally:
        with admin.connect() as conn:
            conn.execute(text('DROP DATABASE "' + name + '" WITH (FORCE)'))
        admin.dispose()
