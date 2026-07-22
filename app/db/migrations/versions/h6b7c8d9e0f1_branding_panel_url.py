"""Add panel_url to branding_settings.

Revision ID: h6b7c8d9e0f1
Revises: g5a6b7c8d9e0
Create Date: 2026-07-21
"""
from alembic import op
import sqlalchemy as sa


revision = "h6b7c8d9e0f1"
down_revision = "g5a6b7c8d9e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "branding_settings",
        sa.Column("panel_url", sa.String(length=512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("branding_settings", "panel_url")
