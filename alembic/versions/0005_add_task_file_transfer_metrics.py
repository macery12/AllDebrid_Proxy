"""Add transfer metrics columns to task_file table

Revision ID: 0005_add_task_file_transfer_metrics
Revises: 0004_add_source_type
Create Date: 2026-04-08

"""
from alembic import op
import sqlalchemy as sa

revision = '0005_add_task_file_transfer_metrics'
down_revision = '0004_add_source_type'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('task_file', sa.Column('speed_bps', sa.BigInteger(), nullable=False, server_default='0'))
    op.add_column('task_file', sa.Column('eta_seconds', sa.Integer(), nullable=True))
    op.add_column('task_file', sa.Column('progress_pct', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('task_file', sa.Column('last_progress_at', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column('task_file', 'last_progress_at')
    op.drop_column('task_file', 'progress_pct')
    op.drop_column('task_file', 'eta_seconds')
    op.drop_column('task_file', 'speed_bps')
