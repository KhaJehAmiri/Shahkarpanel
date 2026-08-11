"""Add per-node WARP exit mode (full vs sensitive) and widen warp_tag for multi-account LB.

Revision ID: ii99dd00ee11
Revises: hh88cc99dd00
Create Date: 2026-08-08
"""
from alembic import op
import sqlalchemy as sa


revision = "ii99dd00ee11"
down_revision = "hh88cc99dd00"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "nodes",
        sa.Column(
            "warp_mode",
            sa.String(length=16),
            nullable=False,
            server_default="full",
        ),
    )
    # Allow comma-separated tags: warp,warp-2,warp-3
    op.alter_column(
        "nodes",
        "warp_tag",
        existing_type=sa.String(length=64),
        type_=sa.String(length=512),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "nodes",
        "warp_tag",
        existing_type=sa.String(length=512),
        type_=sa.String(length=64),
        existing_nullable=True,
    )
    op.drop_column("nodes", "warp_mode")
