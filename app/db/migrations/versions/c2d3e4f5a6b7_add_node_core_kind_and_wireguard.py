"""add node core_kind and node_wireguard table

Phase 11.3 — gives each node a ``core_kind`` ('xray' default | 'wireguard') and
adds a one-to-one ``node_wireguard`` table holding the per-node native
WireGuard server config. Non-WG nodes carry no row in ``node_wireguard``.

Cross-dialect (SQLite / PostgreSQL / MySQL): ``core_kind`` is a plain VARCHAR
with a server default of 'xray' so existing rows backfill automatically.

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-06-04 00:30:00.000000

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c2d3e4f5a6b7"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "nodes",
        sa.Column(
            "core_kind",
            sa.String(length=16),
            nullable=False,
            server_default="xray",
        ),
    )
    op.create_table(
        "node_wireguard",
        sa.Column("node_id", sa.Integer(), nullable=False),
        sa.Column("interface", sa.String(length=32), nullable=False, server_default="wg0"),
        sa.Column("listen_port", sa.Integer(), nullable=False, server_default="51820"),
        sa.Column("subnet", sa.String(length=64), nullable=False, server_default="10.10.0.0/24"),
        sa.Column("private_key", sa.String(length=64), nullable=False),
        sa.Column("public_key", sa.String(length=64), nullable=False),
        sa.Column("endpoint", sa.String(length=256), nullable=True),
        sa.Column("mtu", sa.Integer(), nullable=False, server_default="1420"),
        sa.Column("dns", sa.String(length=256), nullable=True),
        sa.ForeignKeyConstraint(["node_id"], ["nodes.id"]),
        sa.PrimaryKeyConstraint("node_id"),
    )


def downgrade() -> None:
    op.drop_table("node_wireguard")
    op.drop_column("nodes", "core_kind")
