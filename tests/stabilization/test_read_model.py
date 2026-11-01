import csv
import io
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select

from tests.auth_helpers import register_cookie
from trading_agent.config.loading import load_config
from trading_agent.db.schema import activity_events, metadata
from trading_agent.engine.pipeline import TradingPipeline
from trading_agent.web.app import build_app
from trading_agent.web.auth import SESSION_COOKIE, AuthStore
from trading_agent.web.review import SECTIONS


def test_scoped_bootstrap_notifications_exports_and_review_are_read_only(
    database, monkeypatch, tmp_path
):
    cfg = load_config("config/simulation.yaml", env={})
    cfg.app.db_url = database
    pipeline = TradingPipeline(cfg)
    result = pipeline.run()
    engine = create_engine(database)
    auth = AuthStore(
        tmp_path / "fixture-web", "stabilization-public-fixture", "fixture-signing-only"
    )
    cookie = register_cookie(engine, auth)
    monkeypatch.setattr("trading_agent.web.app.create_app_engine", lambda *a, **k: engine)
    client = TestClient(build_app(cfg, auth_store=auth), base_url="http://127.0.0.1:8000")
    assert client.get("/api/v1/bootstrap").status_code == 401
    client.cookies.set(SESSION_COOKIE, cookie)

    def forbidden(*a, **k):
        raise AssertionError("read constructed broker/model/owner signer")

    monkeypatch.setattr("trading_agent.execution.mcp_client.McpClient.__init__", forbidden)
    monkeypatch.setattr("trading_agent.research.model_client.LocalModelClient.__init__", forbidden)
    monkeypatch.setattr("trading_agent.owner_runtime.auth.login", forbidden)

    def counts():
        with engine.connect() as conn:
            return [
                conn.execute(select(func.count()).select_from(t)).scalar_one()
                for t in metadata.sorted_tables
            ]

    before = counts()
    boot = client.get("/api/v1/bootstrap").json()
    assert boot["read_only"] and boot["run_id"] == result.run_id
    assert boot["overview"]["payload"]["counts"]["fills"] == 48
    for section in SECTIONS:
        assert client.get("/" + section + "?run_id=" + result.run_id).status_code == 200
        view = client.get("/api/v1/review/" + section + "?run_id=" + result.run_id).json()
        assert not view["payload"]["live_dispatch_allowed"]
        for collection in view["payload"]["collections"].values():
            assert len(collection["rows"]) <= 100
    empty = client.get("/api/v1/events", params={"run_id": result.run_id, "cursor": boot["cursor"]})
    assert empty.status_code == 200 and not empty.json()["events"]
    stream = client.get(
        "/api/v1/stream", params={"run_id": result.run_id, "cursor": boot["cursor"]}
    )
    assert stream.status_code == 200 and "event: committed" in stream.text
    assert (
        client.get(
            "/api/v1/events", params={"run_id": "alien", "cursor": boot["cursor"]}
        ).status_code
        == 409
    )
    assert counts() == before
    with engine.begin() as conn:
        conn.execute(
            activity_events.insert().values(
                event_id="new-fixture",
                cursor=boot["sequence"] + 1,
                run_id=result.run_id,
                account_alias="local-sim",
                mode="simulation",
                ts=datetime.now(UTC),
                origin="operator",
                event_type="=1+1",
                correlation={},
                payload={"token": "fixture-secret", "note": "<script>x</script>"},
            )
        )
    after = client.get(
        "/api/v1/events", params={"run_id": result.run_id, "cursor": boot["cursor"]}
    ).json()
    assert len(after["events"]) == 1 and after["market_freshness_unchanged"]
    assert after["events"][0]["payload"]["token"] == "[REDACTED]"
    export = client.get(
        "/api/v1/exports/activity.csv", params={"run_id": result.run_id, "cursor": boot["cursor"]}
    )
    rows = list(csv.reader(io.StringIO(export.text)))
    assert rows[1][4] == "'=1+1" and "fixture-secret" not in export.text
    assert export.headers["X-Has-More"] == "false"
    # Losing a committed event produces an explicit resnapshot, never an invented gap fill.
    with engine.begin() as conn:
        conn.execute(
            activity_events.insert().values(
                event_id="gap-fixture",
                cursor=boot["sequence"] + 3,
                run_id=result.run_id,
                account_alias="local-sim",
                mode="simulation",
                ts=datetime.now(UTC),
                origin="operator",
                event_type="gap",
                correlation={},
                payload={},
            )
        )
    gap = client.get("/api/v1/events", params={"run_id": result.run_id, "cursor": after["cursor"]})
    assert gap.status_code == 409 and gap.json()["resnapshot_required"]
    assert (
        client.get(
            "/api/v1/exports/activity.csv",
            params={"run_id": result.run_id, "cursor": after["cursor"]},
        ).status_code
        == 403
    )
    engine.dispose()
    pipeline._engine.dispose()
