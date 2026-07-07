"""Host external_proxy chain (3x-ui externalProxy parity)

Revision ID: r5s6t7u8v9w0
Revises: q4r5s6t7u8v9
Create Date: 2026-07-01
"""
from alembic import op
import sqlalchemy as sa


revision = "r5s6t7u8v9w0"
down_revision = "q4r5s6t7u8v9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("hosts", sa.Column("external_proxy", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("hosts", "external_proxy")
