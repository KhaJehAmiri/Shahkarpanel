"""phase 6: white-label tenants, branding, reseller-owned nodes and tunnels

Adds the tenants and branding_settings tables, the tunnels table, tenant/role
and provisioning columns on nodes, and the tenant_id column on admins.

Revision ID: e6a7b8c9d0f1
Revises: c9d0e1f2a3b4
Create Date: 2026-06-03 05:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e6a7b8c9d0f1'
down_revision = 'c9d0e1f2a3b4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'tenants',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('slug', sa.String(length=64), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('owner_admin_id', sa.Integer(), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.text('1')),
        sa.Column('max_users', sa.Integer(), nullable=True),
        sa.Column('max_nodes', sa.Integer(), nullable=True),
        sa.Column('byo_node_discount_percent', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['owner_admin_id'], ['admins.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('slug'),
    )
    op.create_index(op.f('ix_tenants_slug'), 'tenants', ['slug'], unique=True)
    op.create_index(op.f('ix_tenants_owner_admin_id'), 'tenants', ['owner_admin_id'], unique=False)

    op.create_table(
        'branding_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=True),
        sa.Column('panel_title', sa.String(length=128), nullable=True),
        sa.Column('logo_url', sa.String(length=512), nullable=True),
        sa.Column('favicon_url', sa.String(length=512), nullable=True),
        sa.Column('primary_color', sa.String(length=16), nullable=True),
        sa.Column('support_url', sa.String(length=512), nullable=True),
        sa.Column('sub_profile_title', sa.String(length=128), nullable=True),
        sa.Column('domain', sa.String(length=256), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', name='uq_branding_tenant'),
    )
    op.create_index(op.f('ix_branding_settings_tenant_id'), 'branding_settings', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_branding_settings_domain'), 'branding_settings', ['domain'], unique=False)

    op.create_table(
        'tunnels',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.text('1')),
        sa.Column('relay_node_id', sa.Integer(), nullable=False),
        sa.Column('exit_node_id', sa.Integer(), nullable=False),
        sa.Column('transport', sa.String(length=16), nullable=False, server_default='reality'),
        sa.Column('listen_port', sa.Integer(), nullable=False),
        sa.Column('target_port', sa.Integer(), nullable=False),
        sa.Column('params', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['relay_node_id'], ['nodes.id']),
        sa.ForeignKeyConstraint(['exit_node_id'], ['nodes.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_tunnels_relay_node_id'), 'tunnels', ['relay_node_id'], unique=False)
    op.create_index(op.f('ix_tunnels_exit_node_id'), 'tunnels', ['exit_node_id'], unique=False)

    with op.batch_alter_table('admins') as batch_op:
        batch_op.add_column(sa.Column('tenant_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_admins_tenant_id'), ['tenant_id'], unique=False)
        batch_op.create_foreign_key('fk_admins_tenant_id', 'tenants', ['tenant_id'], ['id'])

    with op.batch_alter_table('nodes') as batch_op:
        batch_op.add_column(sa.Column('tenant_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('owner_admin_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('role', sa.String(length=16), nullable=False, server_default=sa.text("'direct'")))
        batch_op.add_column(sa.Column('provision_host', sa.String(length=256), nullable=True))
        batch_op.add_column(sa.Column('provision_status', sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column('provision_message', sa.String(length=1024), nullable=True))
        batch_op.create_index(batch_op.f('ix_nodes_tenant_id'), ['tenant_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_nodes_owner_admin_id'), ['owner_admin_id'], unique=False)
        batch_op.create_foreign_key('fk_nodes_tenant_id', 'tenants', ['tenant_id'], ['id'])
        batch_op.create_foreign_key('fk_nodes_owner_admin_id', 'admins', ['owner_admin_id'], ['id'])


def downgrade() -> None:
    with op.batch_alter_table('nodes') as batch_op:
        batch_op.drop_constraint('fk_nodes_owner_admin_id', type_='foreignkey')
        batch_op.drop_constraint('fk_nodes_tenant_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_nodes_owner_admin_id'))
        batch_op.drop_index(batch_op.f('ix_nodes_tenant_id'))
        batch_op.drop_column('provision_message')
        batch_op.drop_column('provision_status')
        batch_op.drop_column('provision_host')
        batch_op.drop_column('role')
        batch_op.drop_column('owner_admin_id')
        batch_op.drop_column('tenant_id')

    with op.batch_alter_table('admins') as batch_op:
        batch_op.drop_constraint('fk_admins_tenant_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_admins_tenant_id'))
        batch_op.drop_column('tenant_id')

    op.drop_index(op.f('ix_tunnels_exit_node_id'), table_name='tunnels')
    op.drop_index(op.f('ix_tunnels_relay_node_id'), table_name='tunnels')
    op.drop_table('tunnels')

    op.drop_index(op.f('ix_branding_settings_domain'), table_name='branding_settings')
    op.drop_index(op.f('ix_branding_settings_tenant_id'), table_name='branding_settings')
    op.drop_table('branding_settings')

    op.drop_index(op.f('ix_tenants_owner_admin_id'), table_name='tenants')
    op.drop_index(op.f('ix_tenants_slug'), table_name='tenants')
    op.drop_table('tenants')
