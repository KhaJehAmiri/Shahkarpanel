"""Add locked device/speed limits on reseller wholesale tariffs.

Revision ID: bb22cc33dd44
Revises: aa11bb22cc33
Create Date: 2026-08-01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "bb22cc33dd44"
down_revision = "aa11bb22cc33"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    if not insp.has_table("reseller_plan_tariffs"):
        return
    cols = {c["name"] for c in insp.get_columns("reseller_plan_tariffs")}
    with op.batch_alter_table("reseller_plan_tariffs") as batch:
        if "device_limit" not in cols:
            batch.add_column(sa.Column("device_limit", sa.Integer(), nullable=True))
        if "speed_limit_up" not in cols:
            batch.add_column(sa.Column("speed_limit_up", sa.BigInteger(), nullable=True))
        if "speed_limit_down" not in cols:
            batch.add_column(sa.Column("speed_limit_down", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    if not insp.has_table("reseller_plan_tariffs"):
        return
    cols = {c["name"] for c in insp.get_columns("reseller_plan_tariffs")}
    with op.batch_alter_table("reseller_plan_tariffs") as batch:
        if "speed_limit_down" in cols:
            batch.drop_column("speed_limit_down")
        if "speed_limit_up" in cols:
            batch.drop_column("speed_limit_up")
        if "device_limit" in cols:
            batch.drop_column("device_limit")
