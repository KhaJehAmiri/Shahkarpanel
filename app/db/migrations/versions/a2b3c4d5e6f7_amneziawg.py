"""AmneziaWG obfuscation parameters on node_wireguard

Revision ID: a2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-06-08 05:45:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'a2b3c4d5e6f7'
down_revision = 'f1a2b3c4d5e6'
branch_labels = None
depends_on = None

_INT_COLS = ['awg_jc', 'awg_jmin', 'awg_jmax', 'awg_s1', 'awg_s2']
_BIGINT_COLS = ['awg_h1', 'awg_h2', 'awg_h3', 'awg_h4']


def upgrade() -> None:
    with op.batch_alter_table('node_wireguard', schema=None) as batch_op:
        for col in _INT_COLS:
            batch_op.add_column(sa.Column(col, sa.Integer(), nullable=True))
        for col in _BIGINT_COLS:
            batch_op.add_column(sa.Column(col, sa.BigInteger(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('node_wireguard', schema=None) as batch_op:
        for col in _BIGINT_COLS + _INT_COLS:
            batch_op.drop_column(col)
