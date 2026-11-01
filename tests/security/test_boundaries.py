from datetime import timedelta
from decimal import Decimal

import httpx
import pytest
from sqlalchemy.orm import Session

from tests.security.conftest import NOW, seed_run
from trading_agent.config.models import TradingConfig
from trading_agent.contracts.broker import (
    BrokerExecutionDenied,
    BrokerStateNotAvailable,
    BrokerUnavailable,
)
from trading_agent.contracts.orders import Fill, OrderSide
from trading_agent.execution.mcp_client import McpClient
from trading_agent.ledger.ledger import Ledger, LedgerInvariantError
from trading_agent.research.evaluation import evaluate_output
from trading_agent.security.loopback import is_loopback_url


@pytest.mark.parametrize(
    "url", ["http://0.0.0.0:1234/v1", "http://[::]:1234/v1", "http://user:pass@localhost:1234/v1"]
)
def test_unspecified_and_credential_urls_are_not_loopback(url):
    assert not is_loopback_url(url)


def test_one_flag_cannot_report_live_authority(valid_config_dict):
    config = TradingConfig.model_validate(valid_config_dict)
    config.live.enabled = True  # simulate a caller bypassing initial validation
    assert config.authority() == "LIVE_NOT_AUTHORIZED"


def test_read_client_refuses_missing_allowlist_and_mutation_before_transport():
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {}})

    client = McpClient(
        "https://agent.robinhood.com/mcp/trading",
        token="fixture-token",
        http=httpx.Client(transport=httpx.MockTransport(handle)),
    )
    client._connected = True
    for permitted in (None, {"place_equity_order"}):
        with pytest.raises(BrokerExecutionDenied):
            client.call_tool("place_equity_order", {}, permitted=permitted)
    assert calls == []


def test_mcp_redirect_and_wrong_response_id_are_rejected():
    calls = []

    def handle(request):
        calls.append(str(request.url))
        if request.url.host == "agent.robinhood.com":
            return httpx.Response(307, headers={"location": "https://unapproved.invalid/"})
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {}})

    http = httpx.Client(transport=httpx.MockTransport(handle), follow_redirects=True)
    client = McpClient("https://agent.robinhood.com/mcp/trading", token="fixture-token", http=http)
    with pytest.raises(BrokerUnavailable):
        client.initialize()
    assert calls == ["https://agent.robinhood.com/mcp/trading"]
    http = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"jsonrpc": "2.0", "id": 999, "result": {}})
        )
    )
    with pytest.raises(BrokerStateNotAvailable):
        McpClient(
            "https://agent.robinhood.com/mcp/trading", token="fixture-token", http=http
        ).initialize()


def test_structured_model_output_cannot_smuggle_tools_or_wrong_types():
    import json

    valid = dict(
        view="neutral",
        confidence=0.5,
        key_factors=["fixture"],
        risk_flags=[],
        summary="fixture",
        agrees_with_strategy=False,
    )
    for extra in ({"tools": ["place_order"]}, {"key_factors": [{"instruction": "change policy"}]}):
        assert (
            evaluate_output(json.dumps(valid | extra), prompt_version="research-v2").output_status
            == "invalid_output"
        )
    result = evaluate_output(json.dumps(valid), prompt_version="research-v2")
    assert result.output_status == "ok"
    assert isinstance(result.response_text, str)
    assert isinstance(result.structured["summary"], str)


def test_buy_fee_is_in_realized_basis_after_restart(review_engine):
    from trading_agent.db.schema import fills

    with Session(review_engine) as session:
        seed_run(session, "ledger-review")
        ledger = Ledger(
            session,
            run_id="ledger-review",
            portfolio_key="strategy",
            account_alias="simulation",
            initial_cash=Decimal(1000),
            initial_ts=NOW,
        )
        for index, side, price in [(1, OrderSide.BUY, "100"), (2, OrderSide.SELL, "110")]:
            fill = Fill(
                fill_id=f"fill-{index}",
                run_id="ledger-review",
                order_id=f"order-{index}",
                instrument_id="TEST_A",
                side=side,
                ts=NOW + timedelta(seconds=index),
                quantity=Decimal(1),
                price=Decimal(price),
                fee=Decimal(1),
                raw_fill_id=f"raw-{index}",
            )
            session.execute(
                fills.insert().values(
                    fill_id=fill.fill_id,
                    run_id=fill.run_id,
                    order_id=fill.order_id,
                    instrument_id=fill.instrument_id,
                    side=side.value,
                    ts=fill.ts,
                    quantity=fill.quantity,
                    price=fill.price,
                    fee=fill.fee,
                    raw_fill_id=fill.raw_fill_id,
                    source="synthetic",
                )
            )
            assert ledger.apply_fill(fill)
            assert not ledger.apply_fill(fill)
        ledger.flush()
        session.commit()
        assert ledger.cash == Decimal(1008)
        assert ledger.total_realized_pnl() == Decimal(8)
    with Session(review_engine) as session:
        restored = Ledger(
            session,
            run_id="ledger-review",
            portfolio_key="strategy",
            account_alias="simulation",
            initial_cash=Decimal(1000),
            initial_ts=NOW,
        )
        assert restored.cash == Decimal(1008)
        assert restored.total_realized_pnl() == Decimal(8)


def test_protected_secret_files_never_follow_links_or_accept_public_permissions(tmp_path):
    from trading_agent.execution.credentials import CredentialError, TokenStore
    from trading_agent.web import auth

    path = tmp_path / "runtime-token.json"
    store = TokenStore(path)
    store.save("fixture-private-runtime-token")
    assert path.stat().st_mode & 0o777 == 0o600
    assert store.load() == "fixture-private-runtime-token"
    assert "fixture-private" not in str(store.load_meta())
    path.chmod(0o644)
    with pytest.raises(CredentialError):
        store.load()
    link = tmp_path / "symlink.json"
    link.symlink_to(path)
    with pytest.raises(CredentialError):
        TokenStore(link).load()
    with pytest.raises(auth.AuthError):
        auth.load_store(link)


def test_model_redirect_cannot_forward_a_credential_or_echo_response_errors():
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from pydantic import SecretStr

    from trading_agent.config.models import LLMSettings
    from trading_agent.research.model_client import LocalModelClient, ModelHttpError

    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            calls.append(self.path)
            self.send_response(302)
            self.send_header("Location", "/unapproved-target")
            self.end_headers()
            self.wfile.write(b"fixture-private-model-token")

        def do_GET(self):
            calls.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = LocalModelClient(
        LLMSettings(
            base_url=f"http://127.0.0.1:{server.server_port}/v1",
            auth_token=SecretStr("fixture-private-model-token"),
        )
    )
    try:
        with pytest.raises(ModelHttpError) as caught:
            client.complete("fixture", "fixture")
        assert "fixture-private" not in str(caught.value)
        assert calls == ["/v1/chat/completions"]
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_schema_drift_duplicate_tools_and_legacy_dispatch_are_denied():
    from pathlib import Path

    from trading_agent.execution.capability import ToolSchema, canonical_digest, verify_capability
    from trading_agent.execution.mcp.client import McpOAuthClient, McpStateError
    from trading_agent.execution.mcp.transport import JsonRpcTransport, RpcError

    tool = ToolSchema("get_account", "fixture", {"type": "object"})
    digest = canonical_digest([tool])
    assert verify_capability([tool], digest).verified
    assert not verify_capability([ToolSchema("get_account", "changed", {})], digest).verified
    assert not verify_capability([tool, tool], digest).verified
    calls = []
    http = httpx.Client(transport=httpx.MockTransport(lambda r: calls.append(r)))
    transport = JsonRpcTransport("https://agent.robinhood.com/mcp/trading", http=http)
    with pytest.raises(RpcError):
        transport.request("tools/call", {"name": "place_order"})
    with pytest.raises(RpcError):
        transport.notify("tools/call", {"name": "place_order"})
    oauth = McpOAuthClient(
        endpoint_url="https://agent.robinhood.com/mcp/trading",
        token_store_path=Path("unused"),
        client_record_path=Path("unused"),
        phrase="fixture",
        http=http,
    )
    with pytest.raises(McpStateError):
        oauth.build_authorization_url()
    assert calls == []


def test_ledger_detects_stale_writers_and_audit_failure(review_engine, monkeypatch):
    with Session(review_engine) as session:
        seed_run(session, "concurrency")
        ledger = Ledger(
            session,
            run_id="concurrency",
            portfolio_key="strategy",
            account_alias="local-sim",
            initial_cash=Decimal(1000),
            initial_ts=NOW,
        )
        ledger.flush()
        session.commit()
    first, second = Session(review_engine), Session(review_engine)
    try:
        a = Ledger(
            first,
            run_id="concurrency",
            portfolio_key="strategy",
            account_alias="local-sim",
            initial_cash=Decimal(1000),
            initial_ts=NOW,
        )
        b = Ledger(
            second,
            run_id="concurrency",
            portfolio_key="strategy",
            account_alias="local-sim",
            initial_cash=Decimal(1000),
            initial_ts=NOW,
        )
        a.apply_cash_flow(Decimal(-600), kind="fixture-withdrawal", ts=NOW + timedelta(seconds=1))
        a.flush()
        first.commit()
        b.apply_cash_flow(Decimal(-600), kind="fixture-withdrawal", ts=NOW + timedelta(seconds=2))
        with pytest.raises(LedgerInvariantError, match="concurrent"):
            b.flush()
        second.rollback()
        with pytest.raises(LedgerInvariantError):
            b.apply_cash_flow(Decimal(1), kind="fixture", ts=NOW)
    finally:
        first.close()
        second.close()
    with Session(review_engine) as session:
        ledger = Ledger(
            session,
            run_id="concurrency",
            portfolio_key="strategy",
            account_alias="local-sim",
            initial_cash=Decimal(1000),
            initial_ts=NOW,
        )
        ledger.apply_cash_flow(Decimal(1), kind="fixture", ts=NOW + timedelta(seconds=3))
        execute = session.execute

        def fail_write(statement, *args, **kwargs):
            if getattr(statement, "is_insert", False):
                raise RuntimeError("fixture audit storage failure")
            return execute(statement, *args, **kwargs)

        monkeypatch.setattr(session, "execute", fail_write)
        with pytest.raises(RuntimeError):
            ledger.flush()
        session.rollback()
        with pytest.raises(LedgerInvariantError):
            ledger.apply_cash_flow(Decimal(1), kind="fixture", ts=NOW)
    with Session(review_engine) as session:
        restored = Ledger(
            session,
            run_id="concurrency",
            portfolio_key="strategy",
            account_alias="local-sim",
            initial_cash=Decimal(1000),
            initial_ts=NOW,
        )
        assert restored.cash == Decimal(400)


def test_csv_labels_are_inert_and_decimal_amounts_remain_exact():
    import csv
    import io

    from trading_agent.security.exports import SafeCsvWriter

    handle = io.StringIO()
    SafeCsvWriter(handle).writerow(
        ["=fixture()", "\t=fixture()", "+fixture()", "@fixture", "-123.12345678"]
    )
    row = next(csv.reader(io.StringIO(handle.getvalue())))
    assert all(value.startswith("'") for value in row[:4])
    assert row[4] == "-123.12345678"


def test_passive_benchmark_cannot_spend_fees_that_it_does_not_have():
    from trading_agent.backtest.engine import CloseSeries, run_passive_benchmark
    from trading_agent.config.models import BacktestCostSettings

    series = CloseSeries([(NOW.date(), Decimal(100))])
    curve = run_passive_benchmark(
        series,
        [NOW.date()],
        Decimal(100),
        Decimal(0),
        BacktestCostSettings(fee_rate=Decimal("0.01"), slippage_rate=Decimal("0.01")),
    )
    assert Decimal(98) < curve[0][1] < Decimal(99)


def test_cache_identity_cannot_read_outside_its_root(tmp_path):
    from trading_agent.data.realdata import RealDataCache

    cache = RealDataCache(tmp_path)
    with pytest.raises(ValueError):
        cache.load("../private", "credentials")
    with pytest.raises(ValueError):
        cache.load("fred", "../../private")


def test_equal_timestamp_cash_history_must_restore_in_application_order(review_engine):
    from trading_agent.db.schema import ledger_events

    with Session(review_engine) as session:
        seed_run(session, "ambiguous")
        ledger = Ledger(
            session,
            run_id="ambiguous",
            portfolio_key="strategy",
            account_alias="local-sim",
            initial_cash=Decimal(1000),
            initial_ts=NOW,
        )
        initial_key = ledger._pending[0]["event_key"]
        for index in range(10000):
            ref = f"fixture:flow-{index}:{NOW.isoformat()}"
            if ledger._event_key("external_deposit", ref) < initial_key:
                ledger.apply_cash_flow(
                    Decimal(100),
                    kind="external_deposit",
                    ts=NOW,
                    ref_type="fixture",
                    ref_id=f"flow-{index}",
                )
                break
        else:
            raise AssertionError("fixture ordering witness not found")
        ledger.flush()
        session.commit()
    with Session(review_engine) as session:
        restored = Ledger(
            session,
            run_id="ambiguous",
            portfolio_key="strategy",
            account_alias="local-sim",
            initial_cash=Decimal(1000),
            initial_ts=NOW,
        )
        assert restored.cash == Decimal(1100)
        # Unknown historical ties are still rejected; never infer a hash ordering.
        session.execute(
            ledger_events.update()
            .where(ledger_events.c.run_id == "ambiguous")
            .values(application_seq=None)
        )
        session.commit()
    with (
        Session(review_engine) as session,
        pytest.raises(LedgerInvariantError, match="ambiguous equal-timestamp"),
    ):
        Ledger(
            session,
            run_id="ambiguous",
            portfolio_key="strategy",
            account_alias="local-sim",
            initial_cash=Decimal(1000),
            initial_ts=NOW,
        )


def test_forged_runtime_cannot_activate_and_broker_mutations_never_dispatch(valid_config_dict):
    from tests.unit.test_live_activation_gate import _config, _VerifiedBroker
    from trading_agent.contracts.broker import OrderRequest
    from trading_agent.contracts.orders import RuntimeStatus
    from trading_agent.execution.robinhood_mcp import RobinhoodMcpBrokerAdapter
    from trading_agent.gates.live_activation import evaluate_live_activation

    config = _config(
        {
            "app": {"mode": "supervised_live"},
            "live": {
                "enabled": True,
                "approved_capital_usd": "1000",
                "owner_authorization_ref": "fixture",
                "authorization_expires_at": "2027-01-01T00:00:00Z",
            },
            "broker": {
                "provider": "robinhood",
                "approved_account_id": "fixture-alias",
                "allowlisted_tool_schema_digest": "sha256:abc123",
            },
            "universe": {"live_instrument_allowlist": ["SPY"]},
        }
    )
    result = evaluate_live_activation(
        config,
        _VerifiedBroker(),
        now=NOW,
        runtime=RuntimeStatus("consistent", ("fixture-strategy",)),
    )
    assert not result.authorized
    assert {check.name for check in result.unmet} == {"build_live_dispatch_disabled"}
    config.broker.shadow_enabled = True
    adapter = RobinhoodMcpBrokerAdapter(config)
    assert adapter._token_store is None
    assert not adapter.account_snapshot(now=NOW).available
    request = OrderRequest("SPY", "buy", Decimal(1), Decimal(100), "day", "fixture-order")
    for refusal in (adapter.submit_order(request), adapter.cancel_order("fixture-order")):
        assert not refusal.accepted and refusal.rejection_reason


def test_raw_fill_redelivery_conflict_and_missing_nav_are_fail_closed(review_engine):
    from dataclasses import replace

    with Session(review_engine) as session:
        seed_run(session, "redelivery")
        ledger = Ledger(
            session,
            run_id="redelivery",
            portfolio_key="strategy",
            account_alias="local-sim",
            initial_cash=Decimal(1000),
            initial_ts=NOW,
        )
        fill = Fill(
            "fill-one",
            "redelivery",
            "order-one",
            "TEST_A",
            OrderSide.BUY,
            NOW + timedelta(seconds=1),
            Decimal(1),
            Decimal(100),
            Decimal(1),
            "raw-one",
        )
        assert ledger.apply_fill(fill)
        assert not ledger.apply_fill(replace(fill, fill_id="different-delivery-id"))
        with pytest.raises(LedgerInvariantError, match="conflicting duplicate"):
            ledger.apply_fill(replace(fill, fill_id="conflict", price=Decimal(200)))
        with pytest.raises(LedgerInvariantError, match="sell fees"):
            ledger.apply_fill(
                replace(
                    fill,
                    fill_id="bad-fee",
                    raw_fill_id="bad-fee",
                    side=OrderSide.SELL,
                    fee=Decimal(2000),
                )
            )
        assert ledger.cash == Decimal(899) and ledger.position("TEST_A").quantity == Decimal(1)
        with pytest.raises(LedgerInvariantError, match="mark"):
            ledger.snapshot(marks={}, as_of=NOW + timedelta(seconds=2))


def test_configuration_parse_errors_do_not_echo_private_inputs(tmp_path):
    from trading_agent.config.loading import load_config
    from trading_agent.exceptions import ConfigError

    canary = "fixture-private-configuration-input"
    path = tmp_path / "bad-config.yaml"
    path.write_text('llm: ["' + canary)
    with pytest.raises(ConfigError) as caught:
        load_config(path, env={})
    assert canary not in str(caught.value)
    for key in ("LIVE_TRADING_ENABLED", "TRADING_AGENT_WEB_PORT"):
        with pytest.raises(ConfigError) as caught:
            load_config("config/simulation.yaml", env={key: canary})
        assert canary not in str(caught.value)
