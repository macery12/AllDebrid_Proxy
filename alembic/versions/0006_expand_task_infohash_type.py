"""Expand task.infohash column type from VARCHAR(40) to TEXT

This allows the column to store not just 40-character SHA-1 hex hashes, but
also 32-character base32 infohashes and, in future, longer formats such as
64-character SHA-256 (BitTorrent v2).

Revision ID: 0006_expand_task_infohash_type
Revises: 0005_task_file_metrics
Create Date: 2026-04-20

"""
from alembic import op
import sqlalchemy as sa

revision = '0006_expand_task_infohash_type'
down_revision = '0005_task_file_metrics'
branch_labels = None
depends_on = None


def upgrade():
    # Drop the index first (Postgres requires this before altering column type)
    op.drop_index('ix_task_infohash', table_name='task')
    op.alter_column(
        'task',
        'infohash',
        existing_type=sa.String(40),
        type_=sa.Text(),
        existing_nullable=False,
    )
    op.create_index('ix_task_infohash', 'task', ['infohash'])


def downgrade():
    op.drop_index('ix_task_infohash', table_name='task')
    op.alter_column(
        'task',
        'infohash',
        existing_type=sa.Text(),
        type_=sa.String(40),
        existing_nullable=False,
    )
    op.create_index('ix_task_infohash', 'task', ['infohash'])
