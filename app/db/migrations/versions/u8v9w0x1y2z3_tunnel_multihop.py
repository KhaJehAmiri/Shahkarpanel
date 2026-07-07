"""Tunnel multihop: optional transit node between relay and exit.

Revision ID: u8v9w0x1y2z3
Revises: t7u8v9w0x1y2
Create Date: 2026-07-01
"""
from alembic import op
import sqlalchemy as sa


revision = "u8v9w0x1y2z3"
down_revision = "t7u8v9w0x1y2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tunnels", sa.Column("intermediate_node_id", sa.Integer(), nullable=True))
    op.add_column("tunnels", sa.Column("intermediate_port", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_tunnels_intermediate_node_id",
        "tunnels",
        "nodes",
        ["intermediate_node_id"],
        ["id"],
    )
    op.create_index(
        op.f("ix_tunnels_intermediate_node_id"),
        "tunnels",
        ["intermediate_node_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_tunnels_intermediate_node_id"), table_name="tunnels")
    op.drop_constraint("fk_tunnels_intermediate_node_id", "tunnels", type_="foreignkey")
    op.drop_column("tunnels", "intermediate_port")
    op.drop_column("tunnels", "intermediate_node_id")
