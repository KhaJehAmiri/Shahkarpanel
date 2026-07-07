"""Admin TOTP 2FA secret (opt-in)

Revision ID: o2p3q4r5s6t7
Revises: n1o2p3q4r5s6
Create Date: 2026-07-01
"""
from alembic import op
import sqlalchemy as sa


revision = "o2p3q4r5s6t7"
down_revision = "n1o2p3q4r5s6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("admins", sa.Column("totp_secret", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("admins", "totp_secret")
