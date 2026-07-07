"""Host fields for 3x-ui parity (CDN overrides, export extras)

Revision ID: m0n1o2p3q4r5
Revises: l9m0n1o2p3q4
Create Date: 2026-07-01
"""
from alembic import op
import sqlalchemy as sa


revision = "m0n1o2p3q4r5"
down_revision = "l9m0n1o2p3q4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "ALTER TYPE proxyhostsecurity ADD VALUE IF NOT EXISTS 'reality'"
        )
        op.execute(
            "ALTER TYPE proxyhostsecurity ADD VALUE IF NOT EXISTS 'same'"
        )

    op.add_column(
        "hosts",
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "hosts",
        sa.Column(
            "override_sni_from_address",
            sa.Boolean(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "hosts",
        sa.Column(
            "keep_sni_blank",
            sa.Boolean(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column("hosts", sa.Column("pinned_peer_cert_sha256", sa.Text(), nullable=True))
    op.add_column(
        "hosts",
        sa.Column("verify_peer_cert_by_name", sa.String(length=256), nullable=True),
    )
    op.add_column("hosts", sa.Column("ech_config_list", sa.Text(), nullable=True))
    op.add_column("hosts", sa.Column("mux_params", sa.Text(), nullable=True))
    op.add_column("hosts", sa.Column("sockopt_params", sa.Text(), nullable=True))
    op.add_column("hosts", sa.Column("final_mask", sa.Text(), nullable=True))
    op.add_column("hosts", sa.Column("vless_route", sa.String(length=16), nullable=True))
    op.add_column("hosts", sa.Column("exclude_from_sub_types", sa.Text(), nullable=True))
    op.add_column(
        "hosts",
        sa.Column("mihomo_ip_version", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("hosts", "mihomo_ip_version")
    op.drop_column("hosts", "exclude_from_sub_types")
    op.drop_column("hosts", "vless_route")
    op.drop_column("hosts", "final_mask")
    op.drop_column("hosts", "sockopt_params")
    op.drop_column("hosts", "mux_params")
    op.drop_column("hosts", "ech_config_list")
    op.drop_column("hosts", "verify_peer_cert_by_name")
    op.drop_column("hosts", "pinned_peer_cert_sha256")
    op.drop_column("hosts", "keep_sni_blank")
    op.drop_column("hosts", "override_sni_from_address")
    op.drop_column("hosts", "sort_order")
