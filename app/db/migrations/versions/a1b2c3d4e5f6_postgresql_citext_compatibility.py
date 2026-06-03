"""postgresql citext compatibility

Makes users.username case-insensitive on PostgreSQL (CITEXT), matching SQLite
NOCASE. nodes.name is migrated in f7a8b9c0d1e2 after the nodes table exists.
No-op on SQLite and MySQL.

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
    # users exists here; nodes is created later (37692c1c9715) — see f7a8b9c0d1e2
    op.alter_column(
        'users', 'username',
        type_=CITEXT(),
        existing_type=sa.String(length=34),
        postgresql_using='username::citext',
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.engine.name != 'postgresql':
        return

    op.alter_column(
        'users', 'username',
        type_=sa.String(length=34),
        existing_type=CITEXT(),
        postgresql_using='username::varchar',
    )
