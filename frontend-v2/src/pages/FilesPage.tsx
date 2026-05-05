import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { tasksApi } from '../api/tasks';
import { APIError } from '../api/client';
import { formatBytes } from '../lib/utils';
import { EmptyState } from '../components/EmptyState';
import { ErrorBanner } from '../components/ErrorBanner';
import type { FileEntry } from '../types';
import styles from './FilesPage.module.css';

export function FilesPage() {
  const { taskId } = useParams<{ taskId: string }>();

  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!taskId) return;
    setLoading(true);
    tasksApi
      .getFiles(taskId)
      .then((d) => setEntries(d.entries))
      .catch((e: unknown) => setError(e instanceof APIError ? e.message : 'Failed to load files'))
      .finally(() => setLoading(false));
  }, [taskId]);

  return (
    <div>
      <div className={styles.header}>
        <h1 className={styles.title}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
            <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
          </svg>
          Task Files
        </h1>

        {taskId && (
          <div className={styles.actions}>
            <a
              className="btn"
              href={`/d/${taskId}.tar.gz`}
              download
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="7 10 12 15 17 10" />
                <line x1="12" y1="15" x2="12" y2="3" />
              </svg>
              Download All (.tar.gz)
            </a>
            <a className="btn" href={`/d/${taskId}/links.txt`} target="_blank" rel="noopener noreferrer">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
              </svg>
              Links.txt
            </a>
            <Link className="btn btn-primary" to={`/tasks/${taskId}`}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
                <path d="M19 12H5M12 19l-7-7 7-7" />
              </svg>
              Back to Task
            </Link>
          </div>
        )}
      </div>

      <ErrorBanner message={error} onDismiss={() => setError(null)} />

      <div className="card">
        {loading ? (
          <div className="flex flex-center gap-2 muted" style={{ padding: 40 }}>
            <span className="spinner" />
            Loading files…
          </div>
        ) : entries.length === 0 ? (
          <EmptyState message="No files found in this task." />
        ) : (
          <>
            <p className="muted small mb-4">
              {entries.length} file{entries.length !== 1 ? 's' : ''}
            </p>
            <table className="data-table">
              <thead>
                <tr>
                  <th>File</th>
                  <th style={{ width: 120, textAlign: 'right' }}>Size</th>
                  <th style={{ width: 220 }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((entry) => (
                  <tr key={entry.rel}>
                    <td>
                      <span className={styles.fileName}>
                        {entry.is_video ? '🎬 ' : '📄 '}
                        {entry.rel}
                      </span>
                      {entry.is_downloading && (
                        <span className="pill warn xs" style={{ marginLeft: 8 }}>
                          Downloading…
                        </span>
                      )}
                    </td>
                    <td style={{ textAlign: 'right' }} className="muted small">
                      {formatBytes(entry.size)}
                    </td>
                    <td>
                      {entry.is_downloading ? (
                        <span className="muted small">In progress…</span>
                      ) : (
                        <div className={styles.fileActions}>
                          {entry.is_video && taskId && (
                            <a
                              className="btn btn-good btn-sm"
                              href={`/d/${taskId}/play/${entry.rel}`}
                              target="_blank"
                              rel="noopener noreferrer"
                            >
                              ▶ Play
                            </a>
                          )}
                          {taskId && (
                            <a
                              className="btn btn-sm"
                              href={`/d/${taskId}/raw/${entry.rel}`}
                              download={entry.rel.split('/').pop()}
                            >
                              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
                                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                                <polyline points="7 10 12 15 17 10" />
                                <line x1="12" y1="15" x2="12" y2="3" />
                              </svg>
                              Download
                            </a>
                          )}
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </div>
    </div>
  );
}
