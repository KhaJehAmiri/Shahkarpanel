"""plan tenant scope: per-reseller commercial catalog

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-06-06 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'f5a6b7c8d9e0'
down_revision = 'e4f5a6b7c8d9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == 'sqlite':
        op.create_table(
            'plans_new',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(length=128), nullable=False),
            sa.Column('price', sa.BigInteger(), nullable=False),
            sa.Column('data_limit', sa.BigInteger(), nullable=True),
            sa.Column('duration_days', sa.Integer(), nullable=True),
            sa.Column('device_limit', sa.Integer(), nullable=True),
            sa.Column('enabled', sa.Boolean(), nullable=False),
            sa.Column('tenant_id', sa.Integer(), nullable=True),
            sa.Column('owner_admin_id', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
            sa.ForeignKeyConstraint(['owner_admin_id'], ['admins.id']),
            sa.PrimaryKeyConstraint('id'),
        )
        op.execute(
            'INSERT INTO plans_new (id, name, price, data_limit, duration_days, device_limit, enabled, created_at) '
            'SELECT id, name, price, data_limit, duration_days, device_limit, enabled, created_at FROM plans'
        )
        op.drop_table('plans')
        op.rename_table('plans_new', 'plans')
        op.create_index('ix_plans_tenant_id', 'plans', ['tenant_id'], unique=False)
        op.create_index('ix_plans_owner_admin_id', 'plans', ['owner_admin_id'], unique=False)
    else:
        with op.batch_alter_table('plans', schema=None) as batch_op:
            batch_op.drop_constraint('plans_name_key', type_='unique')
            batch_op.add_column(sa.Column('tenant_id', sa.Integer(), nullable=True))
            batch_op.add_column(sa.Column('owner_admin_id', sa.Integer(), nullable=True))
            batch_op.create_foreign_key('fk_plans_tenant_id', 'tenants', ['tenant_id'], ['id'])
            batch_op.create_foreign_key('fk_plans_owner_admin_id', 'admins', ['owner_admin_id'], ['id'])
            batch_op.create_index('ix_plans_tenant_id', ['tenant_id'], unique=False)
            batch_op.create_index('ix_plans_owner_admin_id', ['owner_admin_id'], unique=False)


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == 'sqlite':
        op.create_table(
            'plans_old',
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
        op.execute(
            'INSERT INTO plans_old (id, name, price, data_limit, duration_days, device_limit, enabled, created_at) '
            'SELECT id, name, price, data_limit, duration_days, device_limit, enabled, created_at FROM plans'
        )
        op.drop_table('plans')
        op.rename_table('plans_old', 'plans')
    else:
        with op.batch_alter_table('plans', schema=None) as batch_op:
            batch_op.drop_index('ix_plans_owner_admin_id')
            batch_op.drop_index('ix_plans_tenant_id')
            batch_op.drop_constraint('fk_plans_owner_admin_id', type_='foreignkey')
            batch_op.drop_constraint('fk_plans_tenant_id', type_='foreignkey')
            batch_op.drop_column('owner_admin_id')
            batch_op.drop_column('tenant_id')
            batch_op.create_unique_constraint('plans_name_key', ['name'])
