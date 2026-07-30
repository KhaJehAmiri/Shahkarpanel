"""Add users.portal_owner_user_id for portal multi-account ownership."""

from alembic import op
import sqlalchemy as sa


revision = "n2o3p4q5r6s7"
down_revision = "m1n2o3p4q5r6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column("portal_owner_user_id", sa.Integer(), nullable=True)
        )
        batch.create_foreign_key(
            "fk_users_portal_owner_user_id",
            "users",
            ["portal_owner_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_users_portal_owner_user_id", ["portal_owner_user_id"])


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_index("ix_users_portal_owner_user_id")
        batch.drop_constraint("fk_users_portal_owner_user_id", type_="foreignkey")
        batch.drop_column("portal_owner_user_id")
