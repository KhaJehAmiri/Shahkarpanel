"""Per-inbound subscription endpoints and legacy token aliases.

Revision ID: w0x1y2z3a4b5
Revises: v9w0x1y2z3a4
Create Date: 2026-07-05
"""
from alembic import op
import sqlalchemy as sa


revision = "w0x1y2z3a4b5"
down_revision = "v9w0x1y2z3a4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "subscription_endpoints",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("host", sa.String(255), nullable=True),
        sa.Column("path_prefix", sa.String(64), nullable=False),
        sa.Column("public_base_url", sa.String(512), nullable=False, server_default=""),
        sa.Column("listen_port", sa.Integer(), nullable=True),
        sa.Column("inbound_tag", sa.String(64), nullable=True),
        sa.Column("export_mode", sa.String(32), nullable=False, server_default="full"),
        sa.Column("format_default", sa.String(32), nullable=True),
        sa.Column("legacy_panel_id", sa.String(64), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_subscription_endpoints_slug"),
    )
    op.create_index(
        "ix_subscription_endpoints_path_prefix",
        "subscription_endpoints",
        ["path_prefix"],
        unique=False,
    )
    op.create_index(
        "ix_subscription_endpoints_host_path",
        "subscription_endpoints",
        ["host", "path_prefix"],
        unique=True,
    )

    op.create_table(
        "subscription_token_aliases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("token", sa.String(256), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("endpoint_id", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(64), nullable=False, server_default="manual"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["endpoint_id"], ["subscription_endpoints.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "endpoint_id", "token", name="uq_subscription_token_aliases_endpoint_token"
        ),
    )
    op.create_index(
        "ix_subscription_token_aliases_token",
        "subscription_token_aliases",
        ["token"],
        unique=False,
    )
    op.create_index(
        "ix_subscription_token_aliases_user_id",
        "subscription_token_aliases",
        ["user_id"],
        unique=False,
    )

    op.execute(
        """
        INSERT INTO subscription_endpoints
            (slug, host, path_prefix, public_base_url, export_mode, enabled, created_at)
        VALUES
            ('default', NULL, 'sub', '', 'full', true, NOW())
        """
    )


def downgrade() -> None:
    op.drop_index("ix_subscription_token_aliases_user_id", table_name="subscription_token_aliases")
    op.drop_index("ix_subscription_token_aliases_token", table_name="subscription_token_aliases")
    op.drop_table("subscription_token_aliases")
    op.drop_index("ix_subscription_endpoints_host_path", table_name="subscription_endpoints")
    op.drop_index("ix_subscription_endpoints_path_prefix", table_name="subscription_endpoints")
    op.drop_table("subscription_endpoints")
