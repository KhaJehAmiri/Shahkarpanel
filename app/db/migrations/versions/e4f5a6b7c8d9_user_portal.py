"""user portal: portal credentials and user orders

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-06-06 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'e4f5a6b7c8d9'
down_revision = 'd3e4f5a6b7c8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('portal_enabled', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('users', sa.Column('hashed_portal_password', sa.String(length=128), nullable=True))
    op.add_column('users', sa.Column('portal_password_reset_at', sa.DateTime(), nullable=True))

    op.create_table(
        'user_orders',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('plan_id', sa.Integer(), nullable=False),
        sa.Column('amount', sa.BigInteger(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='pending'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('paid_at', sa.DateTime(), nullable=True),
        sa.Column('applied_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['plan_id'], ['plans.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_user_orders_user_id', 'user_orders', ['user_id'])
    op.create_index('ix_user_orders_status', 'user_orders', ['status'])


def downgrade() -> None:
    op.drop_index('ix_user_orders_status', table_name='user_orders')
    op.drop_index('ix_user_orders_user_id', table_name='user_orders')
    op.drop_table('user_orders')
    op.drop_column('users', 'portal_password_reset_at')
    op.drop_column('users', 'hashed_portal_password')
    op.drop_column('users', 'portal_enabled')
