"""Durable operational evidence, email outbox and bounded closeout jobs."""
from alembic import op
import sqlalchemy as sa
revision = "a61120261101"
down_revision = "f4b020261101"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("ops_records",
        sa.Column("record_id", sa.String(64), primary_key=True),
        sa.Column("scope", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("document", sa.Text(), nullable=False))
    op.create_table("ops_mail",
        sa.Column("message_id", sa.String(64), primary_key=True),
        sa.Column("scope", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("document", sa.Text(), nullable=False))
    op.create_table("ops_mail_attempts",
        sa.Column("consent_hash", sa.String(64), nullable=False),
        sa.Column("attempt_id", sa.String(64), primary_key=True),
        sa.Column("message_id", sa.String(64), sa.ForeignKey("ops_mail.message_id"), nullable=False),
        sa.Column("document", sa.Text(), nullable=False))
    op.create_table("ops_closeouts",
        sa.Column("job_id", sa.String(64), primary_key=True),
        sa.Column("scope", sa.String(64), nullable=False),
        sa.Column("document", sa.Text(), nullable=False))

    op.create_table("ops_monitors",
        sa.Column("scope", sa.String(64), primary_key=True),
        sa.Column("document", sa.Text(), nullable=False))


def downgrade():
    for name in ("ops_records", "ops_mail", "ops_mail_attempts", "ops_closeouts", "ops_monitors"):
        if op.get_bind().execute(sa.text("SELECT EXISTS (SELECT 1 FROM " + name + ")")).scalar_one():
            raise RuntimeError("nonempty operational evidence prevents downgrade")
    for name in ("ops_monitors", "ops_closeouts", "ops_mail_attempts", "ops_mail", "ops_records"):
        op.drop_table(name)
