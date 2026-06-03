"""add rules table

Automation rules for the rule engine (phase 1).

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-06-03 01:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e5f6a7b8c9d0'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'rules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('trigger_event', sa.String(length=64), nullable=False),
        sa.Column('condition', sa.JSON(), nullable=True),
        sa.Column('action', sa.String(length=64), nullable=False),
        sa.Column('action_params', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_rules_trigger_event'), 'rules', ['trigger_event'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_rules_trigger_event'), table_name='rules')
    op.drop_table('rules')
