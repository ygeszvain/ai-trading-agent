import pytest
from sqlalchemy import create_engine

from trading_agent.db.schema import OPS_TABLES, metadata


@pytest.fixture
def ops_engine(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "operations.sqlite"))
    metadata.create_all(engine, tables=list(OPS_TABLES))
    yield engine
    engine.dispose()
