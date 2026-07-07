"""add AnyTLS proxy type and node_singbox columns

Revision ID: i5j6k7l8m9n0
Revises: h4i5j6k7l8m9
Create Date: 2026-06-10 12:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = "i5j6k7l8m9n0"
down_revision = "h4i5j6k7l8m9"
branch_labels = None
depends_on = None

enum_name = "proxytypes"
temp_enum_name = "temp_proxytypes"
old_values = ("VMess", "VLESS", "Trojan", "Shadowsocks", "WireGuard", "Hysteria2", "TUIC")
new_values = (*old_values, "AnyTLS")

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

    with op.batch_alter_table("node_singbox") as batch_op:
        batch_op.add_column(
            sa.Column("anytls_enabled", sa.Boolean(), server_default=sa.false(), nullable=False)
        )
        batch_op.add_column(sa.Column("anytls_port", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.execute("DELETE FROM proxies WHERE type = 'AnyTLS'")

    with op.batch_alter_table("node_singbox") as batch_op:
        batch_op.drop_column("anytls_port")
        batch_op.drop_column("anytls_enabled")

    temp_type.create(op.get_bind(), checkfirst=False)
    _swap(new_type, temp_type, temp_enum_name)
    new_type.drop(op.get_bind(), checkfirst=False)

    old_type.create(op.get_bind(), checkfirst=False)
    _swap(temp_type, old_type, enum_name)
    temp_type.drop(op.get_bind(), checkfirst=False)
