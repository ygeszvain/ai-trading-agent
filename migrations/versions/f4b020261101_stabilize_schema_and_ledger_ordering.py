"""Reconcile read contracts without guessing legacy provenance or tied ledger order.

Legacy M3 tables are retained verbatim under legacy_m3_* names. New projections
start empty. Equal-time legacy ledger books remain unsequenced and blocked.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "f4b020261101"
down_revision = "e71a4c09d522"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "fills",
        sa.Column("portfolio_key", sa.String(32), nullable=False, server_default="strategy"),
    )
    op.create_table(
        "executor_leases",
        sa.Column("scope", sa.String(128), primary_key=True),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("generation", sa.BigInteger(), nullable=False),
    )
    op.add_column("market_bars", sa.Column("session_id", sa.String(64), nullable=True))
    op.add_column("market_bars", sa.Column("exchange_timezone", sa.String(32), nullable=True))
    for name in ("source_registry", "data_snapshots", "data_quality"):
        op.rename_table(name, "legacy_m3_" + name)
    # These contracts differ structurally; no historical availability is invented.
    op.create_table(
        "source_registry",
        sa.Column("run_id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("source_id", sa.String(length=32), primary_key=True, nullable=False),
        sa.Column("source", sa.String(length=32), primary_key=False, nullable=False),
        sa.Column("kind", sa.String(length=16), primary_key=False, nullable=False),
        sa.Column(
            "enabled", sa.Boolean(), primary_key=False, nullable=False, server_default="false"
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            primary_key=False,
            nullable=False,
            server_default="disabled",
        ),
        sa.Column("config_digest", sa.String(length=64), primary_key=False, nullable=True),
        sa.Column("snapshot_id", sa.String(length=64), primary_key=False, nullable=True),
        sa.Column(
            "instruments_count", sa.Integer(), primary_key=False, nullable=False, server_default="0"
        ),
        sa.Column("symbols", postgresql.JSONB(), primary_key=False, nullable=True),
        sa.Column("error_class", sa.String(length=48), primary_key=False, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), primary_key=False, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), primary_key=False, nullable=True),
    )
    op.create_index("ix_source_registry_status", "source_registry", ["status"], unique=False)
    op.create_table(
        "data_snapshots",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("run_id", sa.String(length=64), primary_key=False, nullable=False),
        sa.Column("source_id", sa.String(length=32), primary_key=False, nullable=False),
        sa.Column("snapshot_id", sa.String(length=64), primary_key=False, nullable=False),
        sa.Column("content_digest", sa.String(length=64), primary_key=False, nullable=True),
        sa.Column(
            "bars_count", sa.Integer(), primary_key=False, nullable=False, server_default="0"
        ),
        sa.Column(
            "instruments_count", sa.Integer(), primary_key=False, nullable=False, server_default="0"
        ),
        sa.Column("first_ts", sa.DateTime(timezone=True), primary_key=False, nullable=True),
        sa.Column("last_ts", sa.DateTime(timezone=True), primary_key=False, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), primary_key=False, nullable=False),
        sa.UniqueConstraint("run_id", "source_id", name="uq_data_snapshots_run_source"),
    )
    op.create_index("ix_data_snapshots_run_id", "data_snapshots", ["run_id"], unique=False)
    op.create_index("ix_data_snapshots_source", "data_snapshots", ["source_id"], unique=False)
    op.create_table(
        "data_quality",
        sa.Column("run_id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("source_id", sa.String(length=32), primary_key=True, nullable=False),
        sa.Column("instrument_id", sa.String(length=16), primary_key=True, nullable=False),
        sa.Column("session_id", sa.String(length=16), primary_key=True, nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), primary_key=False, nullable=False),
        sa.Column("status", sa.String(length=16), primary_key=False, nullable=False),
        sa.Column(
            "flags", postgresql.JSONB(), primary_key=False, nullable=False, server_default="[]"
        ),
        sa.Column(
            "flag_count", sa.Integer(), primary_key=False, nullable=False, server_default="0"
        ),
        sa.Column(
            "missing_sessions", sa.Integer(), primary_key=False, nullable=False, server_default="0"
        ),
        sa.Column("last_observed_session", sa.String(length=16), primary_key=False, nullable=True),
    )
    op.create_index(
        "ix_data_quality_run_session", "data_quality", ["run_id", "session_id"], unique=False
    )
    op.create_index("ix_data_quality_status", "data_quality", ["status"], unique=False)
    op.create_table(
        "broker_snapshots",
        sa.Column("snapshot_id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("provider", sa.String(length=32), primary_key=False, nullable=False),
        sa.Column("account_alias", sa.String(length=64), primary_key=False, nullable=False),
        sa.Column("account_number_masked", sa.String(length=32), primary_key=False, nullable=True),
        sa.Column("session_date", sa.Date(), primary_key=False, nullable=False),
        sa.Column("cash_usd", sa.Numeric(precision=20, scale=8), primary_key=False, nullable=True),
        sa.Column("positions_json", postgresql.JSONB(), primary_key=False, nullable=True),
        sa.Column("open_orders_json", postgresql.JSONB(), primary_key=False, nullable=True),
        sa.Column("capability_digest", sa.String(length=64), primary_key=False, nullable=True),
        sa.Column("status", sa.String(length=32), primary_key=False, nullable=False),
        sa.Column("detail", sa.Text(), primary_key=False, nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), primary_key=False, nullable=False),
    )
    op.create_index(
        "ix_broker_snapshots_provider",
        "broker_snapshots",
        ["provider", "session_date"],
        unique=False,
    )
    op.create_table(
        "broker_gateway_events",
        sa.Column("event_id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("provider", sa.String(length=32), primary_key=False, nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), primary_key=False, nullable=False),
        sa.Column("event_type", sa.String(length=64), primary_key=False, nullable=False),
        sa.Column("detail", sa.Text(), primary_key=False, nullable=True),
        sa.Column("payload_json", postgresql.JSONB(), primary_key=False, nullable=True),
    )
    op.create_index(
        "ix_broker_gateway_events_ts", "broker_gateway_events", ["provider", "ts"], unique=False
    )
    op.add_column("ledger_events", sa.Column("application_seq", sa.BigInteger(), nullable=True))
    op.create_unique_constraint(
        "uq_ledger_application_seq", "ledger_events", ["run_id", "portfolio_key", "application_seq"]
    )
    op.execute(
        sa.text("""
        WITH safe_books AS (
          SELECT run_id, portfolio_key FROM ledger_events GROUP BY run_id, portfolio_key
          HAVING count(*) = count(DISTINCT ts)
        ), numbered AS (
          SELECT e.event_id, row_number() OVER (
            PARTITION BY e.run_id, e.portfolio_key ORDER BY e.ts
          ) AS seq FROM ledger_events e
          JOIN safe_books b USING (run_id, portfolio_key)
        ) UPDATE ledger_events e SET application_seq = n.seq
          FROM numbered n WHERE n.event_id = e.event_id
    """)
    )


def downgrade() -> None:
    bind = op.get_bind()
    # A downgrade must never discard newly written evidence or durable ordering.
    for name in (
        "source_registry",
        "data_snapshots",
        "data_quality",
        "broker_snapshots",
        "broker_gateway_events",
        "ledger_events",
        "fills",
        "executor_leases",
        "market_bars",
    ):
        if bind.execute(sa.text("SELECT EXISTS (SELECT 1 FROM " + name + ")")).scalar_one():
            raise RuntimeError(
                "nonempty evidence prevents destructive downgrade; restore reviewed backup"
            )
    op.drop_constraint("uq_ledger_application_seq", "ledger_events", type_="unique")
    op.drop_column("ledger_events", "application_seq")
    for name in (
        "source_registry",
        "data_snapshots",
        "data_quality",
        "broker_snapshots",
        "broker_gateway_events",
    ):
        op.drop_table(name)
    for name in ("source_registry", "data_snapshots", "data_quality"):
        op.rename_table("legacy_m3_" + name, name)
    op.drop_column("market_bars", "exchange_timezone")
    op.drop_column("market_bars", "session_id")
    op.drop_table("executor_leases")
    op.drop_column("fills", "portfolio_key")
