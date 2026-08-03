"""Add users.family_controls JSON for portal Family Guard.

Revision ID: ee55ff66aa77
Revises: dd44ee55ff66
Create Date: 2026-08-03
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "ee55ff66aa77"
down_revision = "cc33dd44ee55"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in inspect(bind).get_columns("users")}
    if "family_controls" not in cols:
        op.add_column("users", sa.Column("family_controls", sa.JSON(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in inspect(bind).get_columns("users")}
    if "family_controls" in cols:
        op.drop_column("users", "family_controls")
