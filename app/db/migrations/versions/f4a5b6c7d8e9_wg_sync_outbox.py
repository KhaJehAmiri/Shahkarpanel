"""Resumable WireGuard peer sync cursors and outbox.

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-07-20
"""
from alembic import op
import sqlalchemy as sa


revision = "f4a5b6c7d8e9"
down_revision = "e3f4a5b6c7d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "node_sync_cursors",
        sa.Column("node_id", sa.Integer(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("cursor_user_id", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_outbox_id", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("desired_hash", sa.String(length=64), nullable=True),
        sa.Column("applied_hash", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'converged'")),
        sa.Column("peers_done", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("peers_total", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("error", sa.String(length=512), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["node_id"], ["nodes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("node_id"),
    )
    op.create_table(
        "peer_change_outbox",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("op", sa.String(length=16), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("public_key", sa.String(length=128), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_peer_change_outbox_user_id", "peer_change_outbox", ["user_id"])
    op.create_index("ix_peer_change_outbox_public_key", "peer_change_outbox", ["public_key"])
    op.create_index("ix_peer_change_outbox_created_at", "peer_change_outbox", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_peer_change_outbox_created_at", table_name="peer_change_outbox")
    op.drop_index("ix_peer_change_outbox_public_key", table_name="peer_change_outbox")
    op.drop_index("ix_peer_change_outbox_user_id", table_name="peer_change_outbox")
    op.drop_table("peer_change_outbox")
    op.drop_table("node_sync_cursors")
