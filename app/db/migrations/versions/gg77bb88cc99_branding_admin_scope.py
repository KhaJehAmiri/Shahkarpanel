"""Per-admin branding for sub-resellers (isolate sub domain/title).

Revision ID: gg77bb88cc99
Revises: ff66aa77bb88
Create Date: 2026-08-05
"""
from alembic import op
import sqlalchemy as sa


revision = "gg77bb88cc99"
down_revision = "ff66aa77bb88"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "branding_settings",
        sa.Column("admin_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_branding_settings_admin_id",
        "branding_settings",
        "admins",
        ["admin_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_branding_settings_admin_id",
        "branding_settings",
        ["admin_id"],
        unique=False,
    )

    # Replace tenant-wide uniqueness so one tenant can have:
    # - one default row (admin_id IS NULL) for the owner reseller
    # - one row per sub-reseller (admin_id set)
    try:
        op.drop_constraint("uq_branding_tenant", "branding_settings", type_="unique")
    except Exception:
        pass

    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "postgresql":
        op.execute(
            sa.text(
                "CREATE UNIQUE INDEX uq_branding_tenant_default "
                "ON branding_settings (tenant_id) WHERE admin_id IS NULL"
            )
        )
        op.execute(
            sa.text(
                "CREATE UNIQUE INDEX uq_branding_admin "
                "ON branding_settings (admin_id) WHERE admin_id IS NOT NULL"
            )
        )
    else:
        # SQLite: partial unique indexes supported since 3.8+.
        op.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_branding_tenant_default "
            "ON branding_settings (tenant_id) WHERE admin_id IS NULL"
        )
        op.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_branding_admin "
            "ON branding_settings (admin_id) WHERE admin_id IS NOT NULL"
        )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_branding_admin")
    op.execute("DROP INDEX IF EXISTS uq_branding_tenant_default")
    op.drop_index("ix_branding_settings_admin_id", table_name="branding_settings")
    op.drop_constraint("fk_branding_settings_admin_id", "branding_settings", type_="foreignkey")
    op.drop_column("branding_settings", "admin_id")
    op.create_unique_constraint("uq_branding_tenant", "branding_settings", ["tenant_id"])
