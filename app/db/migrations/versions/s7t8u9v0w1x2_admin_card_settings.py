"""Per-reseller card-to-card payment settings on admins."""

from alembic import op
import sqlalchemy as sa


revision = "s7t8u9v0w1x2"
down_revision = "r6s7t8u9v0w1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("admins") as batch:
        batch.add_column(
            sa.Column(
                "card_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            )
        )
        batch.add_column(sa.Column("card_number", sa.String(64), nullable=True))
        batch.add_column(sa.Column("card_holder", sa.String(128), nullable=True))
        batch.add_column(sa.Column("card_bank", sa.String(128), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("admins") as batch:
        batch.drop_column("card_bank")
        batch.drop_column("card_holder")
        batch.drop_column("card_number")
        batch.drop_column("card_enabled")
