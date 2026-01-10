"""Add source_type to task table

Revision ID: 0004_add_source_type
Revises: 0003_add_user_system
Create Date: 2026-01-10

"""
from alembic import op
import sqlalchemy as sa

revision = '0004_add_source_type'
down_revision = '0003_add_user_system'
branch_labels = None
depends_on = None

def upgrade():
    # Add source_type column to task table
    # Default to 'magnet' for backward compatibility with existing tasks
    op.add_column('task', sa.Column('source_type', sa.String(length=16), nullable=False, server_default='magnet'))

def downgrade():
    # Remove source_type column from task table
    op.drop_column('task', 'source_type')
