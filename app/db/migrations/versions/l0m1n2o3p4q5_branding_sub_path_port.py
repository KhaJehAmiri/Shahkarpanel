"""Add subscription path/port to branding_settings.

Revision ID: l0m1n2o3p4q5
Revises: k9l0m1n2o3p4
Create Date: 2026-07-23
"""
from alembic import op
import sqlalchemy as sa


revision = "l0m1n2o3p4q5"
down_revision = "k9l0m1n2o3p4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "branding_settings",
        sa.Column("sub_path", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "branding_settings",
        sa.Column("sub_port", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("branding_settings", "sub_port")
    op.drop_column("branding_settings", "sub_path")
