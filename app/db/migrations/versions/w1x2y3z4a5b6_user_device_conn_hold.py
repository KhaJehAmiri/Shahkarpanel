"""Live 1-device exclusivity hold state on users.

Revision ID: w1x2y3z4a5b6
Revises: v0w1x2y3z4a5
Create Date: 2026-07-31
"""

from alembic import op
import sqlalchemy as sa


revision = "w1x2y3z4a5b6"
down_revision = "v0w1x2y3z4a5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("device_conn_hold", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("device_conn_hold")
