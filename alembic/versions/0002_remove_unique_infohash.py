from alembic import op
import sqlalchemy as sa

revision = '0002_remove_unique_infohash'
down_revision = '0001_init'
branch_labels = None
depends_on = None

def upgrade():
    # Remove unique constraint on infohash to allow task reuse
    # Drop the unique constraint
    op.drop_constraint('task_infohash_key', 'task', type_='unique')
    
    # Add index on infohash for faster lookups
    op.create_index('ix_task_infohash', 'task', ['infohash'])

def downgrade():
    # Restore unique constraint on infohash
    op.drop_index('ix_task_infohash', table_name='task')
    op.create_unique_constraint('task_infohash_key', 'task', ['infohash'])
