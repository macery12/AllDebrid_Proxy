from alembic import op
import sqlalchemy as sa

revision = '0001_init'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('task',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('label', sa.Text(), nullable=True),
        sa.Column('mode', sa.String(length=16), nullable=False),
        sa.Column('source', sa.Text(), nullable=False),
        sa.Column('infohash', sa.String(length=40), nullable=False, unique=True),
        sa.Column('provider', sa.String(length=32), nullable=False),
        sa.Column('provider_ref', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='queued'),
        sa.Column('progress_pct', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now())
    )
    op.create_index('ix_task_status', 'task', ['status'])
    op.create_index('ix_task_created_at', 'task', ['created_at'])

    op.create_table('task_file',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('task_id', sa.String(length=36), sa.ForeignKey('task.id', ondelete='CASCADE'), nullable=False),
        sa.Column('index', sa.Integer(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('size_bytes', sa.BigInteger(), nullable=True),
        sa.Column('state', sa.String(length=32), nullable=False, server_default='listed'),
        sa.Column('bytes_downloaded', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('local_path', sa.Text(), nullable=True),
        sa.Column('unlocked_url', sa.Text(), nullable=True)
    )
    op.create_index('ix_task_file_task_state', 'task_file', ['task_id', 'state'])
    op.create_index('ix_task_file_task_index', 'task_file', ['task_id', 'index'])

    op.create_table('task_event',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('task_id', sa.String(length=36), sa.ForeignKey('task.id', ondelete='CASCADE'), nullable=False),
        sa.Column('ts', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('level', sa.String(length=16), nullable=False),
        sa.Column('event', sa.Text(), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=True)
    )
    op.create_index('ix_task_event_task_ts', 'task_event', ['task_id', 'ts'])

def downgrade():
    op.drop_index('ix_task_event_task_ts', table_name='task_event')
    op.drop_table('task_event')
    op.drop_index('ix_task_file_task_index', table_name='task_file')
    op.drop_index('ix_task_file_task_state', table_name='task_file')
    op.drop_table('task_file')
    op.drop_index('ix_task_created_at', table_name='task')
    op.drop_index('ix_task_status', table_name='task')
    op.drop_table('task')
