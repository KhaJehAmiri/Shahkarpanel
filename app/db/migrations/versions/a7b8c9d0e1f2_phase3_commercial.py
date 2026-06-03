"""phase 3 commercialization: rbac, plans, billing, api keys

Adds RBAC/quota columns to admins and the plans, wallets, transactions,
invoices and api_keys tables.

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-06-03 04:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a7b8c9d0e1f2'
down_revision = 'f6a7b8c9d0e1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('admins', sa.Column('role', sa.String(length=32), nullable=True))
    op.add_column('admins', sa.Column('max_users', sa.Integer(), nullable=True))
    op.add_column('admins', sa.Column('max_total_traffic', sa.BigInteger(), nullable=True))
    op.add_column('admins', sa.Column('max_nodes', sa.Integer(), nullable=True))

    op.create_table(
        'plans',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('price', sa.BigInteger(), nullable=False),
        sa.Column('data_limit', sa.BigInteger(), nullable=True),
        sa.Column('duration_days', sa.Integer(), nullable=True),
        sa.Column('device_limit', sa.Integer(), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )

    op.create_table(
        'wallets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('admin_id', sa.Integer(), nullable=False),
        sa.Column('balance', sa.BigInteger(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['admin_id'], ['admins.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('admin_id'),
    )

    op.create_table(
        'transactions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('admin_id', sa.Integer(), nullable=False),
        sa.Column('amount', sa.BigInteger(), nullable=False),
        sa.Column('type', sa.String(length=32), nullable=False),
        sa.Column('description', sa.String(length=512), nullable=True),
        sa.Column('reference', sa.String(length=128), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['admin_id'], ['admins.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_transactions_admin_id'), 'transactions', ['admin_id'], unique=False)
    op.create_index(op.f('ix_transactions_created_at'), 'transactions', ['created_at'], unique=False)

    op.create_table(
        'invoices',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('admin_id', sa.Integer(), nullable=False),
        sa.Column('plan_id', sa.Integer(), nullable=True),
        sa.Column('amount', sa.BigInteger(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('provider', sa.String(length=32), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('paid_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['admin_id'], ['admins.id']),
        sa.ForeignKeyConstraint(['plan_id'], ['plans.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_invoices_admin_id'), 'invoices', ['admin_id'], unique=False)
    op.create_index(op.f('ix_invoices_status'), 'invoices', ['status'], unique=False)

    op.create_table(
        'api_keys',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('admin_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('prefix', sa.String(length=16), nullable=False),
        sa.Column('key_hash', sa.String(length=128), nullable=False),
        sa.Column('scopes', sa.JSON(), nullable=True),
        sa.Column('revoked', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('last_used_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['admin_id'], ['admins.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key_hash'),
    )
    op.create_index(op.f('ix_api_keys_admin_id'), 'api_keys', ['admin_id'], unique=False)
    op.create_index(op.f('ix_api_keys_prefix'), 'api_keys', ['prefix'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_api_keys_prefix'), table_name='api_keys')
    op.drop_index(op.f('ix_api_keys_admin_id'), table_name='api_keys')
    op.drop_table('api_keys')

    op.drop_index(op.f('ix_invoices_status'), table_name='invoices')
    op.drop_index(op.f('ix_invoices_admin_id'), table_name='invoices')
    op.drop_table('invoices')

    op.drop_index(op.f('ix_transactions_created_at'), table_name='transactions')
    op.drop_index(op.f('ix_transactions_admin_id'), table_name='transactions')
    op.drop_table('transactions')

    op.drop_table('wallets')
    op.drop_table('plans')

    with op.batch_alter_table('admins') as batch_op:
        batch_op.drop_column('max_nodes')
        batch_op.drop_column('max_total_traffic')
        batch_op.drop_column('max_users')
        batch_op.drop_column('role')
