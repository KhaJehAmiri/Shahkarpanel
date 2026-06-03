"""postgresql citext compatibility

Makes the case-insensitive identifier columns (users.username, nodes.name)
behave like SQLite's NOCASE collation on PostgreSQL by switching them to the
CITEXT type. No-op on SQLite and MySQL, which handle case-insensitivity through
their own collations.

Revision ID: a1b2c3d4e5f6
Revises: 2b231de97dc3
Create Date: 2026-06-03 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import CITEXT


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '2b231de97dc3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.engine.name != 'postgresql':
        return

    op.execute('CREATE EXTENSION IF NOT EXISTS citext')
    op.alter_column(
        'users', 'username',
        type_=CITEXT(),
        existing_type=sa.String(length=34),
        postgresql_using='username::citext',
    )
    op.alter_column(
        'nodes', 'name',
        type_=CITEXT(),
        existing_type=sa.String(length=256),
        postgresql_using='name::citext',
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.engine.name != 'postgresql':
        return

    op.alter_column(
        'nodes', 'name',
        type_=sa.String(length=256),
        existing_type=CITEXT(),
        postgresql_using='name::varchar',
    )
    op.alter_column(
        'users', 'username',
        type_=sa.String(length=34),
        existing_type=CITEXT(),
        postgresql_using='username::varchar',
    )
