"""Add per-node WARP exit settings.

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-07-15
"""
from alembic import op
import sqlalchemy as sa


revision = "e3f4a5b6c7d8"
down_revision = "d2e3f4a5b6c7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "nodes",
        sa.Column(
            "warp_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "nodes",
        sa.Column("warp_tag", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("nodes", "warp_tag")
    op.drop_column("nodes", "warp_enabled")
