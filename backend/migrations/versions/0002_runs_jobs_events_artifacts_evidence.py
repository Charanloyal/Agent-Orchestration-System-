"""runs jobs events artifacts evidence

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-15 10:56:48.356191
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0002'
down_revision: str | None = '0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # LangGraph checkpoint tables live in their own schema, managed by the library (ADR 0007).
    op.execute("CREATE SCHEMA IF NOT EXISTS lg")
    op.create_table('briefs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=False),
    sa.Column('body', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('idempotency_key', sa.String(length=100), nullable=False),
    sa.Column('request_sha256', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_briefs_created_by_users')),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_briefs_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_briefs')),
    sa.UniqueConstraint('workspace_id', 'created_by', 'idempotency_key', name=op.f('uq_briefs_workspace_id_created_by_idempotency_key'))
    )
    op.create_index(op.f('ix_briefs_workspace_id'), 'briefs', ['workspace_id'], unique=False)
    op.create_table('runs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('brief_id', sa.Uuid(), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=False),
    sa.Column('state', sa.String(length=30), nullable=False),
    sa.Column('parent_run_id', sa.Uuid(), nullable=True),
    sa.Column('deadline_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('cancel_requested_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('outcome_reason', sa.String(length=500), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("state IN ('QUEUED', 'PLANNING', 'AWAITING_PLAN_APPROVAL', 'RESEARCHING', 'WRITING', 'REVIEWING', 'AWAITING_REPORT_APPROVAL', 'SUCCEEDED', 'NEEDS_ATTENTION', 'FAILED', 'CANCEL_REQUESTED', 'CANCELLED', 'EXPIRED')", name=op.f('ck_runs_state')),
    sa.ForeignKeyConstraint(['brief_id'], ['briefs.id'], name=op.f('fk_runs_brief_id_briefs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_runs_created_by_users')),
    sa.ForeignKeyConstraint(['parent_run_id'], ['runs.id'], name=op.f('fk_runs_parent_run_id_runs'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_runs_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_runs'))
    )
    op.create_index('ix_runs_workspace_created', 'runs', ['workspace_id', 'created_at'], unique=False)
    op.create_table('approvals',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('artifact_kind', sa.String(length=10), nullable=False),
    sa.Column('artifact_version', sa.Integer(), nullable=False),
    sa.Column('artifact_digest', sa.String(length=64), nullable=False),
    sa.Column('decision', sa.String(length=10), nullable=False),
    sa.Column('comment', sa.String(length=500), nullable=True),
    sa.Column('decided_by', sa.Uuid(), nullable=False),
    sa.Column('decided_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("artifact_kind IN ('plan', 'report')", name=op.f('ck_approvals_artifact_kind')),
    sa.CheckConstraint("decision IN ('approve', 'reject')", name=op.f('ck_approvals_decision')),
    sa.ForeignKeyConstraint(['decided_by'], ['users.id'], name=op.f('fk_approvals_decided_by_users')),
    sa.ForeignKeyConstraint(['run_id'], ['runs.id'], name=op.f('fk_approvals_run_id_runs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_approvals_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_approvals')),
    sa.UniqueConstraint('run_id', 'artifact_kind', 'artifact_version', name=op.f('uq_approvals_run_id_artifact_kind_artifact_version'))
    )
    op.create_table('plan_versions',
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('digest', sa.String(length=64), nullable=False),
    sa.Column('body', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('author', sa.String(length=10), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['run_id'], ['runs.id'], name=op.f('fk_plan_versions_run_id_runs'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('run_id', 'version', name=op.f('pk_plan_versions'))
    )
    op.create_table('report_versions',
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('plan_version', sa.Integer(), nullable=False),
    sa.Column('digest', sa.String(length=64), nullable=False),
    sa.Column('body', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['run_id'], ['runs.id'], name=op.f('fk_report_versions_run_id_runs'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('run_id', 'version', name=op.f('pk_report_versions'))
    )
    op.create_table('run_events',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('event_type', sa.String(length=50), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['run_id'], ['runs.id'], name=op.f('fk_run_events_run_id_runs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_run_events_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_run_events'))
    )
    op.create_index('ix_run_events_run_id_id', 'run_events', ['run_id', 'id'], unique=False)
    op.create_table('run_jobs',
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('state', sa.String(length=10), nullable=False),
    sa.Column('waiting_for', sa.String(length=10), nullable=True),
    sa.Column('resume_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('lease_owner', sa.String(length=100), nullable=True),
    sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('fencing_token', sa.BigInteger(), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('max_attempts', sa.Integer(), nullable=False),
    sa.Column('available_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('wait_deadline_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error', sa.String(length=500), nullable=True),
    sa.CheckConstraint("(state = 'LEASED') = (lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)", name=op.f('ck_run_jobs_lease_consistent')),
    sa.CheckConstraint("(state = 'WAITING') = (waiting_for IS NOT NULL)", name=op.f('ck_run_jobs_wait_consistent')),
    sa.CheckConstraint("state IN ('QUEUED', 'LEASED', 'WAITING', 'DONE', 'FAILED')", name=op.f('ck_run_jobs_state')),
    sa.CheckConstraint("waiting_for IS NULL OR waiting_for IN ('plan', 'report')", name=op.f('ck_run_jobs_waiting_for')),
    sa.ForeignKeyConstraint(['run_id'], ['runs.id'], name=op.f('fk_run_jobs_run_id_runs'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('run_id', name=op.f('pk_run_jobs'))
    )
    op.create_index('ix_run_jobs_claimable', 'run_jobs', ['state', 'available_at'], unique=False)
    op.create_table('sources',
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('source_id', sa.String(length=64), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.String(length=10), nullable=False),
    sa.Column('url', sa.Text(), nullable=True),
    sa.Column('upload_id', sa.Uuid(), nullable=True),
    sa.Column('title', sa.String(length=500), nullable=True),
    sa.Column('retrieved_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('published_on', sa.String(length=10), nullable=True),
    sa.Column('fetch_status', sa.String(length=10), nullable=False),
    sa.Column('failure_reason', sa.String(length=500), nullable=True),
    sa.Column('content_sha256', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("fetch_status IN ('fetched', 'failed')", name=op.f('ck_sources_fetch_status')),
    sa.CheckConstraint("kind IN ('web', 'upload', 'corpus')", name=op.f('ck_sources_kind')),
    sa.ForeignKeyConstraint(['run_id'], ['runs.id'], name=op.f('fk_sources_run_id_runs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_sources_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('run_id', 'source_id', name=op.f('pk_sources'))
    )
    op.create_index('ix_sources_run_id', 'sources', ['run_id'], unique=False)
    op.create_table('task_results',
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('task_id', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('output', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('fencing_token', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('succeeded', 'no_evidence', 'failed')", name=op.f('ck_task_results_status')),
    sa.ForeignKeyConstraint(['run_id'], ['runs.id'], name=op.f('fk_task_results_run_id_runs'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('run_id', 'task_id', name=op.f('pk_task_results'))
    )
    op.create_table('tool_executions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('task_id', sa.String(length=64), nullable=False),
    sa.Column('tool', sa.String(length=40), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('fencing_token', sa.BigInteger(), nullable=False),
    sa.Column('error_class', sa.String(length=60), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('started', 'succeeded', 'failed', 'abandoned')", name=op.f('ck_tool_executions_status')),
    sa.ForeignKeyConstraint(['run_id'], ['runs.id'], name=op.f('fk_tool_executions_run_id_runs'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tool_executions'))
    )
    op.create_index('ix_tool_executions_run_id', 'tool_executions', ['run_id'], unique=False)
    op.create_table('evidence_passages',
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('evidence_id', sa.String(length=64), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('source_id', sa.String(length=64), nullable=False),
    sa.Column('task_id', sa.String(length=64), nullable=False),
    sa.Column('locator', sa.String(length=200), nullable=True),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('text_sha256', sa.String(length=64), nullable=False),
    sa.Column('fencing_token', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['run_id', 'source_id'], ['sources.run_id', 'sources.source_id'], name=op.f('fk_evidence_passages_run_id_sources'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['run_id'], ['runs.id'], name=op.f('fk_evidence_passages_run_id_runs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_evidence_passages_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('run_id', 'evidence_id', name=op.f('pk_evidence_passages'))
    )
    op.create_index('ix_evidence_passages_run_task', 'evidence_passages', ['run_id', 'task_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_evidence_passages_run_task', table_name='evidence_passages')
    op.drop_table('evidence_passages')
    op.drop_index('ix_tool_executions_run_id', table_name='tool_executions')
    op.drop_table('tool_executions')
    op.drop_table('task_results')
    op.drop_index('ix_sources_run_id', table_name='sources')
    op.drop_table('sources')
    op.drop_index('ix_run_jobs_claimable', table_name='run_jobs')
    op.drop_table('run_jobs')
    op.drop_index('ix_run_events_run_id_id', table_name='run_events')
    op.drop_table('run_events')
    op.drop_table('report_versions')
    op.drop_table('plan_versions')
    op.drop_table('approvals')
    op.drop_index('ix_runs_workspace_created', table_name='runs')
    op.drop_table('runs')
    op.drop_index(op.f('ix_briefs_workspace_id'), table_name='briefs')
    op.drop_table('briefs')
    op.execute("DROP SCHEMA IF EXISTS lg CASCADE")
