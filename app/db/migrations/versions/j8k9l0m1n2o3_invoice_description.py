"""Add description to invoices.

Revision ID: j8k9l0m1n2o3
Revises: i7j8k9l0m1n2
Create Date: 2026-07-22
"""
from alembic import op
import sqlalchemy as sa


revision = "j8k9l0m1n2o3"
down_revision = "i7j8k9l0m1n2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "invoices",
        sa.Column("description", sa.String(length=512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("invoices", "description")
