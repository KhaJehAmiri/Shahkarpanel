"""SigmaGuard client API: user client_profile + client_probes

Revision ID: e0f1a2b3c4d5
Revises: d9e0f1a2b3c4
Create Date: 2026-06-08 05:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'e0f1a2b3c4d5'
down_revision = 'd9e0f1a2b3c4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'client_profile',
                sa.String(length=16),
                nullable=False,
                server_default=sa.text("'normal'"),
            )
        )

    op.create_table(
        'client_probes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('node_id', sa.Integer(), nullable=True),
        sa.Column('profile', sa.String(length=16), nullable=True),
        sa.Column('protocol', sa.String(length=32), nullable=True),
        sa.Column('ping_ms', sa.Float(), nullable=True),
        sa.Column('packet_loss_pct', sa.Float(), nullable=True),
        sa.Column('handshake_ms', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['node_id'], ['nodes.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_client_probes_user_id', 'client_probes', ['user_id'], unique=False)
    op.create_index('ix_client_probes_node_id', 'client_probes', ['node_id'], unique=False)
    op.create_index('ix_client_probes_created_at', 'client_probes', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_client_probes_created_at', table_name='client_probes')
    op.drop_index('ix_client_probes_node_id', table_name='client_probes')
    op.drop_index('ix_client_probes_user_id', table_name='client_probes')
    op.drop_table('client_probes')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('client_profile')
