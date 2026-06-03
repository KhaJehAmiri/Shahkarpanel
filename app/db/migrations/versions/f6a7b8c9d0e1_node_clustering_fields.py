"""node clustering fields + node_groups

Adds region/capacity/latency/health/group to nodes and a node_groups table
(phase 2: reliability & cluster).

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-06-03 02:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f6a7b8c9d0e1'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'node_groups',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('region', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )

    op.add_column('nodes', sa.Column('region', sa.String(length=64), nullable=True))
    op.add_column('nodes', sa.Column('capacity', sa.Integer(), nullable=True))
    op.add_column('nodes', sa.Column('latency_ms', sa.Float(), nullable=True))
    op.add_column('nodes', sa.Column('last_health', sa.DateTime(), nullable=True))
    op.add_column('nodes', sa.Column('group_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_nodes_region'), 'nodes', ['region'], unique=False)
    op.create_index(op.f('ix_nodes_group_id'), 'nodes', ['group_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_nodes_group_id'), table_name='nodes')
    op.drop_index(op.f('ix_nodes_region'), table_name='nodes')
    with op.batch_alter_table('nodes') as batch_op:
        batch_op.drop_column('group_id')
        batch_op.drop_column('last_health')
        batch_op.drop_column('latency_ms')
        batch_op.drop_column('capacity')
        batch_op.drop_column('region')
    op.drop_table('node_groups')
