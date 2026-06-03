"""add wireguard to proxytypes enum

Adds the ``WireGuard`` member to the ``proxytypes`` enum used by
``proxies.type`` so WireGuard becomes a first-class user protocol (Phase 11).

SQLAlchemy persists the enum *name* (``WireGuard``), so that is the label added
here — consistent with the existing ``VMess``/``VLESS``/``Trojan``/
``Shadowsocks`` labels. On SQLite the column is a plain ``VARCHAR`` with no
check constraint, so the swap is a harmless no-op there; on PostgreSQL/MySQL it
recreates the native enum type. Mirrors the proven swap pattern from the
``add h3 to alpn enum`` migration.

Revision ID: b1c2d3e4f5a6
Revises: f7a8b9c0d1e2
Create Date: 2026-06-04 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "b1c2d3e4f5a6"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None


enum_name = "proxytypes"
temp_enum_name = "temp_proxytypes"
old_values = ("VMess", "VLESS", "Trojan", "Shadowsocks")
new_values = (*old_values, "WireGuard")

old_type = sa.Enum(*old_values, name=enum_name)
new_type = sa.Enum(*new_values, name=enum_name)
temp_type = sa.Enum(*new_values, name=temp_enum_name)

table_name = "proxies"
column_name = "type"


def _swap(from_type, to_type, temp_name):
    with op.batch_alter_table(table_name) as batch_op:
        batch_op.alter_column(
            column_name,
            existing_type=from_type,
            type_=to_type,
            existing_nullable=False,
            postgresql_using=f"{column_name}::text::{temp_name}",
        )


def upgrade() -> None:
    temp_type.create(op.get_bind(), checkfirst=False)
    _swap(old_type, temp_type, temp_enum_name)
    old_type.drop(op.get_bind(), checkfirst=False)

    new_type.create(op.get_bind(), checkfirst=False)
    _swap(temp_type, new_type, enum_name)
    temp_type.drop(op.get_bind(), checkfirst=False)


def downgrade() -> None:
    # Any WireGuard proxies must go before the label disappears.
    op.execute("DELETE FROM proxies WHERE type = 'WireGuard'")

    temp_type.create(op.get_bind(), checkfirst=False)
    _swap(new_type, temp_type, temp_enum_name)
    new_type.drop(op.get_bind(), checkfirst=False)

    old_type.create(op.get_bind(), checkfirst=False)
    _swap(temp_type, old_type, enum_name)
    temp_type.drop(op.get_bind(), checkfirst=False)
