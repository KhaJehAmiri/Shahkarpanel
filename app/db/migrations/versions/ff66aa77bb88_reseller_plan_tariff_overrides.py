"""Per-reseller wholesale tariff price overrides.

Revision ID: ff66aa77bb88
Revises: dd44ee55ff66
Create Date: 2026-08-04
"""
from alembic import op
import sqlalchemy as sa


revision = "ff66aa77bb88"
down_revision = "dd44ee55ff66"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reseller_plan_tariff_overrides",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("admin_id", sa.Integer(), sa.ForeignKey("admins.id"), nullable=False, index=True),
        sa.Column(
            "tariff_id",
            sa.Integer(),
            sa.ForeignKey("reseller_plan_tariffs.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("price", sa.BigInteger(), nullable=True),
        sa.UniqueConstraint("admin_id", "tariff_id", name="uq_reseller_tariff_override"),
    )


def downgrade() -> None:
    op.drop_table("reseller_plan_tariff_overrides")
