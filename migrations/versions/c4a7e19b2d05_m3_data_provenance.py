"""M3 data provenance: source registry, snapshots, quality

Revision ID: c4a7e19b2d05
Revises: 9b2e6c41d7a5
Create Date: 2026-11-10 20:00:00.000000

Plan section 5 (data sources): every persisted observation, decision, and
snapshot already carries data_source + data_snapshot_id (M1 columns). These
three tables make the provenance complete and auditable:

* source_registry  — one row per data source id (registry entry from the
  configuration: license, access rules, permissions, deactivation rules).
* data_snapshots   — one row per snapshot id (content digest, origin URL,
  retrieval timestamp, point-in-time cutoff).
* data_quality     — per source per session: completeness/coverage numbers
  computed from the persisted market_bars rows.

All writes are idempotent (insert-or-ignore on the natural keys) so
crash-resume re-runs never duplicate provenance rows.
"""


revision = "c4a7e19b2d05"
down_revision = "9b2e6c41d7a5"
branch_labels = None
depends_on = None

import sqlalchemy as sa
from alembic import op


def upgrade() -> None:
    op.create_table(
        "source_registry",
        sa.Column("source_id", sa.String(length=32), primary_key=True),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("license_id", sa.String(length=64), nullable=False),
        sa.Column("license_terms", sa.String(length=512), nullable=True),
        sa.Column("access", sa.String(length=16), nullable=False),
        sa.Column("cost_usd_per_month", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("api_base_url", sa.String(length=512), nullable=True),
        sa.Column("auth_kind", sa.String(length=32), nullable=True),
        sa.Column("auth_configured", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("auth_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("store_allowed", sa.Boolean(), nullable=False),
        sa.Column("model_process_allowed", sa.Boolean(), nullable=False),
        sa.Column("web_display_allowed", sa.Boolean(), nullable=False),
        sa.Column("live_allowed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("retention_days", sa.Integer(), nullable=True),
        sa.Column("redownload_authorized", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("deactivate_when", sa.String(length=256), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.String(length=512), nullable=True),
    )
    op.create_table(
        "data_snapshots",
        sa.Column("snapshot_id", sa.String(length=64), primary_key=True),
        sa.Column("source_id", sa.String(length=32), nullable=False, index=True),
        sa.Column("content_digest", sa.String(length=64), nullable=False),
        sa.Column("origin_url", sa.String(length=512), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cutoff_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("first_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_ts", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_data_snapshots_source_retrieved", "data_snapshots", ["source_id", "retrieved_at"])
    op.create_table(
        "data_quality",
        sa.Column("source_id", sa.String(length=32), primary_key=True),
        sa.Column("run_id", sa.String(length=64), primary_key=True),
        sa.Column("session_date", sa.Date(), primary_key=True),
        sa.Column("expected_obs", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("received_obs", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("missing_obs", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("stale_sessions", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("quality_flags", sa.String(length=64), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_data_quality_source_session", "data_quality", ["source_id", "session_date"])


def downgrade() -> None:
    op.drop_index("ix_data_quality_source_session", table_name="data_quality")
    op.drop_table("data_quality")
    op.drop_index("ix_data_snapshots_source_retrieved", table_name="data_snapshots")
    op.drop_table("data_snapshots")
    op.drop_table("source_registry")
