import { useState, useCallback } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import { tasksApi } from '../api/tasks';
import { APIError } from '../api/client';
import { useTask } from '../hooks/useTask';
import { useTaskStream } from '../hooks/useTaskStream';
import { isFinalState } from '../lib/utils';
import { StatusBadge } from '../components/StatusBadge';
import { StreamIndicator } from '../components/StreamIndicator';
import { FileTable } from '../components/FileTable';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { ErrorBanner } from '../components/ErrorBanner';
import { EmptyState } from '../components/EmptyState';
import type { Task } from '../types';
import styles from './TaskDetailPage.module.css';

export function TaskDetailPage() {
  const { taskId } = useParams<{ taskId: string }>();
  const navigate = useNavigate();

  const { task, setTask, loading, error: loadError } = useTask(taskId);

  const isSelectable =
    task?.mode === 'select' &&
    !isFinalState(task?.status ?? '') &&
    task?.status === 'waiting_selection';

  const isActive = !!task && !isFinalState(task.status);

  const streamStatus = useTaskStream(
    taskId,
    isActive,
    useCallback(
      (updater: (prev: Task | null) => Task | null) => setTask((prev) => updater(prev) as Task | null),
      [setTask],
    ),
  );

  // Selection state
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  // Action states
  const [actionError, setActionError] = useState<string | null>(null);
  const [submittingSelect, setSubmittingSelect] = useState(false);
  const [submittingCancel, setSubmittingCancel] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

  // Selection handlers
  const handleToggleFile = (fileId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(fileId)) next.delete(fileId);
      else next.add(fileId);
      return next;
    });
  };

  const handleToggleAll = (select: boolean) => {
    if (!task) return;
    setSelectedIds(select ? new Set(task.files.map((f) => f.fileId)) : new Set());
  };

  const handleSubmitSelection = async () => {
    if (!taskId || selectedIds.size === 0) return;
    setSubmittingSelect(true);
    setActionError(null);
    try {
      await tasksApi.select(taskId, Array.from(selectedIds));
      // SSE will update the status; refresh task data immediately
      const updated = await tasksApi.get(taskId);
      setTask(updated);
      setSelectedIds(new Set());
    } catch (e) {
      setActionError(e instanceof APIError ? e.message : 'Selection failed');
    } finally {
      setSubmittingSelect(false);
    }
  };

  const handleCancel = async () => {
    if (!taskId) return;
    setSubmittingCancel(true);
    setActionError(null);
    try {
      await tasksApi.cancel(taskId);
      const updated = await tasksApi.get(taskId);
      setTask(updated);
    } catch (e) {
      setActionError(e instanceof APIError ? e.message : 'Cancel failed');
    } finally {
      setSubmittingCancel(false);
    }
  };

  const handleDelete = async () => {
    if (!taskId) return;
    setDeleting(true);
    try {
      await tasksApi.delete(taskId, true /* purge files */);
      navigate('/');
    } catch (e) {
      setActionError(e instanceof APIError ? e.message : 'Delete failed');
      setDeleting(false);
      setConfirmDelete(false);
    }
  };

  // ─── Loading / error states ───
  if (loading) {
    return (
      <div className="flex flex-center gap-3 muted" style={{ minHeight: 200 }}>
        <span className="spinner spinner-lg" />
        Loading task…
      </div>
    );
  }

  if (loadError || !task) {
    return (
      <div className="card">
        <EmptyState
          message={loadError ?? 'Task not found'}
          icon={
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden>
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="8" x2="12" y2="12" />
              <line x1="12" y1="16" x2="12.01" y2="16" />
            </svg>
          }
        >
          <Link to="/" className="btn mt-4">← Back to home</Link>
        </EmptyState>
      </div>
    );
  }

  const isFinal = isFinalState(task.status);

  return (
    <div>
      {/* ─── Page header ─── */}
      <div className={styles.header}>
        <div>
          <h1 className={styles.taskTitle}>
            Task Details
            <span className={styles.taskId}>{task.taskId}</span>
          </h1>

          <div className={styles.metaRow}>
            <div className={styles.metaItem}>
              <strong>Status</strong>
              <StatusBadge status={task.status} />
            </div>
            <div className={styles.metaItem}>
              <strong>Mode</strong>
              <span className="pill neutral">{task.mode}</span>
            </div>
            {task.label && (
              <div className={styles.metaItem}>
                <strong>Label</strong>
                <span>{task.label}</span>
              </div>
            )}
            {task.infohash && (
              <div className={styles.metaItem}>
                <strong>Hash</strong>
                <kbd>{task.infohash.substring(0, 16)}…</kbd>
              </div>
            )}
            <div className={styles.metaItem}>
              <StreamIndicator status={streamStatus} />
            </div>
          </div>
        </div>

        <div className={styles.headerActions}>
          <Link to="/" className="btn">← Home</Link>
          {!isFinal && (
            <Link to={`/tasks/${task.taskId}/files`} className="btn btn-good">
              Open Files
            </Link>
          )}
          {isFinal && (
            <Link to={`/tasks/${task.taskId}/files`} className="btn btn-good">
              Browse Files
            </Link>
          )}
        </div>
      </div>

      <ErrorBanner message={actionError} onDismiss={() => setActionError(null)} />

      {/* ─── Files section ─── */}
      <div className="card mt-4">
        <div className={styles.sectionHeader}>
          <span className={styles.sectionTitle}>
            Files
            <span className={styles.fileCount}>({task.files.length} files)</span>
          </span>
        </div>

        {/* Selection toolbar */}
        {isSelectable && (
          <div className={styles.selectionBar}>
            <span className={styles.selectionCount}>
              {selectedIds.size} of {task.files.length} selected
            </span>
            <button className="btn btn-sm" onClick={() => handleToggleAll(true)}>
              Select All
            </button>
            <button className="btn btn-sm" onClick={() => handleToggleAll(false)}>
              Clear All
            </button>
            <button
              className="btn btn-primary btn-sm"
              onClick={handleSubmitSelection}
              disabled={selectedIds.size === 0 || submittingSelect}
            >
              {submittingSelect && <span className="spinner" />}
              Submit Selection ({selectedIds.size})
            </button>
          </div>
        )}

        <FileTable
          files={task.files}
          selectable={isSelectable}
          selectedIds={selectedIds}
          onToggle={handleToggleFile}
          onToggleAll={handleToggleAll}
          loading={task.files.length === 0 && !isFinal}
        />

        {/* Action toolbar */}
        <div className={styles.toolbar}>
          {!isFinal && (
            <button
              className="btn btn-warn"
              onClick={handleCancel}
              disabled={submittingCancel}
            >
              {submittingCancel && <span className="spinner" />}
              Cancel Task
            </button>
          )}
          <button
            className="btn btn-danger"
            onClick={() => setConfirmDelete(true)}
            disabled={deleting}
          >
            {deleting && <span className="spinner" />}
            Delete + Purge
          </button>
          <Link to={`/tasks/${task.taskId}/files`} className="btn btn-good">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
              <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
            </svg>
            Open Files
          </Link>
        </div>
      </div>

      {/* ─── Confirm delete dialog ─── */}
      <ConfirmDialog
        open={confirmDelete}
        title="Delete and Purge Task?"
        message={`This will permanently delete the task and all downloaded files for "${task.label ?? task.taskId}". This cannot be undone.`}
        confirmLabel="Delete + Purge"
        dangerous
        onConfirm={handleDelete}
        onCancel={() => setConfirmDelete(false)}
      />
    </div>
  );
}
