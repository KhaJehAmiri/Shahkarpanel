"""SigmaGuard Wire node fields + AWG S3/S4

Revision ID: k8l9m0n1o2p3
Revises: j6k7l8m9n0o1
Create Date: 2026-06-10 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "k8l9m0n1o2p3"
down_revision = "j6k7l8m9n0o1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("node_wireguard", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("sg_wire_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false"))
        )
        batch_op.add_column(sa.Column("sg_wire_preset_rev", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("awg_s3", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("awg_s4", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("node_wireguard", schema=None) as batch_op:
        batch_op.drop_column("awg_s4")
        batch_op.drop_column("awg_s3")
        batch_op.drop_column("sg_wire_preset_rev")
        batch_op.drop_column("sg_wire_enabled")
