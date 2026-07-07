"""Add optional region code on proxy hosts (location without a node).

Revision ID: y3z4a5b6c7d8
Revises: x2y3z4a5b6c7
"""
from alembic import op
import sqlalchemy as sa


revision = "y3z4a5b6c7d8"
down_revision = "x2y3z4a5b6c7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("hosts", sa.Column("region", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("hosts", "region")
