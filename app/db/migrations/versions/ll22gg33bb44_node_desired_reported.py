"""Desired/reported columns on nodes (phase 4).

Revision ID: ll22gg33bb44
Revises: kk11ff22aa33
Create Date: 2026-08-19
"""
from alembic import op
import sqlalchemy as sa


revision = "ll22gg33bb44"
down_revision = "kk11ff22aa33"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("nodes", sa.Column("last_ack_at", sa.DateTime(), nullable=True))
    op.add_column(
        "nodes",
        sa.Column(
            "reported_peer_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column("nodes", sa.Column("ssh_ok", sa.Boolean(), nullable=True))
    op.add_column("nodes", sa.Column("control_tunnel_ok", sa.Boolean(), nullable=True))
    op.add_column("nodes", sa.Column("last_stats_ok", sa.DateTime(), nullable=True))
    op.add_column("nodes", sa.Column("desired_fingerprint", sa.String(length=64), nullable=True))
    op.add_column("nodes", sa.Column("reported_fingerprint", sa.String(length=64), nullable=True))
    op.add_column(
        "nodes",
        sa.Column("drift", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column("nodes", sa.Column("drift_reason", sa.String(length=512), nullable=True))
    op.create_index("ix_nodes_last_ack_at", "nodes", ["last_ack_at"])


def downgrade() -> None:
    op.drop_index("ix_nodes_last_ack_at", table_name="nodes")
    op.drop_column("nodes", "drift_reason")
    op.drop_column("nodes", "drift")
    op.drop_column("nodes", "reported_fingerprint")
    op.drop_column("nodes", "desired_fingerprint")
    op.drop_column("nodes", "last_stats_ok")
    op.drop_column("nodes", "control_tunnel_ok")
    op.drop_column("nodes", "ssh_ok")
    op.drop_column("nodes", "reported_peer_count")
    op.drop_column("nodes", "last_ack_at")
