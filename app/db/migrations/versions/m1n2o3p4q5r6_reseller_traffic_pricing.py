"""Per-reseller traffic pricing overrides.

Revision ID: m1n2o3p4q5r6
Revises: l0m1n2o3p4q5
Create Date: 2026-07-27
"""
from alembic import op
import sqlalchemy as sa


revision = "m1n2o3p4q5r6"
down_revision = "l0m1n2o3p4q5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "admins",
        sa.Column("usage_rate_per_gb", sa.BigInteger(), nullable=True),
    )
    op.create_table(
        "reseller_traffic_package_overrides",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("admin_id", sa.Integer(), sa.ForeignKey("admins.id"), nullable=False, index=True),
        sa.Column(
            "package_id",
            sa.Integer(),
            sa.ForeignKey("reseller_traffic_packages.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("price", sa.BigInteger(), nullable=True),
        sa.Column("bytes", sa.BigInteger(), nullable=True),
        sa.UniqueConstraint("admin_id", "package_id", name="uq_reseller_pkg_override"),
    )


def downgrade() -> None:
    op.drop_table("reseller_traffic_package_overrides")
    op.drop_column("admins", "usage_rate_per_gb")
