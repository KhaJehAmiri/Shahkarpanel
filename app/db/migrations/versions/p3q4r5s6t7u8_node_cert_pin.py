"""Node TLS cert pinning (server_cert_sha256)

Revision ID: p3q4r5s6t7u8
Revises: o2p3q4r5s6t7
Create Date: 2026-07-01
"""
from alembic import op
import sqlalchemy as sa


revision = "p3q4r5s6t7u8"
down_revision = "o2p3q4r5s6t7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("nodes", sa.Column("server_cert_sha256", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("nodes", "server_cert_sha256")
