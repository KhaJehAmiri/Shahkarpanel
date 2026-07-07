"""User device/speed limits + per-node Xray override

Revision ID: q4r5s6t7u8v9
Revises: p3q4r5s6t7u8
Create Date: 2026-07-01
"""
from alembic import op
import sqlalchemy as sa


revision = "q4r5s6t7u8v9"
down_revision = "p3q4r5s6t7u8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("device_limit", sa.Integer(), nullable=True))
    op.add_column("users", sa.Column("device_ips", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("speed_limit_up", sa.BigInteger(), nullable=True))
    op.add_column("users", sa.Column("speed_limit_down", sa.BigInteger(), nullable=True))
    op.add_column("nodes", sa.Column("xray_config_override", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("nodes", "xray_config_override")
    op.drop_column("users", "speed_limit_down")
    op.drop_column("users", "speed_limit_up")
    op.drop_column("users", "device_ips")
    op.drop_column("users", "device_limit")
