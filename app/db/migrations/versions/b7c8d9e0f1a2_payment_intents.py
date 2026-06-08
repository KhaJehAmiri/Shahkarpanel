"""payment intents for PSP top-up and portal renewals

Revision ID: b7c8d9e0f1a2
Revises: a6b7c8d9e0f1
Create Date: 2026-06-06 22:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'b7c8d9e0f1a2'
down_revision = 'a6b7c8d9e0f1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'payment_intents',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=32), nullable=False),
        sa.Column('admin_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('plan_id', sa.Integer(), nullable=True),
        sa.Column('amount', sa.BigInteger(), nullable=False),
        sa.Column('provider', sa.String(length=32), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='pending'),
        sa.Column('extra', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['admin_id'], ['admins.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['plan_id'], ['plans.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_payment_intents_admin_id', 'payment_intents', ['admin_id'], unique=False)
    op.create_index('ix_payment_intents_user_id', 'payment_intents', ['user_id'], unique=False)
    op.create_index('ix_payment_intents_status', 'payment_intents', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_payment_intents_status', table_name='payment_intents')
    op.drop_index('ix_payment_intents_user_id', table_name='payment_intents')
    op.drop_index('ix_payment_intents_admin_id', table_name='payment_intents')
    op.drop_table('payment_intents')
