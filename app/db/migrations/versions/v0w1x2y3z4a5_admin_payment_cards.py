"""Multi card-to-card: admins.cards JSON array.

Revision ID: v0w1x2y3z4a5
Revises: u9v0w1x2y3z4
Create Date: 2026-07-31
"""

from alembic import op
import sqlalchemy as sa


revision = "v0w1x2y3z4a5"
down_revision = "u9v0w1x2y3z4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("admins") as batch:
        batch.add_column(sa.Column("cards", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("admins") as batch:
        batch.drop_column("cards")
