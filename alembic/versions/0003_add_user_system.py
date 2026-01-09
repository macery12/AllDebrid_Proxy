"""Add user system

Revision ID: 0003_add_user_system
Revises: 0002_remove_unique_infohash
Create Date: 2026-01-09

"""
from alembic import op
import sqlalchemy as sa

revision = '0003_add_user_system'
down_revision = '0002_remove_unique_infohash'
branch_labels = None
depends_on = None

def upgrade():
    # Create user table
    op.create_table('user',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('username', sa.String(length=255), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('is_admin', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('last_login', sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index('ix_user_username', 'user', ['username'], unique=True)

    # Create user_stats table
    op.create_table('user_stats',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id', ondelete='CASCADE'), nullable=False),
        sa.Column('total_downloads', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_magnets_processed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_bytes_downloaded', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now())
    )
    op.create_index('ix_user_stats_user_id', 'user_stats', ['user_id'], unique=True)

    # Add user_id to task table
    op.add_column('task', sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id', ondelete='CASCADE'), nullable=True))
    op.create_index('ix_task_user_id', 'task', ['user_id'])

def downgrade():
    # Remove user_id from task table
    op.drop_index('ix_task_user_id', table_name='task')
    op.drop_column('task', 'user_id')

    # Drop user_stats table
    op.drop_index('ix_user_stats_user_id', table_name='user_stats')
    op.drop_table('user_stats')

    # Drop user table
    op.drop_index('ix_user_username', table_name='user')
    op.drop_table('user')
