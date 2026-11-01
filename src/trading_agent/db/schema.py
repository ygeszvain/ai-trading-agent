"""SQLAlchemy Core schema (plan section 16: persistence and audit model).

Seventeen tables, all run-scoped except the web authentication pair. The
design rules that matter for auditability:

- Every consequential row is tied to a run, account alias, and mode.
- Money and quantity values are NUMERIC(20,8); timestamps are timestamptz
  (UTC); JSONB columns carry sanitized structured payloads.
- Unique ``event_key`` on ledger events and raw fill ids make application
  of any state change idempotent: a restart replays nothing twice.
- Activity events (outbox) are committed in the same transaction as the
  state they describe.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects import postgresql

MONEY = Numeric(20, 8)
JSONB = postgresql.JSONB
TS = DateTime(timezone=True)
ID = String(64)

metadata = MetaData()


# ---------------------------------------------------------------- runs

runs = Table(
    "runs",
    metadata,
    Column("run_id", ID, primary_key=True),
    Column("account_alias", String(64), nullable=False),
    Column("mode", String(32), nullable=False),
    Column("config_digest", String(64), nullable=False),
    Column("strategy_version", String(64), nullable=False),
    Column("risk_policy_version", String(64), nullable=False),
    Column("data_source", String(64), nullable=False),
    Column("data_snapshot_id", String(64), nullable=False),
    Column("initial_cash", MONEY, nullable=False),
    Column("status", String(32), nullable=False),  # running | completed | paused
    Column("fencing_token", BigInteger, nullable=False, server_default=text("0")),
    Column("created_at", TS, nullable=False),
    Column("completed_at", TS, nullable=True),
)

# ---------------------------------------------------------- instruments

instruments = Table(
    "instruments",
    metadata,
    Column("run_id", ID, primary_key=True),
    Column("instrument_id", String(32), primary_key=True),
    Column("symbol", String(32), nullable=False),
    Column("asset_class", String(32), nullable=False),
    Column("price_decimals", Integer, nullable=False),
    Column("quantity_precision", Integer, nullable=False),
    Column("is_synthetic", Boolean, nullable=False, server_default=text("true")),
    Column("eligible", Boolean, nullable=False, server_default=text("true")),
    Column("notes", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
)

# -------------------------------------------------------- market_bars

market_bars = Table(
    "market_bars",
    metadata,
    Column("run_id", ID, primary_key=True),
    Column("instrument_id", String(32), primary_key=True),
    Column("ts", TS, primary_key=True),
    Column("open", MONEY, nullable=False),
    Column("high", MONEY, nullable=False),
    Column("low", MONEY, nullable=False),
    Column("close", MONEY, nullable=False),
    Column("volume", MONEY, nullable=False),
    Column("source_id", String(64), nullable=False),
    Column("quality", String(16), nullable=False, server_default="valid"),
    Column("exchange_time", TS, nullable=True),
    Column("session_id", ID, nullable=True),
    Column("exchange_timezone", String(32), nullable=True),
)

# ------------------------------------------------------------ decisions

decisions = Table(
    "decisions",
    metadata,
    Column("decision_id", ID, primary_key=True),
    Column("run_id", ID, nullable=False),
    Column("account_alias", String(64), nullable=False),
    Column("mode", String(32), nullable=False),
    Column("instrument_id", String(32), nullable=False),
    Column("decision_at", TS, nullable=False),
    Column("expires_at", TS, nullable=False),
    Column("action", String(16), nullable=False),
    Column("target_weight", MONEY, nullable=False),
    Column("strategy_version", String(64), nullable=False),
    Column("model_version", String(64), nullable=True),
    Column("data_snapshot_id", String(64), nullable=False),
    Column("rationale", Text, nullable=False),
    Column("invalidation", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("risk_policy_version", String(64), nullable=False),
    UniqueConstraint("run_id", "instrument_id", "decision_at", name="uq_decisions"),
)

# --------------------------------------------------- risk_evaluations

risk_evaluations = Table(
    "risk_evaluations",
    metadata,
    Column("evaluation_id", ID, primary_key=True),
    Column("run_id", ID, nullable=False),
    Column("decision_id", ID, nullable=False, unique=True),
    Column("policy_version", String(64), nullable=False),
    Column("evaluated_at", TS, nullable=False),
    Column("outcome", String(16), nullable=False),
    Column("reasons", JSONB, nullable=False),
    Column("limits", JSONB, nullable=False),
)

# -------------------------------------------------------- reservations

reservations = Table(
    "reservations",
    metadata,
    Column("reservation_id", ID, primary_key=True),
    Column("run_id", ID, nullable=False),
    Column("kind", String(16), nullable=False),
    Column("order_id", ID, nullable=False),
    Column("intent_id", ID, nullable=False),
    Column("instrument_id", String(32), nullable=False),
    Column("amount", MONEY, nullable=False),
    Column("status", String(16), nullable=False, server_default="active"),
    Column("reserved_at", TS, nullable=False),
    Column("resolved_at", TS, nullable=True),
    Column("fencing_token", BigInteger, nullable=False, server_default=text("0")),
)

# -------------------------------------------------------- order_intents

order_intents = Table(
    "order_intents",
    metadata,
    Column("intent_id", ID, primary_key=True),
    Column("run_id", ID, nullable=False),
    Column("decision_id", ID, nullable=False),
    Column("account_alias", String(64), nullable=False),
    Column("instrument_id", String(32), nullable=False),
    Column("side", String(8), nullable=False),
    Column("quantity", MONEY, nullable=False),
    Column("limit_price", MONEY, nullable=False),
    Column("time_in_force", String(8), nullable=False),
    Column("client_order_id", ID, nullable=False, unique=True),
    Column("created_at", TS, nullable=False),
    Column("policy_version", String(64), nullable=False),
    Column("strategy_version", String(64), nullable=False),
)

# ------------------------------------------------- submission_attempts

submission_attempts = Table(
    "submission_attempts",
    metadata,
    Column("attempt_id", ID, primary_key=True),
    Column("run_id", ID, nullable=False),
    Column("order_id", ID, nullable=False),
    Column("request_digest", String(64), nullable=False),
    Column("submitted_at", TS, nullable=False),
    Column("outcome", String(16), nullable=False),
    Column("raw_status", String(32), nullable=False),
    Column("error_class", String(64), nullable=True),
)

# ------------------------------------------------------ broker_orders

broker_orders = Table(
    "broker_orders",
    metadata,
    Column("order_id", ID, primary_key=True),
    Column("run_id", ID, nullable=False),
    Column("intent_id", ID, nullable=False),
    Column("client_order_id", ID, nullable=False, unique=True),
    Column("account_alias", String(64), nullable=False),
    Column("instrument_id", String(32), nullable=False),
    Column("side", String(8), nullable=False),
    Column("order_type", String(16), nullable=False),
    Column("limit_price", MONEY, nullable=False),
    Column("quantity", MONEY, nullable=False),
    Column("time_in_force", String(8), nullable=False),
    Column("status", String(24), nullable=False),
    Column("raw_status", String(32), nullable=False),
    Column("filled_quantity", MONEY, nullable=False, server_default=text("0")),
    Column("created_at", TS, nullable=False),
    Column("updated_at", TS, nullable=False),
    Column("expires_at", TS, nullable=True),
    Column("cancel_requested_at", TS, nullable=True),
)

# ------------------------------------------------------- order_events

order_events = Table(
    "order_events",
    metadata,
    Column("run_id", ID, primary_key=True),
    Column("order_id", ID, primary_key=True),
    Column("seq", Integer, primary_key=True),
    Column("ts", TS, nullable=False),
    Column("from_status", String(24), nullable=False),
    Column("to_status", String(24), nullable=False),
    Column("reason", Text, nullable=False),
)

# ---------------------------------------------------------------- fills

fills = Table(
    "fills",
    metadata,
    Column("fill_id", ID, primary_key=True),
    Column("run_id", ID, nullable=False),
    Column("order_id", ID, nullable=False),
    Column("instrument_id", String(32), nullable=False),
    Column("side", String(8), nullable=False),
    Column("ts", TS, nullable=False),
    Column("quantity", MONEY, nullable=False),
    Column("price", MONEY, nullable=False),
    Column("fee", MONEY, nullable=False),
    Column("raw_fill_id", ID, nullable=False),
    Column("source", String(32), nullable=False, server_default="simulator"),
    Column("corrected_by", ID, nullable=True),
    UniqueConstraint("run_id", "raw_fill_id", name="uq_fills_raw"),
)

# ------------------------------------------------------- ledger_events

ledger_events = Table(
    "ledger_events",
    metadata,
    Column("event_id", ID, primary_key=True),
    Column("event_key", ID, nullable=False, unique=True),
    Column("run_id", ID, nullable=False),
    Column("portfolio_key", String(32), nullable=False),
    Column("ts", TS, nullable=False),
    Column("kind", String(32), nullable=False),
    Column("instrument_id", String(32), nullable=True),
    Column("quantity", MONEY, nullable=True),
    Column("price", MONEY, nullable=True),
    Column("amount", MONEY, nullable=True),
    Column("fee", MONEY, nullable=True),
    Column("cash_after", MONEY, nullable=True),
    Column("position_after", MONEY, nullable=True),
    Column("ref_type", String(32), nullable=True),
    Column("ref_id", ID, nullable=True),
    Column("fencing_token", BigInteger, nullable=False, server_default=text("0")),
    Column("note", Text, nullable=True),
)

# ------------------------------------------------- portfolio_snapshots

portfolio_snapshots = Table(
    "portfolio_snapshots",
    metadata,
    Column("run_id", ID, primary_key=True),
    Column("portfolio_key", String(32), primary_key=True),
    Column("ts", TS, primary_key=True),
    Column("equity", MONEY, nullable=False),
    Column("cash", MONEY, nullable=False),
    Column("gross_exposure", MONEY, nullable=False),
    Column("positions", JSONB, nullable=False),
    Column("reconciliation_status", String(16), nullable=False, server_default="unverified"),
)

# -------------------------------------------------- reconciliation_runs

reconciliation_runs = Table(
    "reconciliation_runs",
    metadata,
    Column("reconciliation_id", ID, primary_key=True),
    Column("run_id", ID, nullable=False),
    Column("session_date", String(16), nullable=False),
    Column("status", String(16), nullable=False),  # consistent | needs-review
    Column("differences", JSONB, nullable=False),
    Column("started_at", TS, nullable=False),
    Column("completed_at", TS, nullable=False),
)

# ---------------------------------------------------- activity_events

activity_events = Table(
    "activity_events",
    metadata,
    Column("event_id", ID, primary_key=True),
    Column("cursor", BigInteger, primary_key=True),
    Column("run_id", ID, nullable=False),
    Column("account_alias", String(64), nullable=False),
    Column("mode", String(32), nullable=False),
    Column("ts", TS, nullable=False),
    Column("origin", String(32), nullable=False),
    Column("event_type", String(64), nullable=False),
    Column("correlation", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("payload", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("corrected_by", ID, nullable=True),
)

# ----------------------------------------------------------- web_auth

web_auth = Table(
    "web_auth",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("kind", String(16), nullable=False, unique=True),  # "bootstrap"
    Column("token_sha256", String(64), nullable=False),
    Column("created_at", TS, nullable=False),
)

web_sessions = Table(
    "web_sessions",
    metadata,
    Column("session_sha256", String(64), primary_key=True),
    Column("created_at", TS, nullable=False),
    Column("expires_at", TS, nullable=False),
    Column("last_seen_at", TS, nullable=False),
)


# ----------------------------------------------------------- research (M2)

research_jobs = Table(
    "research_jobs",
    metadata,
    Column("job_id", String(64), primary_key=True),
    Column("run_id", String(64), nullable=False),
    Column("session_date", Date, nullable=False),
    Column("source_id", String(64), nullable=False),
    Column("model_id", String(128), nullable=True),
    Column("prompt_version", String(32), nullable=False),
    Column("config_digest", String(64), nullable=False),
    Column("status", String(32), nullable=False),
    Column("calls_made", Integer, server_default=text("0"), nullable=False),
    Column("calls_budget", Integer, nullable=False),
    Column("evaluations_count", Integer, server_default=text("0"), nullable=False),
    Column("error_class", String(64), nullable=True),
    Column("error_detail", String(512), nullable=True),
    Column("created_at", TS, nullable=False),
    Column("started_at", TS, nullable=True),
    Column("finished_at", TS, nullable=True),
    UniqueConstraint("job_id"),
)

research_evaluations = Table(
    "research_evaluations",
    metadata,
    Column("eval_id", String(64), primary_key=True),
    Column("job_id", String(64), nullable=False),
    Column("run_id", String(64), nullable=False),
    Column("session_date", Date, nullable=False),
    Column("instrument_id", String(32), nullable=False),
    Column("data_snapshot_id", String(64), nullable=False),
    Column("model_id", String(128), nullable=True),
    Column("prompt_version", String(32), nullable=False),
    Column("validation_status", String(16), nullable=False),  # valid|invalid|unavailable
    Column("action", String(16), nullable=True),
    Column("weight", Numeric(20, 10), nullable=True),
    Column("rationale", String(1024), nullable=True),
    Column("sanitized_response", JSONB, server_default=text("'{}'::jsonb"), nullable=False),
    Column("response_digest", String(64), nullable=True),
    Column("response_chars", Integer, server_default=text("0"), nullable=False),
    Column("strategy_action", String(16), nullable=True),
    Column("strategy_weight", Numeric(20, 10), nullable=True),
    Column("latency_ms", Integer, nullable=True),
    Column("tokens_out", Integer, nullable=True),
    Column("created_at", TS, nullable=False),
    Index("ix_research_evaluations_run", "run_id", "session_date"),
)

gateway_snapshots = Table(
    "gateway_snapshots",
    metadata,
    Column("snapshot_id", String(64), primary_key=True),
    Column("run_id", String(64), nullable=False),
    Column("session_date", Date, nullable=False),
    Column("source_id", String(64), nullable=False),
    Column("account_alias", String(64), nullable=False),
    Column("kind", String(32), nullable=False),
    Column("sanitized_payload", JSONB, nullable=False),
    Column("raw_digest", String(64), nullable=True),
    Column("field_count", Integer, server_default=text("0"), nullable=False),
    Column("fetched_at", TS, nullable=False),
    Index("ix_gateway_snapshots_run", "run_id", "kind", "session_date"),
)

# --------------------------------------------------------------------- M4
# Broker gateway (plan section 14) — Robinhood official MCP, shadow mode.
#
# These tables hold sanitized, read-only views of the brokerage account and
# the gateway's verification audit trail. The MCP token never appears here:
# account identity is stored masked, and event payloads are structured.

broker_snapshots = Table(
    "broker_snapshots",
    metadata,
    Column("snapshot_id", String(64), primary_key=True),
    Column("provider", String(32), nullable=False),
    Column("account_alias", String(64), nullable=False),
    Column("account_number_masked", String(32), nullable=True),
    Column("session_date", Date, nullable=False),
    Column("cash_usd", MONEY, nullable=True),
    Column("positions_json", JSONB, nullable=True),
    Column("open_orders_json", JSONB, nullable=True),
    Column("capability_digest", String(64), nullable=True),
    Column("status", String(32), nullable=False),
    Column("detail", Text, nullable=True),
    Column("fetched_at", TS, nullable=False),
    Index("ix_broker_snapshots_provider", "provider", "session_date"),
)

broker_gateway_events = Table(
    "broker_gateway_events",
    metadata,
    Column("event_id", String(64), primary_key=True),
    Column("provider", String(32), nullable=False),
    Column("ts", TS, nullable=False),
    Column("event_type", String(64), nullable=False),
    Column("detail", Text, nullable=True),
    Column("payload_json", JSONB, nullable=True),
    Index("ix_broker_gateway_events_ts", "provider", "ts"),
)

TABLES: list[Table] = [
    runs,
    instruments,
    market_bars,
    decisions,
    risk_evaluations,
    reservations,
    order_intents,
    submission_attempts,
    broker_orders,
    order_events,
    fills,
    ledger_events,
    portfolio_snapshots,
    reconciliation_runs,
    activity_events,
    web_auth,
    web_sessions,
    research_jobs,
    research_evaluations,
    gateway_snapshots,
    broker_snapshots,
    broker_gateway_events,
]

# --------------------------------------------------------------------- M3
# Data-provenance tables (plan section 8: registry-driven data sources).
#
# The website is a read-only surface over these tables; nothing here is a
# source of execution truth.

data_snapshots = Table(
    "data_snapshots",
    metadata,
    Column("id", ID, primary_key=True),
    Column("run_id", ID, nullable=False, index=True),
    Column("source_id", String(32), nullable=False),
    Column("snapshot_id", String(64), nullable=False),
    Column("content_digest", String(64), nullable=True),
    Column("bars_count", Integer, nullable=False, server_default="0"),
    Column("instruments_count", Integer, nullable=False, server_default="0"),
    Column("first_ts", TS, nullable=True),
    Column("last_ts", TS, nullable=True),
    Column("created_at", TS, nullable=False),
    UniqueConstraint("run_id", "source_id", name="uq_data_snapshots_run_source"),
)

source_registry = Table(
    "source_registry",
    metadata,
    Column("run_id", ID, nullable=False, primary_key=True),
    Column("source_id", String(32), nullable=False, primary_key=True),
    Column("source", String(32), nullable=False),
    Column("kind", String(16), nullable=False),
    Column("enabled", Boolean, nullable=False, server_default="false"),
    Column("status", String(16), nullable=False, server_default="disabled"),
    Column("config_digest", String(64), nullable=True),
    Column("snapshot_id", String(64), nullable=True),
    Column("instruments_count", Integer, nullable=False, server_default="0"),
    Column("symbols", JSONB, nullable=True),
    Column("error_class", String(48), nullable=True),
    Column("created_at", TS, nullable=False),
    Column("updated_at", TS, nullable=True),
)

data_quality = Table(
    "data_quality",
    metadata,
    Column("run_id", ID, nullable=False, primary_key=True),
    Column("source_id", String(32), nullable=False, primary_key=True),
    Column("instrument_id", String(16), nullable=False, primary_key=True),
    Column("session_id", String(16), nullable=False, primary_key=True),
    Column("checked_at", TS, nullable=False),
    Column("status", String(16), nullable=False),
    Column("flags", JSONB, nullable=False, server_default="[]"),
    Column("flag_count", Integer, nullable=False, server_default="0"),
    Column("missing_sessions", Integer, nullable=False, server_default="0"),
    Column("last_observed_session", String(16), nullable=True),
)

source_registry_idx = Index("ix_source_registry_status", source_registry.c.status)
data_quality_status_idx = Index("ix_data_quality_status", data_quality.c.status)
data_quality_session_idx = Index(
    "ix_data_quality_run_session",
    data_quality.c.run_id,
    data_quality.c.session_id,
)
data_snapshots_idx = Index("ix_data_snapshots_source", data_snapshots.c.source_id)


# M6 mock-only control journal; production dispatch remains unavailable.
m6_accounts = Table(
    "m6_accounts",
    metadata,
    Column("account_key", String(64), primary_key=True),
    Column("document", Text, nullable=False),
)
m6_approvals = Table(
    "m6_approvals",
    metadata,
    Column("approval_id", String(96), primary_key=True),
    Column("account_key", String(64), ForeignKey("m6_accounts.account_key"), nullable=False),
    Column("intent_hash", String(64), nullable=False, unique=True),
    Column("document", Text, nullable=False),
    Column("consumed", Boolean, nullable=False),
    Column("revoked", Boolean, nullable=False),
)
m6_orders = Table(
    "m6_orders",
    metadata,
    Column("intent_id", String(96), primary_key=True),
    Column("account_key", String(64), ForeignKey("m6_accounts.account_key"), nullable=False),
    Column(
        "approval_id",
        String(96),
        ForeignKey("m6_approvals.approval_id"),
        nullable=False,
        unique=True,
    ),
    Column("document", Text, nullable=False),
)
m6_fills = Table(
    "m6_fills",
    metadata,
    Column("fill_id", String(96), primary_key=True),
    Column("account_key", String(64), ForeignKey("m6_accounts.account_key"), nullable=False),
    Column("order_id", String(96), ForeignKey("m6_orders.intent_id"), nullable=False),
    Column("document", Text, nullable=False),
)
m6_audit = Table(
    "m6_audit",
    metadata,
    Column("sequence", Integer, primary_key=True, autoincrement=True),
    Column("account_key", String(64), ForeignKey("m6_accounts.account_key"), nullable=False),
    Column("run_id", String(96), nullable=False),
    Column("at", String(40), nullable=False),
    Column("event_type", String(64), nullable=False),
    Column("payload", Text, nullable=False),
)
M6_TABLES = (m6_accounts, m6_approvals, m6_orders, m6_fills, m6_audit)


# M7 shares accounting contracts, not M6 per-intent approval authority.
def _m7_journal_tables() -> tuple[Table, ...]:
    account = Table(
        "m7_accounts",
        metadata,
        Column("account_key", String(64), primary_key=True),
        Column("document", Text, nullable=False),
    )
    envelope = Table(
        "m7_envelopes",
        metadata,
        Column("approval_id", String(96), primary_key=True),
        Column("account_key", String(64), ForeignKey("m7_accounts.account_key"), nullable=False),
        Column("intent_hash", String(64), unique=True, nullable=False),
        Column("document", Text, nullable=False),
        Column("consumed", Boolean, nullable=False),
        Column("revoked", Boolean, nullable=False),
    )
    order = Table(
        "m7_orders",
        metadata,
        Column("intent_id", String(96), primary_key=True),
        Column("account_key", String(64), ForeignKey("m7_accounts.account_key"), nullable=False),
        Column("approval_id", String(96), ForeignKey("m7_envelopes.approval_id"), nullable=False),
        Column("document", Text, nullable=False),
    )
    fill = Table(
        "m7_fills",
        metadata,
        Column("fill_id", String(96), primary_key=True),
        Column("account_key", String(64), ForeignKey("m7_accounts.account_key"), nullable=False),
        Column("order_id", String(96), ForeignKey("m7_orders.intent_id"), nullable=False),
        Column("document", Text, nullable=False),
    )
    event = Table(
        "m7_audit",
        metadata,
        Column("sequence", Integer, primary_key=True, autoincrement=True),
        Column("account_key", String(64), ForeignKey("m7_accounts.account_key"), nullable=False),
        Column("run_id", String(96), nullable=False),
        Column("at", String(40), nullable=False),
        Column("event_type", String(64), nullable=False),
        Column("payload", Text, nullable=False),
    )
    return account, envelope, order, fill, event


M7_TABLES = _m7_journal_tables()
m7_accounts, m7_envelopes, m7_orders, m7_fills, m7_audit = M7_TABLES
m7_runtime = Table(
    "m7_runtime",
    metadata,
    Column("account_key", String(64), ForeignKey("m7_accounts.account_key"), primary_key=True),
    Column("document", Text, nullable=False),
)
m7_monitor = Table(
    "m7_monitor",
    metadata,
    Column("account_key", String(64), ForeignKey("m7_accounts.account_key"), primary_key=True),
    Column("document", Text, nullable=False),
)
m7_notices = Table(
    "m7_notices",
    metadata,
    Column("incident_hash", String(64), primary_key=True),
    Column("account_key", String(64), ForeignKey("m7_accounts.account_key"), nullable=False),
    Column("document", Text, nullable=False),
    Column("acknowledged", Boolean, nullable=False),
)
m7_changes = Table(
    "m7_changes",
    metadata,
    Column("change_id", String(64), primary_key=True),
    Column("account_key", String(64), ForeignKey("m7_accounts.account_key"), nullable=False),
    Column("kind", String(32), nullable=False),
    Column("document", Text, nullable=False),
)
M7_ALL_TABLES = (*M7_TABLES, m7_runtime, m7_monitor, m7_notices, m7_changes)
