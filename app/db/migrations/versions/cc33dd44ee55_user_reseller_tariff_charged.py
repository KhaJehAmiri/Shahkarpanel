"""Track last wholesale tariff charged per user (anti bypass).

Revision ID: cc33dd44ee55
Revises: bb22cc33dd44
Create Date: 2026-08-01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "cc33dd44ee55"
down_revision = "bb22cc33dd44"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in inspect(bind).get_columns("users")}
    if "reseller_tariff_charged_id" not in cols:
        op.add_column(
            "users",
            sa.Column("reseller_tariff_charged_id", sa.Integer(), nullable=True),
        )
        op.create_foreign_key(
            "fk_users_reseller_tariff_charged_id",
            "users",
            "reseller_plan_tariffs",
            ["reseller_tariff_charged_id"],
            ["id"],
            ondelete="SET NULL",
        )
    if "reseller_tariff_charged_expire" not in cols:
        op.add_column(
            "users",
            sa.Column("reseller_tariff_charged_expire", sa.Integer(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in inspect(bind).get_columns("users")}
    if "reseller_tariff_charged_id" in cols:
        try:
            op.drop_constraint(
                "fk_users_reseller_tariff_charged_id", "users", type_="foreignkey"
            )
        except Exception:
            pass
        op.drop_column("users", "reseller_tariff_charged_id")
    if "reseller_tariff_charged_expire" in cols:
        op.drop_column("users", "reseller_tariff_charged_expire")
