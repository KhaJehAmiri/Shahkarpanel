"""platform settings UI + sub-reseller commission

Revision ID: d9e0f1a2b3c4
Revises: c8d9e0f1a2b3
Create Date: 2026-06-07 02:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'd9e0f1a2b3c4'
down_revision = 'c8d9e0f1a2b3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'platform_settings',
        sa.Column('key', sa.String(length=64), nullable=False),
        sa.Column('value', sa.JSON(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('key'),
    )
    with op.batch_alter_table('admins', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('commission_percent', sa.Integer(), nullable=False, server_default=sa.text('0')),
        )


def downgrade() -> None:
    with op.batch_alter_table('admins', schema=None) as batch_op:
        batch_op.drop_column('commission_percent')
    op.drop_table('platform_settings')
