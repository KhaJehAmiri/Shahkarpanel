"""sing-box TLS: Let's Encrypt metadata columns

Revision ID: g3h4i5j6k7l8
Revises: 5b1ce0a12003
Create Date: 2026-06-09 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "g3h4i5j6k7l8"
down_revision = "5b1ce0a12003"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "node_singbox",
        sa.Column("tls_trusted", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column("node_singbox", sa.Column("tls_issuer", sa.String(256), nullable=True))
    op.add_column("node_singbox", sa.Column("tls_expires_at", sa.DateTime(), nullable=True))
    op.add_column("node_singbox", sa.Column("tls_le_domain", sa.String(256), nullable=True))


def downgrade():
    op.drop_column("node_singbox", "tls_le_domain")
    op.drop_column("node_singbox", "tls_expires_at")
    op.drop_column("node_singbox", "tls_issuer")
    op.drop_column("node_singbox", "tls_trusted")
