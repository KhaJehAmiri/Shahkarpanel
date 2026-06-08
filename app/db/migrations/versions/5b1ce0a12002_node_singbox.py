"""create node_singbox table (Hysteria2 / TUIC server config)

Per-node sing-box server config for the QUIC product protocols. One row per
node that enables Hysteria2 and/or TUIC; both inbounds share the node TLS
material and a local Clash API port the panel polls for per-user traffic.

Revision ID: 5b1ce0a12002
Revises: 5b1ce0a12001
Create Date: 2026-06-08 00:00:01.000000

"""
import sqlalchemy as sa
from alembic import op

revision = "5b1ce0a12002"
down_revision = "5b1ce0a12001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "node_singbox",
        sa.Column("node_id", sa.Integer(), nullable=False),
        sa.Column("certificate_path", sa.String(length=512), nullable=True),
        sa.Column("key_path", sa.String(length=512), nullable=True),
        sa.Column("sni", sa.String(length=256), nullable=True),
        sa.Column("clash_api_port", sa.Integer(), server_default=sa.text("9095"), nullable=False),
        sa.Column("clash_api_secret", sa.String(length=128), nullable=True),
        sa.Column("hysteria2_enabled", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("hysteria2_port", sa.Integer(), nullable=True),
        sa.Column("hysteria2_up_mbps", sa.Integer(), nullable=True),
        sa.Column("hysteria2_down_mbps", sa.Integer(), nullable=True),
        sa.Column("hysteria2_obfs_password", sa.String(length=128), nullable=True),
        sa.Column("tuic_enabled", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("tuic_port", sa.Integer(), nullable=True),
        sa.Column("tuic_congestion_control", sa.String(length=16), server_default=sa.text("'bbr'"), nullable=False),
        sa.ForeignKeyConstraint(["node_id"], ["nodes.id"]),
        sa.PrimaryKeyConstraint("node_id"),
    )


def downgrade() -> None:
    op.drop_table("node_singbox")
