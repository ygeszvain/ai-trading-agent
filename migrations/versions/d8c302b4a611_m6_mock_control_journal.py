"""M6 additive mock control journal; does not repair prior schema drift or enable live."""

from alembic import op
import sqlalchemy as sa

revision = "d8c302b4a611"
down_revision = "c4a7e19b2d05"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "m6_accounts",
        sa.Column("account_key", sa.String(64), primary_key=True),
        sa.Column("document", sa.Text(), nullable=False),
    )
    op.create_table(
        "m6_approvals",
        sa.Column("approval_id", sa.String(96), primary_key=True),
        sa.Column(
            "account_key", sa.String(64), sa.ForeignKey("m6_accounts.account_key"), nullable=False
        ),
        sa.Column("intent_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("document", sa.Text(), nullable=False),
        sa.Column("consumed", sa.Boolean(), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "m6_orders",
        sa.Column("intent_id", sa.String(96), primary_key=True),
        sa.Column(
            "account_key", sa.String(64), sa.ForeignKey("m6_accounts.account_key"), nullable=False
        ),
        sa.Column(
            "approval_id",
            sa.String(96),
            sa.ForeignKey("m6_approvals.approval_id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("document", sa.Text(), nullable=False),
    )
    op.create_table(
        "m6_fills",
        sa.Column("fill_id", sa.String(96), primary_key=True),
        sa.Column(
            "account_key", sa.String(64), sa.ForeignKey("m6_accounts.account_key"), nullable=False
        ),
        sa.Column("order_id", sa.String(96), sa.ForeignKey("m6_orders.intent_id"), nullable=False),
        sa.Column("document", sa.Text(), nullable=False),
    )
    op.create_table(
        "m6_audit",
        sa.Column("sequence", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "account_key", sa.String(64), sa.ForeignKey("m6_accounts.account_key"), nullable=False
        ),
        sa.Column("run_id", sa.String(96), nullable=False),
        sa.Column("at", sa.String(40), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
    )


def downgrade():
    for name in ("m6_audit", "m6_fills", "m6_orders", "m6_approvals", "m6_accounts"):
        op.drop_table(name)
