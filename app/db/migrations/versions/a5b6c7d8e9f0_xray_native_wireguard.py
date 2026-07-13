"""Add Xray-native WireGuard inbound (Finalmask noise obfuscated) fields.

Revision ID: a5b6c7d8e9f0
Revises: z4a5b6c7d8e9
"""
from alembic import op
import sqlalchemy as sa


revision = "a5b6c7d8e9f0"
down_revision = "z4a5b6c7d8e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "node_wireguard",
        sa.Column("xray_wg_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "node_wireguard",
        sa.Column("xray_wg_listen_port", sa.Integer(), nullable=True),
    )
    op.add_column(
        "node_wireguard",
        sa.Column("xray_wg_mtu", sa.Integer(), nullable=False, server_default=sa.text("1420")),
    )
    op.add_column(
        "node_wireguard",
        sa.Column("xray_wg_noise", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("node_wireguard", "xray_wg_noise")
    op.drop_column("node_wireguard", "xray_wg_mtu")
    op.drop_column("node_wireguard", "xray_wg_listen_port")
    op.drop_column("node_wireguard", "xray_wg_enabled")
