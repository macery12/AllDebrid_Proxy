import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { adminApi } from '../api/admin';
import { APIError } from '../api/client';
import { tasksApi } from '../api/tasks';
import { ErrorBanner } from '../components/ErrorBanner';
import { EmptyState } from '../components/EmptyState';
import { StatusBadge } from '../components/StatusBadge';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { formatBytes, formatDateTime, formatModeLabel, formatStatusLabel, truncateMiddle } from '../lib/utils';
import type { AdminStats, TaskSummary } from '../types';
import styles from './AdminDashboardPage.module.css';

export function AdminDashboardPage() {
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [deleteTaskId, setDeleteTaskId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [copiedTaskId, setCopiedTaskId] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const [statsRes, tasksRes] = await Promise.all([
        adminApi.stats(),
        adminApi.tasks({ limit: 100, status: statusFilter || undefined }),
      ]);
      setStats(statsRes);
      setTasks(tasksRes.tasks);
    } catch (e) {
      setError(e instanceof APIError ? e.message : 'Failed to load admin dashboard');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, [statusFilter]);

  const filteredTasks = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return tasks;
    return tasks.filter((task) => {
      return [task.taskId, task.label ?? '', task.source ?? '']
        .some((value) => value.toLowerCase().includes(term));
    });
  }, [search, tasks]);

  const handleDelete = async () => {
    if (!deleteTaskId) return;
    setDeleting(true);
    try {
      await tasksApi.delete(deleteTaskId, true);
      setDeleteTaskId(null);
      await load();
    } catch (e) {
      setError(e instanceof APIError ? e.message : 'Failed to delete task');
    } finally {
      setDeleting(false);
    }
  };

  const handleCopyMagnet = async (task: TaskSummary) => {
    if (!task.source) return;
    try {
      await navigator.clipboard.writeText(task.source);
      setCopiedTaskId(task.taskId);
      window.setTimeout(() => {
        setCopiedTaskId((current) => (current === task.taskId ? null : current));
      }, 1500);
    } catch {
      setError('Failed to copy magnet link');
    }
  };

  return (
    <div className={styles.page}>
      <section className={styles.topBar}>
        <div>
          <h1 className={styles.title}>Admin</h1>
          <p className={styles.subtitle}>Tasks, users, and system state.</p>
        </div>
        <div className={styles.actions}>
          <Link to="/admin/users" className="btn">Manage Users</Link>
          <Link to="/" className="btn btn-good">New Task</Link>
          <button className="btn" onClick={() => void load()} disabled={loading}>Refresh</button>
        </div>
      </section>

      <ErrorBanner message={error} onDismiss={() => setError(null)} />

      <section className={styles.statsGrid}>
        <article className={styles.statCard}><span>Total Tasks</span><strong>{stats?.tasks.total ?? '—'}</strong></article>
        <article className={styles.statCard}><span>Queued</span><strong>{stats?.tasks.queued ?? '—'}</strong></article>
        <article className={styles.statCard}><span>Downloading</span><strong>{stats?.tasks.downloading ?? '—'}</strong></article>
        <article className={styles.statCard}><span>Completed</span><strong>{stats?.tasks.completed ?? '—'}</strong></article>
        <article className={styles.statCard}><span>Users</span><strong>{stats?.users.total_users ?? '—'}</strong></article>
        <article className={styles.statCard}><span>Storage Free</span><strong>{stats ? formatBytes(stats.storage.free_bytes) : '—'}</strong></article>
      </section>

      <section className={styles.panel}>
        <div className={styles.filters}>
          <input
            className="input"
            placeholder="Search tasks"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <select className="select" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="">All statuses</option>
            <option value="queued">Queued</option>
            <option value="downloading">Downloading</option>
            <option value="ready">Ready</option>
            <option value="done">Done</option>
            <option value="completed">Completed</option>
            <option value="failed">Failed</option>
            <option value="canceled">Canceled</option>
          </select>
        </div>

        {loading ? (
          <div className="flex flex-center gap-2 muted" style={{ padding: 40 }}>
            <span className="spinner" />
            Loading admin data…
          </div>
        ) : filteredTasks.length === 0 ? (
          <EmptyState message="No tasks found" />
        ) : (
          <div className={styles.tableWrap}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>UUID</th>
                  <th>Task</th>
                  <th>Status</th>
                  <th>Mode</th>
                  <th>Created</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredTasks.map((task) => (
                  <tr key={task.taskId}>
                    <td className={styles.monoCell}>{task.id ?? '—'}</td>
                    <td className={styles.monoCell} title={task.taskId}>{truncateMiddle(task.taskId, 8, 6)}</td>
                    <td>
                      <div className={styles.taskLabel}>{task.label || truncateMiddle(task.taskId, 8, 6)}</div>
                    </td>
                    <td><StatusBadge status={task.status} /></td>
                    <td>{formatModeLabel(task.mode)}</td>
                    <td className="muted small">{formatDateTime(task.created_at)}</td>
                    <td>
                      <div className={styles.rowActions}>
                        <Link to={`/tasks/${task.taskId}`} className="btn btn-good btn-sm">View</Link>
                        <Link to={`/tasks/${task.taskId}/files`} className="btn btn-warn btn-sm">Files</Link>
                        {task.source && (
                          <button className="btn btn-sm" onClick={() => void handleCopyMagnet(task)}>
                            {copiedTaskId === task.taskId ? 'Copied' : 'Copy Magnet'}
                          </button>
                        )}
                        <button className="btn btn-danger btn-sm" onClick={() => setDeleteTaskId(task.taskId)}>Delete</button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className={styles.systemGrid}>
        <div className={styles.systemCard}>
          <span>Queue Length</span>
          <strong>{stats?.queue.length ?? '—'}</strong>
        </div>
        <div className={styles.systemCard}>
          <span>Download Progress</span>
          <strong>{stats?.downloads.progress_pct ?? 0}%</strong>
        </div>
        <div className={styles.systemCard}>
          <span>Worker</span>
          <strong>{stats?.health.worker_healthy ? formatStatusLabel('healthy') : formatStatusLabel('down')}</strong>
        </div>
      </section>

      <ConfirmDialog
        open={!!deleteTaskId}
        title="Delete task?"
        message="This deletes the task and purges downloaded files."
        confirmLabel={deleting ? 'Deleting…' : 'Delete'}
        dangerous
        onConfirm={() => void handleDelete()}
        onCancel={() => !deleting && setDeleteTaskId(null)}
      />
    </div>
  );
}
