"""tunnel endpoints nullable (panel-local core as a tunnel end)

Makes ``tunnels.relay_node_id`` and ``tunnels.exit_node_id`` nullable so that a
NULL endpoint represents the panel's own local Xray core. This allows a panel
on an Iran host to act as the relay (only a foreign exit node added) or a panel
on a foreign host to act as the exit (only an Iran relay node added).

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-06-06 02:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd3e4f5a6b7c8'
down_revision = 'c2d3e4f5a6b7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('tunnels') as batch_op:
        batch_op.alter_column('relay_node_id', existing_type=sa.Integer(), nullable=True)
        batch_op.alter_column('exit_node_id', existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    with op.batch_alter_table('tunnels') as batch_op:
        batch_op.alter_column('exit_node_id', existing_type=sa.Integer(), nullable=False)
        batch_op.alter_column('relay_node_id', existing_type=sa.Integer(), nullable=False)
