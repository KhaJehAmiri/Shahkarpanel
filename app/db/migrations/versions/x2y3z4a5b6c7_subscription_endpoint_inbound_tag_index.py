"""Index subscription_endpoints.inbound_tag (per-inbound Listen Domain/Port/URI Path lookups).

Revision ID: x2y3z4a5b6c7
Revises: w0x1y2z3a4b5
Create Date: 2026-07-05
"""
from alembic import op


revision = "x2y3z4a5b6c7"
down_revision = "w0x1y2z3a4b5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_subscription_endpoints_inbound_tag",
        "subscription_endpoints",
        ["inbound_tag"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_subscription_endpoints_inbound_tag", table_name="subscription_endpoints")
