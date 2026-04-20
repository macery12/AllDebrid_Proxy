"""Add user role column

Adds a 'role' column to the user table supporting three levels:
  admin  – full access (migrated from is_admin=True)
  member – home/tasks access but not admin pages
  user   – download-only access (migrated from is_admin=False)

Revision ID: 0007_add_user_roles
Revises: 0006_expand_task_infohash_type
Create Date: 2026-04-20

"""
from alembic import op
import sqlalchemy as sa

revision = '0007_add_user_roles'
down_revision = '0006_expand_task_infohash_type'
branch_labels = None
depends_on = None


def upgrade():
    # Add role column with default 'user'
    op.add_column('user', sa.Column('role', sa.String(length=16), nullable=False, server_default='user'))

    # Migrate existing is_admin=True users to role='admin'
    op.execute("UPDATE \"user\" SET role = 'admin' WHERE is_admin = TRUE")


def downgrade():
    op.drop_column('user', 'role')
