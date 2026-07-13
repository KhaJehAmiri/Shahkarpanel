"""Fix xray_wg_noise column type: json -> jsonb.

Plain ``json`` has no equality operator in Postgres, which breaks every
``.distinct()`` query over ``node_wireguard`` (e.g. ``crud.get_wireguard_nodes``)
with "could not identify an equality operator for type json" as soon as any
row has this column populated.

Revision ID: b6c7d8e9f0a1
Revises: a5b6c7d8e9f0
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "b6c7d8e9f0a1"
down_revision = "a5b6c7d8e9f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "node_wireguard",
        "xray_wg_noise",
        type_=postgresql.JSONB(),
        existing_type=sa.JSON(),
        postgresql_using="xray_wg_noise::jsonb",
    )


def downgrade() -> None:
    op.alter_column(
        "node_wireguard",
        "xray_wg_noise",
        type_=sa.JSON(),
        existing_type=postgresql.JSONB(),
        postgresql_using="xray_wg_noise::json",
    )
