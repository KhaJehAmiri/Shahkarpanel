"""Bill from Admin.users_usage delta (all connection paths).

Revision ID: k9l0m1n2o3p4
Revises: j8k9l0m1n2o3
Create Date: 2026-07-22
"""
from alembic import op
import sqlalchemy as sa


revision = "k9l0m1n2o3p4"
down_revision = "j8k9l0m1n2o3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "usage_billing_checkpoints",
        sa.Column(
            "last_billed_users_usage",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
    )
    # Avoid one-shot billing of all historical traffic: watermark = current usage.
    op.execute(
        """
        UPDATE usage_billing_checkpoints AS c
        SET last_billed_users_usage = COALESCE(a.users_usage, 0)
        FROM admins AS a
        WHERE a.id = c.admin_id
        """
    )


def downgrade() -> None:
    op.drop_column("usage_billing_checkpoints", "last_billed_users_usage")
