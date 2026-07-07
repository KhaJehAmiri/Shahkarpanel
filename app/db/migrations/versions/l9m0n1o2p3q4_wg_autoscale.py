"""WireGuard auto-scale: wg_interfaces + wg_peers

Revision ID: l9m0n1o2p3q4
Revises: k8l9m0n1o2p3
Create Date: 2026-06-30 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "l9m0n1o2p3q4"
down_revision = "k8l9m0n1o2p3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "wg_interfaces",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("node_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column("subnet", sa.String(length=64), nullable=False),
        sa.Column("listen_port", sa.Integer(), nullable=False),
        sa.Column("private_key", sa.String(length=64), nullable=False),
        sa.Column("public_key", sa.String(length=64), nullable=False),
        sa.Column("peer_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_peers", sa.Integer(), nullable=False, server_default=sa.text("200")),
        sa.Column("slot_index", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["node_id"], ["nodes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("node_id", "name", name="uq_wg_interfaces_node_name"),
    )
    op.create_index("ix_wg_interfaces_node_id", "wg_interfaces", ["node_id"])

    op.create_table(
        "wg_peers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("interface_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("address", sa.String(length=64), nullable=False),
        sa.Column("private_key", sa.String(length=64), nullable=False),
        sa.Column("public_key", sa.String(length=64), nullable=False),
        sa.Column("preshared_key", sa.String(length=64), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["interface_id"], ["wg_interfaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_wg_peers_user_id"),
        sa.UniqueConstraint("interface_id", "address", name="uq_wg_peers_iface_address"),
        sa.UniqueConstraint("interface_id", "public_key", name="uq_wg_peers_iface_pubkey"),
    )
    op.create_index("ix_wg_peers_interface_id", "wg_peers", ["interface_id"])
    op.create_index("ix_wg_peers_user_id", "wg_peers", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_wg_peers_user_id", table_name="wg_peers")
    op.drop_index("ix_wg_peers_interface_id", table_name="wg_peers")
    op.drop_table("wg_peers")
    op.drop_index("ix_wg_interfaces_node_id", table_name="wg_interfaces")
    op.drop_table("wg_interfaces")
