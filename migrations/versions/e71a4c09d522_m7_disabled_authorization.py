"""Add disabled M7 envelope/incident/change journal; prior schema drift remains blocked."""

import sqlalchemy as sa
from alembic import op

revision = "e71a4c09d522"
down_revision = "d8c302b4a611"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "m7_accounts",
        sa.Column("account_key", sa.String(64), primary_key=True, nullable=False),
        sa.Column("document", sa.Text(), primary_key=False, nullable=False),
    )
    op.create_table(
        "m7_envelopes",
        sa.Column("approval_id", sa.String(96), primary_key=True, nullable=False),
        sa.Column(
            "account_key",
            sa.String(64),
            sa.ForeignKey("m7_accounts.account_key"),
            primary_key=False,
            nullable=False,
        ),
        sa.Column("intent_hash", sa.String(64), primary_key=False, nullable=False, unique=True),
        sa.Column("document", sa.Text(), primary_key=False, nullable=False),
        sa.Column("consumed", sa.Boolean(), primary_key=False, nullable=False),
        sa.Column("revoked", sa.Boolean(), primary_key=False, nullable=False),
    )
    op.create_table(
        "m7_orders",
        sa.Column("intent_id", sa.String(96), primary_key=True, nullable=False),
        sa.Column(
            "account_key",
            sa.String(64),
            sa.ForeignKey("m7_accounts.account_key"),
            primary_key=False,
            nullable=False,
        ),
        sa.Column(
            "approval_id",
            sa.String(96),
            sa.ForeignKey("m7_envelopes.approval_id"),
            primary_key=False,
            nullable=False,
        ),
        sa.Column("document", sa.Text(), primary_key=False, nullable=False),
    )
    op.create_table(
        "m7_fills",
        sa.Column("fill_id", sa.String(96), primary_key=True, nullable=False),
        sa.Column(
            "account_key",
            sa.String(64),
            sa.ForeignKey("m7_accounts.account_key"),
            primary_key=False,
            nullable=False,
        ),
        sa.Column(
            "order_id",
            sa.String(96),
            sa.ForeignKey("m7_orders.intent_id"),
            primary_key=False,
            nullable=False,
        ),
        sa.Column("document", sa.Text(), primary_key=False, nullable=False),
    )
    op.create_table(
        "m7_audit",
        sa.Column("sequence", sa.Integer(), primary_key=True, nullable=False),
        sa.Column(
            "account_key",
            sa.String(64),
            sa.ForeignKey("m7_accounts.account_key"),
            primary_key=False,
            nullable=False,
        ),
        sa.Column("run_id", sa.String(96), primary_key=False, nullable=False),
        sa.Column("at", sa.String(40), primary_key=False, nullable=False),
        sa.Column("event_type", sa.String(64), primary_key=False, nullable=False),
        sa.Column("payload", sa.Text(), primary_key=False, nullable=False),
    )
    op.create_table(
        "m7_runtime",
        sa.Column(
            "account_key",
            sa.String(64),
            sa.ForeignKey("m7_accounts.account_key"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("document", sa.Text(), primary_key=False, nullable=False),
    )
    op.create_table(
        "m7_monitor",
        sa.Column(
            "account_key",
            sa.String(64),
            sa.ForeignKey("m7_accounts.account_key"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("document", sa.Text(), primary_key=False, nullable=False),
    )
    op.create_table(
        "m7_notices",
        sa.Column("incident_hash", sa.String(64), primary_key=True, nullable=False),
        sa.Column(
            "account_key",
            sa.String(64),
            sa.ForeignKey("m7_accounts.account_key"),
            primary_key=False,
            nullable=False,
        ),
        sa.Column("document", sa.Text(), primary_key=False, nullable=False),
        sa.Column("acknowledged", sa.Boolean(), primary_key=False, nullable=False),
    )
    op.create_table(
        "m7_changes",
        sa.Column("change_id", sa.String(64), primary_key=True, nullable=False),
        sa.Column(
            "account_key",
            sa.String(64),
            sa.ForeignKey("m7_accounts.account_key"),
            primary_key=False,
            nullable=False,
        ),
        sa.Column("kind", sa.String(32), primary_key=False, nullable=False),
        sa.Column("document", sa.Text(), primary_key=False, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("m7_changes")
    op.drop_table("m7_notices")
    op.drop_table("m7_monitor")
    op.drop_table("m7_runtime")
    op.drop_table("m7_audit")
    op.drop_table("m7_fills")
    op.drop_table("m7_orders")
    op.drop_table("m7_envelopes")
    op.drop_table("m7_accounts")
