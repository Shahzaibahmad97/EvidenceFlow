"""initial schema

Revision ID: 0001
Revises: 
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('crm_record',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('idempotency_key', sa.String(length=64), nullable=False),
    sa.Column('external_id', sa.String(length=64), nullable=False),
    sa.Column('payload', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('idempotency_key', name='uq_crm_record_idempotency_key')
    )
    op.create_table('document',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('filename', sa.String(length=255), nullable=False),
    sa.Column('source_text', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('approved_payload_hash', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('extraction',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('document_id', sa.String(length=36), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('schema_version', sa.String(length=16), nullable=False),
    sa.Column('raw_payload', sa.JSON(), nullable=True),
    sa.Column('draft', sa.JSON(), nullable=True),
    sa.Column('evidence', sa.JSON(), nullable=True),
    sa.Column('payload_hash', sa.String(length=64), nullable=True),
    sa.Column('error_code', sa.String(length=64), nullable=True),
    sa.Column('error_detail', sa.Text(), nullable=True),
    sa.Column('model', sa.String(length=128), nullable=True),
    sa.Column('prompt_hash', sa.String(length=64), nullable=True),
    sa.Column('latency_ms', sa.Integer(), nullable=True),
    sa.Column('input_tokens', sa.Integer(), nullable=True),
    sa.Column('output_tokens', sa.Integer(), nullable=True),
    sa.Column('request_id', sa.String(length=128), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['document.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('extraction', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_extraction_document_id'), ['document_id'], unique=False)

    op.create_table('job',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('type', sa.String(length=16), nullable=False),
    sa.Column('document_id', sa.String(length=36), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('max_attempts', sa.Integer(), nullable=False),
    sa.Column('run_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('locked_by', sa.String(length=64), nullable=True),
    sa.Column('failure_kind', sa.String(length=32), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['document.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('job', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_job_document_id'), ['document_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_job_run_at'), ['run_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_job_status'), ['status'], unique=False)

    op.create_table('approval',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('document_id', sa.String(length=36), nullable=False),
    sa.Column('extraction_id', sa.String(length=36), nullable=False),
    sa.Column('payload_hash', sa.String(length=64), nullable=False),
    sa.Column('actor', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['document.id'], ),
    sa.ForeignKeyConstraint(['extraction_id'], ['extraction.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('approval', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_approval_document_id'), ['document_id'], unique=False)

    op.create_table('crm_write',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('document_id', sa.String(length=36), nullable=False),
    sa.Column('extraction_id', sa.String(length=36), nullable=False),
    sa.Column('idempotency_key', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('external_id', sa.String(length=64), nullable=True),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['document.id'], ),
    sa.ForeignKeyConstraint(['extraction_id'], ['extraction.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('idempotency_key', name='uq_crm_write_idempotency_key')
    )
    with op.batch_alter_table('crm_write', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_crm_write_document_id'), ['document_id'], unique=False)

    op.create_table('event',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('document_id', sa.String(length=36), nullable=False),
    sa.Column('extraction_id', sa.String(length=36), nullable=True),
    sa.Column('type', sa.String(length=48), nullable=False),
    sa.Column('actor', sa.String(length=64), nullable=False),
    sa.Column('payload', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['document.id'], ),
    sa.ForeignKeyConstraint(['extraction_id'], ['extraction.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('event', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_event_document_id'), ['document_id'], unique=False)

    op.create_table('validation_result',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('extraction_id', sa.String(length=36), nullable=False),
    sa.Column('rule', sa.String(length=64), nullable=False),
    sa.Column('outcome', sa.String(length=16), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['extraction_id'], ['extraction.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('validation_result', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_validation_result_extraction_id'), ['extraction_id'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('validation_result', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_validation_result_extraction_id'))

    op.drop_table('validation_result')
    with op.batch_alter_table('event', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_event_document_id'))

    op.drop_table('event')
    with op.batch_alter_table('crm_write', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_crm_write_document_id'))

    op.drop_table('crm_write')
    with op.batch_alter_table('approval', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_approval_document_id'))

    op.drop_table('approval')
    with op.batch_alter_table('job', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_job_status'))
        batch_op.drop_index(batch_op.f('ix_job_run_at'))
        batch_op.drop_index(batch_op.f('ix_job_document_id'))

    op.drop_table('job')
    with op.batch_alter_table('extraction', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_extraction_document_id'))

    op.drop_table('extraction')
    op.drop_table('document')
    op.drop_table('crm_record')
