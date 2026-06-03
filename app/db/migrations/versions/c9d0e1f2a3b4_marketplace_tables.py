"""add marketplace plugin + review tables

Phase 5: plugin marketplace and ratings.

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-06-03 05:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c9d0e1f2a3b4'
down_revision = 'b8c9d0e1f2a3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'marketplace_plugins',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('version', sa.String(length=32), nullable=True),
        sa.Column('description', sa.String(length=1024), nullable=True),
        sa.Column('author', sa.String(length=128), nullable=True),
        sa.Column('source_url', sa.String(length=512), nullable=True),
        sa.Column('installed', sa.Boolean(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('rating_sum', sa.Integer(), nullable=False),
        sa.Column('rating_count', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    op.create_index(
        op.f('ix_marketplace_plugins_name'), 'marketplace_plugins', ['name'], unique=False
    )

    op.create_table(
        'plugin_reviews',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('plugin_id', sa.Integer(), nullable=False),
        sa.Column('admin_id', sa.Integer(), nullable=True),
        sa.Column('rating', sa.Integer(), nullable=False),
        sa.Column('comment', sa.String(length=1024), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['plugin_id'], ['marketplace_plugins.id']),
        sa.ForeignKeyConstraint(['admin_id'], ['admins.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('plugin_id', 'admin_id', name='uq_plugin_review_admin'),
    )
    op.create_index(
        op.f('ix_plugin_reviews_plugin_id'), 'plugin_reviews', ['plugin_id'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_plugin_reviews_plugin_id'), table_name='plugin_reviews')
    op.drop_table('plugin_reviews')
    op.drop_index(op.f('ix_marketplace_plugins_name'), table_name='marketplace_plugins')
    op.drop_table('marketplace_plugins')
