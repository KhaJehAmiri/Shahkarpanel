"""sub-reseller hierarchy: parent_admin_id on admins

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
Create Date: 2026-06-07 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c8d9e0f1a2b3'
down_revision = 'b7c8d9e0f1a2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('admins', schema=None) as batch_op:
        batch_op.add_column(sa.Column('parent_admin_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_admins_parent_admin_id', 'admins', ['parent_admin_id'], ['id'])
        batch_op.create_index('ix_admins_parent_admin_id', ['parent_admin_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('admins', schema=None) as batch_op:
        batch_op.drop_index('ix_admins_parent_admin_id')
        batch_op.drop_constraint('fk_admins_parent_admin_id', type_='foreignkey')
        batch_op.drop_column('parent_admin_id')
