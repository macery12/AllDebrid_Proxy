import { useState, useEffect, useRef } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { tasksApi } from '../api/tasks';
import type { CreateTaskResponse, TaskSummary } from '../api/tasks';
import { APIError } from '../api/client';
import { ErrorBanner } from '../components/ErrorBanner';
import { StatusBadge } from '../components/StatusBadge';
import { EmptyState } from '../components/EmptyState';
import styles from './CreateTaskPage.module.css';

const MAX_SOURCE_LENGTH = 10_000;
const MAX_LABEL_LENGTH = 500;

export function CreateTaskPage() {
  const navigate = useNavigate();

  // Form state
  const [source, setSource] = useState('');
  const [mode, setMode] = useState<'auto' | 'select'>('auto');
  const [label, setLabel] = useState('');
  const [torrentFiles, setTorrentFiles] = useState<File[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Submission state
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<CreateTaskResponse[]>([]);

  // Recent tasks
  const [recentTasks, setRecentTasks] = useState<TaskSummary[]>([]);
  const [recentLoading, setRecentLoading] = useState(true);

  useEffect(() => {
    tasksApi
      .list({ limit: 10 })
      .then((d) => setRecentTasks(d.tasks))
      .catch(() => setRecentTasks([]))
      .finally(() => setRecentLoading(false));
  }, [results]);

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const files = Array.from(e.dataTransfer.files).filter((f) =>
      f.name.endsWith('.torrent'),
    );
    setTorrentFiles((prev) => [...prev, ...files]);
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      const files = Array.from(e.target.files).filter((f) => f.name.endsWith('.torrent'));
      setTorrentFiles((prev) => [...prev, ...files]);
    }
    e.target.value = '';
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setResults([]);

    const sources = source
      .split('\n')
      .map((s) => s.trim())
      .filter(Boolean);

    if (sources.length === 0 && torrentFiles.length === 0) {
      setError('Enter at least one magnet link / URL, or upload a torrent file.');
      return;
    }

    if (source.length > MAX_SOURCE_LENGTH) {
      setError(`Source input is too long (max ${MAX_SOURCE_LENGTH} characters).`);
      return;
    }

    if (label.length > MAX_LABEL_LENGTH) {
      setError(`Label is too long (max ${MAX_LABEL_LENGTH} characters).`);
      return;
    }

    setSubmitting(true);

    const created: CreateTaskResponse[] = [];
    const failures: string[] = [];

    // Process text sources
    const seen = new Set<string>();
    const uniqueSources = sources.filter((s) => {
      const key = s.toLowerCase();
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });

    for (let i = 0; i < uniqueSources.length; i++) {
      const src = uniqueSources[i];
      const lbl =
        uniqueSources.length > 1 && label
          ? `${label.substring(0, MAX_LABEL_LENGTH - 10)} (${i + 1}/${uniqueSources.length})`
          : label || undefined;

      try {
        const res = await tasksApi.create({ source: src, mode, label: lbl });
        created.push(res);
      } catch (e) {
        failures.push(e instanceof APIError ? e.message : `Source ${i + 1} failed`);
      }
    }

    // Process torrent files
    for (const file of torrentFiles) {
      const form = new FormData();
      form.append('torrent_file', file);
      form.append('mode', mode);
      if (label) form.append('label', label);

      try {
        const res = await fetch('/v2/tasks/from-torrent', {
          method: 'POST',
          credentials: 'include',
          body: form,
        });
        if (!res.ok) {
          const data = (await res.json().catch(() => ({}))) as Record<string, unknown>;
          failures.push(String(data.error ?? `Torrent "${file.name}" failed`));
        } else {
          const data = (await res.json()) as CreateTaskResponse;
          created.push(data);
        }
      } catch {
        failures.push(`Torrent "${file.name}" failed`);
      }
    }

    setSubmitting(false);

    if (failures.length > 0) {
      setError(failures.join(' | '));
    }

    if (created.length === 1 && failures.length === 0) {
      navigate(`/tasks/${created[0].taskId}`);
      return;
    }

    if (created.length > 0) {
      setResults(created);
      setSource('');
      setLabel('');
      setTorrentFiles([]);
    }
  };

  return (
    <div>
      <h1 className={styles.pageTitle}>New Download Task</h1>
      <p className={styles.pageSubtitle}>
        Submit a magnet link, direct URL, or upload a .torrent file.
      </p>

      <div className={styles.layout}>
        {/* ─── Main form ─── */}
        <div>
          <form className="card" onSubmit={submit} noValidate>
            <ErrorBanner message={error} onDismiss={() => setError(null)} className="mb-4" />

            <div className="field">
              <label htmlFor="source" className="field-label">Magnet link or URL</label>
              <textarea
                id="source"
                className="textarea"
                placeholder="magnet:?xt=urn:btih:… or https://…&#10;One per line"
                rows={5}
                value={source}
                onChange={(e) => setSource(e.target.value)}
                disabled={submitting}
              />
            </div>

            {/* OR torrent drop zone */}
            <div className={styles.orDivider}><span>or</span></div>

            <div
              className={`${styles.dropZone} ${dragOver ? styles.dragOver : ''}`}
              onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => { if (e.key === 'Enter') fileInputRef.current?.click(); }}
            >
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden style={{ margin: '0 auto 8px', display: 'block', opacity: 0.5 }}>
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="17 8 12 3 7 8" />
                <line x1="12" y1="3" x2="12" y2="15" />
              </svg>
              <p style={{ fontWeight: 600, fontSize: 13 }}>Drop .torrent files here</p>
              <p className={styles.dropZoneText}>or click to browse</p>
              {torrentFiles.length > 0 && (
                <p className={styles.dropZoneFiles}>{torrentFiles.length} file(s) selected</p>
              )}
              <input
                ref={fileInputRef}
                type="file"
                accept=".torrent"
                multiple
                onChange={handleFileChange}
                style={{ display: 'none' }}
              />
            </div>

            <div className={`${styles.formRow} mt-4`}>
              <div className="field">
                <label className="field-label">Label (optional)</label>
                <input
                  className="input"
                  type="text"
                  placeholder="My movie"
                  maxLength={MAX_LABEL_LENGTH}
                  value={label}
                  onChange={(e) => setLabel(e.target.value)}
                  disabled={submitting}
                />
              </div>
            </div>

            {/* Mode selector */}
            <div className="field mt-4">
              <label className="field-label">Download mode</label>
              <div className={styles.modeGroup}>
                {(['auto', 'select'] as const).map((m) => (
                  <label
                    key={m}
                    className={`${styles.modeOption} ${mode === m ? styles.selected : ''}`}
                  >
                    <input
                      type="radio"
                      name="mode"
                      value={m}
                      checked={mode === m}
                      onChange={() => setMode(m)}
                      disabled={submitting}
                    />
                    <span className={styles.modeDot} />
                    <span>
                      <span className={styles.modeLabel}>{m === 'auto' ? 'Auto' : 'Select'}</span>
                      <p className={styles.modeDesc}>
                        {m === 'auto'
                          ? 'Download all files automatically'
                          : 'Choose which files to download'}
                      </p>
                    </span>
                  </label>
                ))}
              </div>
            </div>

            <div className="mt-5">
              <button
                type="submit"
                className="btn btn-primary btn-lg"
                disabled={submitting}
                style={{ width: '100%', justifyContent: 'center' }}
              >
                {submitting && <span className="spinner" />}
                {submitting ? 'Creating…' : 'Create Task'}
              </button>
            </div>
          </form>

          {/* Results after multi-task submission */}
          {results.length > 0 && (
            <div className={`card mt-5`}>
              <p className="card-title">Tasks Created</p>
              <div className={styles.resultList}>
                {results.map((r) => (
                  <div key={r.taskId} className={styles.resultItem}>
                    {r.reused ? (
                      <span className="pill warn">Reused</span>
                    ) : (
                      <span className="pill good">New</span>
                    )}
                    <Link to={`/tasks/${r.taskId}`}>{r.taskId}</Link>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* ─── Sidebar: recent tasks ─── */}
        <div className="card">
          <p className="card-title">Recent Tasks</p>
          {recentLoading ? (
            <div className="flex gap-2 items-center muted small">
              <span className="spinner" />
              Loading…
            </div>
          ) : recentTasks.length === 0 ? (
            <EmptyState message="No tasks yet" />
          ) : (
            recentTasks.map((t) => (
              <Link key={t.taskId} to={`/tasks/${t.taskId}`} className={styles.recentItem}>
                <StatusBadge status={t.status} />
                <span className={styles.recentLabel}>{t.label || t.taskId}</span>
                <span className={styles.recentMeta}>{t.mode}</span>
              </Link>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
