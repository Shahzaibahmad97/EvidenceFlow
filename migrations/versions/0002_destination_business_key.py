"""destination business key

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('crm_record', schema=None) as batch_op:
        batch_op.add_column(sa.Column('business_key', sa.String(length=320), nullable=False))
        batch_op.create_unique_constraint('uq_crm_record_business_key', ['business_key'])



def downgrade() -> None:
    with op.batch_alter_table('crm_record', schema=None) as batch_op:
        batch_op.drop_constraint('uq_crm_record_business_key', type_='unique')
        batch_op.drop_column('business_key')

