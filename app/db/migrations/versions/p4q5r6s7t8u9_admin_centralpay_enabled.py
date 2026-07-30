"""Add admins.centralpay_enabled — per-reseller CentralPay opt-in."""

from alembic import op
import sqlalchemy as sa


revision = "p4q5r6s7t8u9"
down_revision = "o3p4q5r6s7t8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("admins") as batch:
        batch.add_column(
            sa.Column(
                "centralpay_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("admins") as batch:
        batch.drop_column("centralpay_enabled")
