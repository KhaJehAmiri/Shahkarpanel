"""add feature_flags table

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-03 00:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'feature_flags',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('admin_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['admin_id'], ['admins.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name', 'admin_id', name='uq_feature_flag_name_admin'),
    )
    op.create_index(op.f('ix_feature_flags_name'), 'feature_flags', ['name'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_feature_flags_name'), table_name='feature_flags')
    op.drop_table('feature_flags')
