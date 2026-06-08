"""SigmaGuard client phase B: device tokens, telemetry, dedicated IPs

Revision ID: f1a2b3c4d5e6
Revises: e0f1a2b3c4d5
Create Date: 2026-06-08 05:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'f1a2b3c4d5e6'
down_revision = 'e0f1a2b3c4d5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'client_devices',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('token', sa.String(length=512), nullable=False),
        sa.Column('platform', sa.String(length=16), nullable=True),
        sa.Column('app_version', sa.String(length=32), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_client_devices_user_id', 'client_devices', ['user_id'], unique=False)
    op.create_index('ix_client_devices_token', 'client_devices', ['token'], unique=True)

    op.create_table(
        'client_telemetry',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('session_id', sa.String(length=64), nullable=True),
        sa.Column('active_protocol', sa.String(length=32), nullable=True),
        sa.Column('active_node', sa.Integer(), nullable=True),
        sa.Column('ping_ms', sa.Float(), nullable=True),
        sa.Column('packet_loss_pct', sa.Float(), nullable=True),
        sa.Column('bytes_sent', sa.BigInteger(), nullable=True),
        sa.Column('bytes_recv', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['active_node'], ['nodes.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_client_telemetry_user_id', 'client_telemetry', ['user_id'], unique=False)
    op.create_index('ix_client_telemetry_session_id', 'client_telemetry', ['session_id'], unique=False)
    op.create_index('ix_client_telemetry_created_at', 'client_telemetry', ['created_at'], unique=False)

    op.create_table(
        'dedicated_ips',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('address', sa.String(length=64), nullable=False),
        sa.Column('node_id', sa.Integer(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('assigned_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['node_id'], ['nodes.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('address'),
        sa.UniqueConstraint('user_id'),
    )
    op.create_index('ix_dedicated_ips_address', 'dedicated_ips', ['address'], unique=True)
    op.create_index('ix_dedicated_ips_node_id', 'dedicated_ips', ['node_id'], unique=False)
    op.create_index('ix_dedicated_ips_user_id', 'dedicated_ips', ['user_id'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_dedicated_ips_user_id', table_name='dedicated_ips')
    op.drop_index('ix_dedicated_ips_node_id', table_name='dedicated_ips')
    op.drop_index('ix_dedicated_ips_address', table_name='dedicated_ips')
    op.drop_table('dedicated_ips')

    op.drop_index('ix_client_telemetry_created_at', table_name='client_telemetry')
    op.drop_index('ix_client_telemetry_session_id', table_name='client_telemetry')
    op.drop_index('ix_client_telemetry_user_id', table_name='client_telemetry')
    op.drop_table('client_telemetry')

    op.drop_index('ix_client_devices_token', table_name='client_devices')
    op.drop_index('ix_client_devices_user_id', table_name='client_devices')
    op.drop_table('client_devices')
