"""Mark users auto-disabled because their reseller hit its total-traffic cap.

Lets reseller total-traffic enforcement be reversible: only users this flag
marks are auto-reactivated when the reseller drops back under its cap, so an
admin's own manual disables are never silently re-enabled.

Revision ID: c1d2e3f4a5b6
Revises: b6c7d8e9f0a1
Create Date: 2026-07-14
"""
from alembic import op
import sqlalchemy as sa


revision = "c1d2e3f4a5b6"
down_revision = "b6c7d8e9f0a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "capped_by_reseller",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "capped_by_reseller")
