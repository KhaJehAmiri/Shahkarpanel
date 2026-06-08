"""add hysteria2 and tuic to proxytypes enum

Adds the ``Hysteria2`` and ``TUIC`` members to the ``proxytypes`` enum used by
``proxies.type`` so the sing-box product protocols become first-class user
protocols (alongside ``WireGuard``).

SQLAlchemy persists the enum *name* (``Hysteria2`` / ``TUIC``). On SQLite the
column is a plain ``VARCHAR`` with no check constraint, so the swap is a
harmless no-op; on PostgreSQL/MySQL it recreates the native enum type. Mirrors
the proven swap pattern from ``add wireguard to proxytypes``.

Revision ID: 5b1ce0a12001
Revises: a2b3c4d5e6f7
Create Date: 2026-06-08 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = "5b1ce0a12001"
down_revision = "a2b3c4d5e6f7"
branch_labels = None
depends_on = None


enum_name = "proxytypes"
temp_enum_name = "temp_proxytypes"
old_values = ("VMess", "VLESS", "Trojan", "Shadowsocks", "WireGuard")
new_values = (*old_values, "Hysteria2", "TUIC")

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
    op.execute("DELETE FROM proxies WHERE type IN ('Hysteria2', 'TUIC')")

    temp_type.create(op.get_bind(), checkfirst=False)
    _swap(new_type, temp_type, temp_enum_name)
    new_type.drop(op.get_bind(), checkfirst=False)

    old_type.create(op.get_bind(), checkfirst=False)
    _swap(temp_type, old_type, enum_name)
    temp_type.drop(op.get_bind(), checkfirst=False)
