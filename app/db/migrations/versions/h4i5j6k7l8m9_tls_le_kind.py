"""sing-box TLS: LE target kind (domain | ip)

Revision ID: h4i5j6k7l8m9
Revises: g3h4i5j6k7l8
Create Date: 2026-06-09 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "h4i5j6k7l8m9"
down_revision = "g3h4i5j6k7l8"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("node_singbox", sa.Column("tls_le_kind", sa.String(16), nullable=True))


def downgrade():
    op.drop_column("node_singbox", "tls_le_kind")
