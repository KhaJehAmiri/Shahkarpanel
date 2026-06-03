"""add indexes on users.admin_id and users.status

Speeds up the very common "count/list users by owner and status" queries used
throughout the panel and multi-tenant accounting.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-06-03 00:15:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'd4e5f6a7b8c9'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(op.f('ix_users_admin_id'), 'users', ['admin_id'], unique=False)
    op.create_index(op.f('ix_users_status'), 'users', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_users_status'), table_name='users')
    op.drop_index(op.f('ix_users_admin_id'), table_name='users')
