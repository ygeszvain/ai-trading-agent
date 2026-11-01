from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Boolean, Date, DateTime, Numeric, func, select
from sqlalchemy.orm import Session

from tests.security.conftest import NOW, seed_run
from trading_agent.db import schema
from trading_agent.web import auth
from trading_agent.web.app import build_app


def required(table, **values):
    """Populate synthetic required columns; override all fields relevant to a scenario."""
    result = {}
    for column in table.columns:
        if column.name in values or column.nullable or column.server_default is not None:
            continue
        if isinstance(column.type, DateTime):
            result[column.name] = NOW
        elif isinstance(column.type, Date):
            result[column.name] = NOW.date()
        elif isinstance(column.type, Numeric):
            result[column.name] = Decimal(0)
        elif isinstance(column.type, Boolean):
            result[column.name] = True
        elif column.type.__class__.__name__ == "JSONB":
            result[column.name] = {}
        else:
            result[column.name] = "fixture"
    return result | values


def seed_history(engine):
    with engine.begin() as conn:
        seed_run(conn)
        seed_run(conn, "alien-run", alias="alien-account", mode="simulation")
        seed_run(conn, "paper-run", alias="local-sim", mode="paper")
        for symbol in ("TEST_A", "TEST_B"):
            conn.execute(
                schema.instruments.insert().values(
                    required(
                        schema.instruments,
                        run_id="review-run",
                        instrument_id=symbol,
                        symbol=symbol,
                        asset_class="synthetic-equity",
                        price_decimals=2,
                        quantity_precision=0,
                        notes=[],
                    )
                )
            )
        for index, symbol in enumerate(("TEST_A", "TEST_A", "TEST_B")):
            conn.execute(
                schema.market_bars.insert().values(
                    required(
                        schema.market_bars,
                        run_id="review-run",
                        instrument_id=symbol,
                        ts=NOW + timedelta(days=index),
                        open=100,
                        high=101,
                        low=99,
                        close=100,
                        volume=10000,
                        source_id="synthetic",
                        quality="valid",
                        exchange_time=NOW + timedelta(days=index),
                    )
                )
            )
        conn.execute(
            schema.decisions.insert().values(
                required(
                    schema.decisions,
                    decision_id="decision-good",
                    run_id="review-run",
                    account_alias="local-sim",
                    mode="simulation",
                    instrument_id="TEST_A",
                    action="HOLD",
                    rationale="<script>fixture-injection</script>",
                    expires_at=NOW + timedelta(minutes=1),
                )
            )
        )
        conn.execute(
            schema.order_intents.insert().values(
                required(
                    schema.order_intents,
                    intent_id="intent-good",
                    run_id="review-run",
                    decision_id="decision-good",
                    account_alias="local-sim",
                    instrument_id="TEST_A",
                    side="buy",
                    quantity=10,
                    limit_price=100,
                    client_order_id="client-good",
                    time_in_force="day",
                )
            )
        )
        conn.execute(
            schema.broker_orders.insert().values(
                required(
                    schema.broker_orders,
                    order_id="order-good",
                    run_id="review-run",
                    intent_id="intent-good",
                    client_order_id="client-good",
                    account_alias="local-sim",
                    instrument_id="TEST_A",
                    side="buy",
                    quantity=10,
                    limit_price=100,
                    status="unknown",
                    raw_status="ambiguous-outcome",
                    filled_quantity=4,
                )
            )
        )
        for index in (1, 2):
            conn.execute(
                schema.fills.insert().values(
                    required(
                        schema.fills,
                        fill_id=f"partial-{index}",
                        run_id="review-run",
                        order_id="order-good",
                        instrument_id="TEST_A",
                        side="buy",
                        quantity=2,
                        price=100,
                        fee=Decimal("0.1"),
                        raw_fill_id=f"raw-{index}",
                        source="synthetic",
                    )
                )
            )
        conn.execute(
            schema.reservations.insert().values(
                required(
                    schema.reservations,
                    reservation_id="reserved",
                    run_id="review-run",
                    kind="cash",
                    order_id="order-good",
                    intent_id="intent-good",
                    instrument_id="TEST_A",
                    amount=600,
                    status="active",
                )
            )
        )
        conn.execute(
            schema.portfolio_snapshots.insert().values(
                required(
                    schema.portfolio_snapshots,
                    run_id="review-run",
                    portfolio_key="strategy",
                    ts=NOW + timedelta(days=2),
                    equity=100000,
                    cash=Decimal("123456789.12345678"),
                    gross_exposure=400,
                    reconciliation_status="needs-review",
                    positions=[
                        {
                            "instrument_id": "TEST_A",
                            "quantity": "4",
                            "average_cost": "100.05",
                            "mark": None,
                            "mark_as_of": None,
                            "mark_stale": True,
                        }
                    ],
                )
            )
        )
        for index, kind in enumerate(
            ("decision_hold", "risk_rejected", "cancel_requested", "fill_corrected"), 1
        ):
            conn.execute(
                schema.activity_events.insert().values(
                    required(
                        schema.activity_events,
                        event_id=f"activity-{index}",
                        cursor=index,
                        run_id="review-run",
                        account_alias="local-sim",
                        mode="simulation",
                        origin="fixture",
                        event_type=kind,
                        correlation={
                            "instrument": "TEST_A",
                            "decision": "decision-good",
                            "order": "order-good",
                        },
                        payload={"note": '<img src=x onerror="fixture-injection">'},
                        corrected_by="activity-4" if index == 1 else None,
                    )
                )
            )


@pytest.fixture
def web(review_engine, review_config, monkeypatch, tmp_path):
    seed_history(review_engine)
    monkeypatch.setattr(
        "trading_agent.web.app.create_app_engine", lambda *args, **kwargs: review_engine
    )
    store = auth.AuthStore(
        path=tmp_path / "fixture-auth",
        owner_token="fixture-owner-token",
        session_secret="fixture-owner-session-secret",
    )
    app = build_app(review_config, auth_store=store)
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    return client, store, review_engine, app


def login(client, store):
    response = client.post(
        "/auth/login",
        data={"token": store.owner_token},
        headers={"Origin": "http://127.0.0.1:8000"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    return client.cookies.get(auth.SESSION_COOKIE)


def test_login_origin_logout_revocation_expiry_and_host(web):
    client, store, engine, app = web
    assert client.get("/api/v1/overview").status_code == 401
    assert client.post("/auth/login", data={"token": store.owner_token}).status_code == 403
    assert (
        client.post(
            "/auth/login",
            data={"token": store.owner_token},
            headers={"Origin": "https://unapproved.invalid"},
        ).status_code
        == 403
    )
    cookie = login(client, store)
    assert client.get("/api/v1/overview").status_code == 200
    assert client.get("/api/v1/overview", headers={"host": "127.0.0.1:9999"}).status_code == 403
    assert client.get("/auth/logout").status_code == 405
    assert client.post("/auth/logout").status_code == 403
    assert (
        client.post(
            "/auth/logout", headers={"Origin": "http://127.0.0.1:8000"}, follow_redirects=False
        ).status_code
        == 302
    )
    client.cookies.set(auth.SESSION_COOKIE, cookie)
    assert client.get("/api/v1/overview").status_code == 401
    client.cookies.set(auth.SESSION_COOKIE, auth.issue_session(store, now=NOW - timedelta(days=1)))
    assert client.get("/api/v1/overview").status_code == 401


def test_material_persisted_views_scope_unknown_corrections_and_exact_values(web, monkeypatch):
    client, store, engine, app = web
    login(client, store)

    def forbidden(*args, **kwargs):
        raise AssertionError("browser invoked a model or broker client")

    monkeypatch.setattr("trading_agent.research.model_client.LocalModelClient.__init__", forbidden)
    monkeypatch.setattr("trading_agent.execution.mcp_client.McpClient.__init__", forbidden)
    paths = [
        "runs",
        "overview",
        "health",
        "orders",
        "orders/order-good",
        "fills",
        "positions",
        "equity-curve",
        "activity",
        "instruments/TEST_A",
        "instruments/missing",
        "prices/TEST_A",
        "cash-ledger",
    ]
    with Session(engine) as session:
        before = {
            t.name: session.execute(select(func.count()).select_from(t)).scalar_one()
            for t in schema.metadata.sorted_tables
        }
    for path in paths:
        response = client.get("/api/v1/" + path + "?run_id=review-run")
        assert response.status_code == 200, (path, response.text)
        assert response.json()["scope"]["mode"] in (None, "SIMULATION")
        for alien in ("alien-run", "paper-run"):
            denied = client.get("/api/v1/" + path + "?run_id=" + alien)
            assert denied.status_code == 200
            assert denied.json()["scope"]["run_id"] is None
    assert [r["run_id"] for r in client.get("/api/v1/runs").json()["payload"]["runs"]] == [
        "review-run"
    ]
    detail = client.get("/api/v1/orders/order-good?run_id=review-run").json()["payload"]
    assert detail["order"]["status"] == "unknown"
    assert len(detail["fills"]) == 2
    positions = client.get("/api/v1/positions?run_id=review-run").json()
    assert positions["payload"]["cash"] == "123456789.12345678"
    assert positions["payload"]["positions"][0]["market_value"] is None
    assert "missing-mark" in positions["quality_flags"]
    assert positions["payload"]["equity"] is None
    assert (
        client.get("/api/v1/equity-curve?run_id=review-run").json()["payload"]["series"][0][
            "equity"
        ]
        is None
    )
    assert positions["payload"]["gross_exposure"] is None
    assert client.get("/api/v1/activity?cursor=not-a-cursor").status_code == 422
    assert client.get("/api/v1/activity?cursor=-1").status_code == 422
    for page in (
        "/",
        "/activity",
        "/orders",
        "/orders/order-good",
        "/portfolio",
        "/instruments/TEST_A",
    ):
        response = client.get(page)
        assert response.status_code == 200
        assert "script-src 'self'" in response.headers["content-security-policy"]
        assert response.headers["cache-control"] == "no-store"
    assert client.get("/api/v1/stream").status_code == 404
    assert client.get("/api/v1/export.csv").status_code == 404
    with Session(engine) as session:
        after = {
            t.name: session.execute(select(func.count()).select_from(t)).scalar_one()
            for t in schema.metadata.sorted_tables
        }
    assert before == after


def test_database_failure_is_unavailable_and_read_transaction_rejects_writes(web, monkeypatch):
    client, store, engine, app = web
    login(client, store)

    def corrupting_read(session, *args, **kwargs):
        session.execute(schema.runs.delete())

    monkeypatch.setattr("trading_agent.web.app.get_overview", corrupting_read)
    assert client.get("/api/v1/overview").status_code == 503
    with Session(engine) as session:
        assert session.execute(select(func.count()).select_from(schema.runs)).scalar_one() == 3


def test_database_partition_denies_even_a_signed_session(web, monkeypatch):
    from sqlalchemy.exc import OperationalError

    client, store, engine, app = web
    login(client, store)

    def unavailable(*args, **kwargs):
        raise OperationalError("fixture database unavailable", {}, Exception("fixture"))

    monkeypatch.setattr("trading_agent.web.app.open_session", unavailable)
    response = client.get("/api/v1/overview")
    assert response.status_code == 503
    assert response.json() == {"error": "local database unavailable"}


def test_schema_drift_is_a_startup_error(review_engine, review_config):
    from sqlalchemy import text

    from trading_agent.db.migrate import MigrationError, verify_schema

    verify_schema(review_config)
    with review_engine.begin() as conn:
        conn.execute(text("ALTER TABLE market_bars DROP COLUMN session_id"))
    try:
        with pytest.raises(MigrationError, match="market_bars.session_id"):
            verify_schema(review_config)
    finally:
        with review_engine.begin() as conn:
            conn.execute(text("ALTER TABLE market_bars ADD COLUMN session_id VARCHAR"))


def test_read_evidence_is_redacted_without_losing_exact_money(web):
    client, store, engine, app = web
    login(client, store)
    canary = "fixture-only-private-token-12345"
    with engine.begin() as conn:
        conn.execute(
            schema.activity_events.update().values(
                payload={"token": canary, "note": "Bearer " + canary}
            )
        )
        conn.execute(schema.decisions.update().values(rationale="Bearer " + canary))
    for endpoint in ("activity", "orders/order-good"):
        response = client.get("/api/v1/" + endpoint + "?run_id=review-run")
        assert response.status_code == 200 and canary not in response.text
        assert "[REDACTED]" in response.text
    assert (
        client.get("/api/v1/positions?run_id=review-run").json()["payload"]["cash"]
        == "123456789.12345678"
    )
