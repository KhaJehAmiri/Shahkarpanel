"""Public storefront: invite codes, signup flags, reseller applications.

Revision ID: dd44ee55ff66
Revises: cc33dd44ee55
Create Date: 2026-08-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = "dd44ee55ff66"
down_revision = "ee55ff66aa77"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in inspect(bind).get_columns("admins")}
    if "invite_code" not in cols:
        op.add_column("admins", sa.Column("invite_code", sa.String(length=32), nullable=True))
        op.create_index("ix_admins_invite_code", "admins", ["invite_code"], unique=True)
    if "public_signup_enabled" not in cols:
        op.add_column(
            "admins",
            sa.Column(
                "public_signup_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=text("true"),
            ),
        )
    if "reseller_apply_enabled" not in cols:
        op.add_column(
            "admins",
            sa.Column(
                "reseller_apply_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=text("true"),
            ),
        )
    if "storefront_headline" not in cols:
        op.add_column("admins", sa.Column("storefront_headline", sa.String(length=256), nullable=True))
    if "storefront_tagline" not in cols:
        op.add_column("admins", sa.Column("storefront_tagline", sa.String(length=512), nullable=True))

    if not inspect(bind).has_table("reseller_applications"):
        op.create_table(
            "reseller_applications",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("username", sa.String(length=34), nullable=False),
            sa.Column("password_plain", sa.String(length=128), nullable=True),
            sa.Column("display_name", sa.String(length=128), nullable=True),
            sa.Column("contact", sa.String(length=256), nullable=True),
            sa.Column("message", sa.Text(), nullable=True),
            sa.Column(
                "status",
                sa.String(length=16),
                nullable=False,
                server_default=text("'pending'"),
            ),
            sa.Column("parent_admin_id", sa.Integer(), sa.ForeignKey("admins.id"), nullable=True),
            sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=True),
            sa.Column("invite_code", sa.String(length=32), nullable=True),
            sa.Column("created_admin_id", sa.Integer(), sa.ForeignKey("admins.id"), nullable=True),
            sa.Column("reviewed_by_admin_id", sa.Integer(), sa.ForeignKey("admins.id"), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(), nullable=True),
            sa.Column("reject_reason", sa.String(length=256), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_reseller_applications_username", "reseller_applications", ["username"])
        op.create_index("ix_reseller_applications_status", "reseller_applications", ["status"])
        op.create_index(
            "ix_reseller_applications_parent_admin_id",
            "reseller_applications",
            ["parent_admin_id"],
        )
        op.create_index("ix_reseller_applications_tenant_id", "reseller_applications", ["tenant_id"])
        op.create_index("ix_reseller_applications_created_at", "reseller_applications", ["created_at"])


def downgrade() -> None:
    bind = op.get_bind()
    if inspect(bind).has_table("reseller_applications"):
        op.drop_table("reseller_applications")
    cols = {c["name"] for c in inspect(bind).get_columns("admins")}
    for name, index in (
        ("invite_code", "ix_admins_invite_code"),
        ("public_signup_enabled", None),
        ("reseller_apply_enabled", None),
        ("storefront_headline", None),
        ("storefront_tagline", None),
    ):
        if name in cols:
            if index:
                try:
                    op.drop_index(index, table_name="admins")
                except Exception:
                    pass
            op.drop_column("admins", name)
