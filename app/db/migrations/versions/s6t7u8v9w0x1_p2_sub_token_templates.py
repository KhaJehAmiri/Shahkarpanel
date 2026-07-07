"""P2: sub_token, template fields, session_limit

Revision ID: s6t7u8v9w0x1
Revises: r5s6t7u8v9w0
Create Date: 2026-07-01
"""
import secrets

from alembic import op
import sqlalchemy as sa


revision = "s6t7u8v9w0x1"
down_revision = "r5s6t7u8v9w0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("sub_token", sa.String(32), nullable=True))
    op.create_index("ix_users_sub_token", "users", ["sub_token"], unique=True)
    op.add_column("users", sa.Column("session_limit_minutes", sa.Integer(), nullable=True))

    op.add_column(
        "user_templates",
        sa.Column(
            "data_limit_reset_strategy",
            sa.Enum(
                "no_reset",
                "day",
                "week",
                "month",
                "year",
                name="userdatalimitresetstrategy",
                create_type=False,
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "user_templates",
        sa.Column(
            "default_status",
            sa.Enum("active", "disabled", "on_hold", name="userstatus", create_type=False),
            nullable=True,
        ),
    )
    op.add_column("user_templates", sa.Column("note", sa.String(500), nullable=True))
    op.add_column("user_templates", sa.Column("next_plan", sa.JSON(), nullable=True))

    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id FROM users WHERE sub_token IS NULL"))
    for row in rows:
        conn.execute(
            sa.text("UPDATE users SET sub_token = :tok WHERE id = :id"),
            {"tok": secrets.token_hex(16), "id": row.id},
        )


def downgrade() -> None:
    op.drop_column("user_templates", "next_plan")
    op.drop_column("user_templates", "note")
    op.drop_column("user_templates", "default_status")
    op.drop_column("user_templates", "data_limit_reset_strategy")
    op.drop_column("users", "session_limit_minutes")
    op.drop_index("ix_users_sub_token", table_name="users")
    op.drop_column("users", "sub_token")
