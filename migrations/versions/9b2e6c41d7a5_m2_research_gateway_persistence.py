"""M2 research and sanitized gateway persistence

Revision ID: 9b2e6c41d7a5
Revises: 6403ee565ba4
Create Date: 2026-11-10 09:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '9b2e6c41d7a5'
down_revision = '6403ee565ba4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('research_jobs',
    sa.Column('job_id', sa.String(length=64), nullable=False),
    sa.Column('run_id', sa.String(length=64), nullable=False),
    sa.Column('session_date', sa.Date(), nullable=False),
    sa.Column('source_id', sa.String(length=64), nullable=False),
    sa.Column('model_id', sa.String(length=128), nullable=True),
    sa.Column('prompt_version', sa.String(length=32), nullable=False),
    sa.Column('config_digest', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('calls_made', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('calls_budget', sa.Integer(), nullable=False),
    sa.Column('evaluations_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('error_class', sa.String(length=64), nullable=True),
    sa.Column('error_detail', sa.String(length=512), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.UniqueConstraint('job_id'),
    )
    op.create_table('research_evaluations',
    sa.Column('eval_id', sa.String(length=64), nullable=False),
    sa.Column('job_id', sa.String(length=64), nullable=False),
    sa.Column('run_id', sa.String(length=64), nullable=False),
    sa.Column('session_date', sa.Date(), nullable=False),
    sa.Column('instrument_id', sa.String(length=32), nullable=False),
    sa.Column('data_snapshot_id', sa.String(length=64), nullable=False),
    sa.Column('model_id', sa.String(length=128), nullable=True),
    sa.Column('prompt_version', sa.String(length=32), nullable=False),
    sa.Column('validation_status', sa.String(length=16), nullable=False),
    sa.Column('action', sa.String(length=16), nullable=True),
    sa.Column('weight', sa.Numeric(precision=20, scale=10), nullable=True),
    sa.Column('rationale', sa.String(length=1024), nullable=True),
    sa.Column('sanitized_response', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('response_digest', sa.String(length=64), nullable=True),
    sa.Column('response_chars', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('strategy_action', sa.String(length=16), nullable=True),
    sa.Column('strategy_weight', sa.Numeric(precision=20, scale=10), nullable=True),
    sa.Column('latency_ms', sa.Integer(), nullable=True),
    sa.Column('tokens_out', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('eval_id'),
    )
    op.create_index('ix_research_evaluations_run', 'research_evaluations', ['run_id', 'session_date'])
    op.create_table('gateway_snapshots',
    sa.Column('snapshot_id', sa.String(length=64), nullable=False),
    sa.Column('run_id', sa.String(length=64), nullable=False),
    sa.Column('session_date', sa.Date(), nullable=False),
    sa.Column('source_id', sa.String(length=64), nullable=False),
    sa.Column('account_alias', sa.String(length=64), nullable=False),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('sanitized_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('raw_digest', sa.String(length=64), nullable=True),
    sa.Column('field_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('snapshot_id'),
    )
    op.create_index('ix_gateway_snapshots_run', 'gateway_snapshots', ['run_id', 'kind', 'session_date'])


def downgrade() -> None:
    op.drop_index('ix_gateway_snapshots_run', table_name='gateway_snapshots')
    op.drop_table('gateway_snapshots')
    op.drop_index('ix_research_evaluations_run', table_name='research_evaluations')
    op.drop_table('research_evaluations')
    op.drop_table('research_jobs')
