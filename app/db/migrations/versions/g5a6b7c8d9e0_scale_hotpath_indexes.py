"""High-volume indexes for users/proxies hot paths.

Revision ID: g5a6b7c8d9e0
Revises: f4a5b6c7d8e9
Create Date: 2026-07-20
"""
from alembic import op


revision = "g5a6b7c8d9e0"
down_revision = "f4a5b6c7d8e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Proxy lookups (WG collect, joins)
    op.create_index("ix_proxies_type", "proxies", ["type"], unique=False)
    op.create_index("ix_proxies_user_id", "proxies", ["user_id"], unique=False)
    # Review / expire / quota candidate queries
    op.create_index("ix_users_expire", "users", ["expire"], unique=False)
    op.create_index("ix_users_status_expire", "users", ["status", "expire"], unique=False)
    op.create_index(
        "ix_users_status_online_at",
        "users",
        ["status", "online_at"],
        unique=False,
    )
    # Partial-ish help for quota: status + data_limit (used_traffic compared in filter)
    op.create_index(
        "ix_users_status_data_limit",
        "users",
        ["status", "data_limit"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_users_status_data_limit", table_name="users")
    op.drop_index("ix_users_status_online_at", table_name="users")
    op.drop_index("ix_users_status_expire", table_name="users")
    op.drop_index("ix_users_expire", table_name="users")
    op.drop_index("ix_proxies_user_id", table_name="proxies")
    op.drop_index("ix_proxies_type", table_name="proxies")
