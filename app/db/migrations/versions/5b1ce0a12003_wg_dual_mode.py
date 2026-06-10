"""WireGuard dual mode: plain wg0 + AmneziaWG wg1 on separate ports

Revision ID: 5b1ce0a12003
Revises: 5b1ce0a12002
Create Date: 2026-06-08 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "5b1ce0a12003"
down_revision = "5b1ce0a12002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("node_wireguard", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("plain_enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        )
        batch_op.add_column(
            sa.Column("awg_enabled", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        )
        batch_op.add_column(
            sa.Column("awg_interface", sa.String(length=32), nullable=False, server_default=sa.text("'wg1'")),
        )
        batch_op.add_column(
            sa.Column("awg_listen_port", sa.Integer(), nullable=False, server_default=sa.text("51821")),
        )
        batch_op.add_column(
            sa.Column("awg_subnet", sa.String(length=64), nullable=False, server_default=sa.text("'10.11.0.0/24'")),
        )
        batch_op.add_column(sa.Column("awg_private_key", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("awg_public_key", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("awg_endpoint", sa.String(length=256), nullable=True))

    # Nodes that already had AWG obfuscation params were single-mode AWG; enable
    # dual stack so plain WG can coexist on a separate port.
    op.execute(
        "UPDATE node_wireguard SET awg_enabled = 1 "
        "WHERE awg_jc IS NOT NULL OR awg_jmin IS NOT NULL OR awg_jmax IS NOT NULL "
        "OR awg_s1 IS NOT NULL OR awg_s2 IS NOT NULL "
        "OR awg_h1 IS NOT NULL OR awg_h2 IS NOT NULL OR awg_h3 IS NOT NULL OR awg_h4 IS NOT NULL"
    )


def downgrade() -> None:
    with op.batch_alter_table("node_wireguard", schema=None) as batch_op:
        batch_op.drop_column("awg_endpoint")
        batch_op.drop_column("awg_public_key")
        batch_op.drop_column("awg_private_key")
        batch_op.drop_column("awg_subnet")
        batch_op.drop_column("awg_listen_port")
        batch_op.drop_column("awg_interface")
        batch_op.drop_column("awg_enabled")
        batch_op.drop_column("plain_enabled")
