"""Add optional direct (untunneled) WireGuard listen port on relay nodes.

Revision ID: z4a5b6c7d8e9
Revises: y3z4a5b6c7d8
"""
from alembic import op
import sqlalchemy as sa


revision = "z4a5b6c7d8e9"
down_revision = "y3z4a5b6c7d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "node_wireguard",
        sa.Column("direct_listen_port", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("node_wireguard", "direct_listen_port")
