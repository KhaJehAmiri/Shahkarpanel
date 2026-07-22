"""Reseller prepaid traffic packages.

Revision ID: i7j8k9l0m1n2
Revises: h6b7c8d9e0f1
Create Date: 2026-07-22
"""
from alembic import op
import sqlalchemy as sa


revision = "i7j8k9l0m1n2"
down_revision = "h6b7c8d9e0f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "admins",
        sa.Column(
            "prepaid_traffic_remaining",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_table(
        "reseller_traffic_packages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("bytes", sa.BigInteger(), nullable=False),
        sa.Column("price", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "reseller_traffic_purchases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("admin_id", sa.Integer(), sa.ForeignKey("admins.id"), nullable=False),
        sa.Column(
            "package_id",
            sa.Integer(),
            sa.ForeignKey("reseller_traffic_packages.id"),
            nullable=True,
        ),
        sa.Column("bytes", sa.BigInteger(), nullable=False),
        sa.Column("price_paid", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("source", sa.String(length=16), nullable=False, server_default="purchase"),
        sa.Column(
            "created_by_admin_id",
            sa.Integer(),
            sa.ForeignKey("admins.id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_reseller_traffic_purchases_admin_id",
        "reseller_traffic_purchases",
        ["admin_id"],
    )
    op.create_index(
        "ix_reseller_traffic_purchases_created_at",
        "reseller_traffic_purchases",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_reseller_traffic_purchases_created_at", table_name="reseller_traffic_purchases")
    op.drop_index("ix_reseller_traffic_purchases_admin_id", table_name="reseller_traffic_purchases")
    op.drop_table("reseller_traffic_purchases")
    op.drop_table("reseller_traffic_packages")
    op.drop_column("admins", "prepaid_traffic_remaining")
