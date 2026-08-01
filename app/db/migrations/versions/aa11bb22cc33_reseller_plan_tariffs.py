"""Reseller plan wholesale tariffs (separate from master retail Plans).

Revision ID: aa11bb22cc33
Revises: w1x2y3z4a5b6
Create Date: 2026-08-01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "aa11bb22cc33"
down_revision = "w1x2y3z4a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if inspect(bind).has_table("reseller_plan_tariffs"):
        return
    op.create_table(
        "reseller_plan_tariffs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("price", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("data_limit", sa.BigInteger(), nullable=True),
        sa.Column("duration_days", sa.Integer(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if inspect(bind).has_table("reseller_plan_tariffs"):
        op.drop_table("reseller_plan_tariffs")
