"""Durable user_sync_outbox + users.sync_state (phase 2).

Revision ID: kk11ff22aa33
Revises: jj00ee11ff22
Create Date: 2026-08-19
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "kk11ff22aa33"
down_revision = "jj00ee11ff22"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "sync_state",
            sa.String(length=16),
            nullable=False,
            server_default="live",
        ),
    )
    op.add_column("users", sa.Column("sync_error", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("sync_acked_at", sa.DateTime(), nullable=True))

    bind = op.get_bind()
    json_type = (
        postgresql.JSONB() if bind.dialect.name == "postgresql" else sa.JSON()
    )
    op.create_table(
        "user_sync_outbox",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("target", sa.String(length=16), nullable=False, server_default="all"),
        sa.Column("node_id", sa.Integer(), nullable=True),
        sa.Column("shard_or_tag", sa.String(length=128), nullable=True),
        sa.Column("payload", json_type, nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_retry_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("acked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_user_sync_outbox_drain",
        "user_sync_outbox",
        ["status", "next_retry_at"],
    )
    op.create_index("ix_user_sync_outbox_user", "user_sync_outbox", ["user_id"])
    if bind.dialect.name == "postgresql":
        op.execute(
            sa.text(
                """
                CREATE UNIQUE INDEX uq_user_sync_outbox_pending
                ON user_sync_outbox (
                    user_id,
                    action,
                    target,
                    COALESCE(node_id, 0)
                )
                WHERE status IN ('pending', 'running')
                """
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(sa.text("DROP INDEX IF EXISTS uq_user_sync_outbox_pending"))
    op.drop_index("ix_user_sync_outbox_user", table_name="user_sync_outbox")
    op.drop_index("ix_user_sync_outbox_drain", table_name="user_sync_outbox")
    op.drop_table("user_sync_outbox")
    op.drop_column("users", "sync_acked_at")
    op.drop_column("users", "sync_error")
    op.drop_column("users", "sync_state")
