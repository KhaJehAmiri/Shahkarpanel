"""add workflows table

Phase 4: multi-step workflow automation.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-06-03 04:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b8c9d0e1f2a3'
down_revision = 'a7b8c9d0e1f2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'workflows',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('trigger_event', sa.String(length=64), nullable=False),
        sa.Column('condition', sa.JSON(), nullable=True),
        sa.Column('steps', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_workflows_trigger_event'), 'workflows', ['trigger_event'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_workflows_trigger_event'), table_name='workflows')
    op.drop_table('workflows')
