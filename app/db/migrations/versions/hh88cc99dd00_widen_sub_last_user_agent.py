"""Widen users.sub_last_user_agent to the model length (512).

The 2023 widening only ran on MySQL, so Postgres installs kept the original
varchar(64). Any subscription fetch from a client with a longer User-Agent
(browsers, Karing, bots) then failed the UPDATE and returned 500 instead of
the user's configs.

Revision ID: hh88cc99dd00
Revises: gg77bb88cc99
Create Date: 2026-08-06
"""
from alembic import op
import sqlalchemy as sa


revision = "hh88cc99dd00"
down_revision = "gg77bb88cc99"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return
    op.alter_column(
        "users",
        "sub_last_user_agent",
        existing_type=sa.String(length=64),
        type_=sa.String(length=512),
        existing_nullable=True,
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return
    op.execute(
        sa.text("UPDATE users SET sub_last_user_agent = left(sub_last_user_agent, 64)")
        if bind.dialect.name == "postgresql"
        else sa.text("UPDATE users SET sub_last_user_agent = LEFT(sub_last_user_agent, 64)")
    )
    op.alter_column(
        "users",
        "sub_last_user_agent",
        existing_type=sa.String(length=512),
        type_=sa.String(length=64),
        existing_nullable=True,
    )
