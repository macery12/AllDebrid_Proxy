"""Expand task.infohash column type for longer identifiers

Revision ID: 0006_expand_task_infohash_type
Revises: 0005_task_file_metrics
Create Date: 2026-04-08

"""
from alembic import op
import sqlalchemy as sa

revision = '0006_expand_task_infohash_type'
down_revision = '0005_task_file_metrics'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        'task',
        'infohash',
        existing_type=sa.String(length=40),
        type_=sa.Text(),
        existing_nullable=False
    )


def downgrade():
    bind = op.get_bind()
    max_length = bind.execute(sa.text("SELECT COALESCE(MAX(char_length(infohash)), 0) FROM task")).scalar() or 0
    if max_length > 40:
        raise RuntimeError("Cannot downgrade task.infohash to VARCHAR(40): existing values exceed 40 characters")

    op.alter_column(
        'task',
        'infohash',
        existing_type=sa.Text(),
        type_=sa.String(length=40),
        existing_nullable=False
    )
