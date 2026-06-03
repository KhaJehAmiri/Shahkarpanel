"""postgresql nodes.name citext

Apply CITEXT to nodes.name after the nodes table exists (37692c1c9715).

Revision ID: f7a8b9c0d1e2
Revises: e6a7b8c9d0f1
Create Date: 2026-06-03 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import CITEXT


revision = 'f7a8b9c0d1e2'
down_revision = 'e6a7b8c9d0f1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.engine.name != 'postgresql':
        return

    op.execute('CREATE EXTENSION IF NOT EXISTS citext')
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
