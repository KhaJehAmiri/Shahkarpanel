"""usage billing checkpoints per reseller admin

Revision ID: a6b7c8d9e0f1
Revises: f5a6b7c8d9e0
Create Date: 2026-06-06 20:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'a6b7c8d9e0f1'
down_revision = 'f5a6b7c8d9e0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'usage_billing_checkpoints',
        sa.Column('admin_id', sa.Integer(), nullable=False),
        sa.Column('last_billed_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['admin_id'], ['admins.id']),
        sa.PrimaryKeyConstraint('admin_id'),
    )


def downgrade() -> None:
    op.drop_table('usage_billing_checkpoints')
