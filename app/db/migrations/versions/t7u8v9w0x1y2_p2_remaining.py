"""P2 remaining: per-node hosts, protocol usage, user routing/dns

Revision ID: t7u8v9w0x1y2
Revises: s6t7u8v9w0x1
Create Date: 2026-07-01
"""
from alembic import op
import sqlalchemy as sa


revision = "t7u8v9w0x1y2"
down_revision = "s6t7u8v9w0x1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("hosts", sa.Column("node_ids", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("routing_preset", sa.String(64), nullable=True))
    op.add_column("users", sa.Column("dns_policy", sa.JSON(), nullable=True))

    op.create_table(
        "node_user_protocol_usages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, index=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("node_id", sa.Integer(), sa.ForeignKey("nodes.id"), nullable=True, index=True),
        sa.Column("protocol", sa.String(32), nullable=False, index=True),
        sa.Column("used_traffic", sa.BigInteger(), nullable=False, server_default="0"),
        sa.UniqueConstraint("created_at", "user_id", "node_id", "protocol", name="uq_proto_usage_hour"),
    )


def downgrade() -> None:
    op.drop_table("node_user_protocol_usages")
    op.drop_column("users", "dns_policy")
    op.drop_column("users", "routing_preset")
    op.drop_column("hosts", "node_ids")
