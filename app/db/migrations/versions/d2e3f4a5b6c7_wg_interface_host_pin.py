"""Pin WireGuard interface hosts across auto-widen.

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-07-15
"""
from alembic import op
import sqlalchemy as sa


revision = "d2e3f4a5b6c7"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "node_wireguard",
        sa.Column("interface_host", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "node_wireguard",
        sa.Column("awg_interface_host", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("node_wireguard", "awg_interface_host")
    op.drop_column("node_wireguard", "interface_host")
