import { useState, useEffect, useCallback } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { bluecogApi } from '../api/bluecog';
import type { BlueCogTorrent, RSSStatus, RSSProgressEvent, SubmitResult } from '../api/bluecog';
import { APIError } from '../api/client';
import { ErrorBanner } from '../components/ErrorBanner';
import styles from './BlueCogPage.module.css';

const RSS_POLL_MS = 4_000;   // poll RSS status while running

function humanBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function fmtDate(iso: string | null): string {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString(undefined, {
      dateStyle: 'short',
      timeStyle: 'short',
    });
  } catch {
    return iso;
  }
}

function RSSProgressLog({ events }: { events: RSSProgressEvent[] }) {
  return (
    <div className={styles.rssLog}>
      {events.map((ev, i) => {
        if (ev.type === 'waiting') {
          return (
            <div key={i} className={styles.rssLogRow}>
              <span className={styles.rssLogIcon}>⏳</span>
              <span className={styles.rssLogWait}>Waiting {ev.seconds}s before next item…</span>
            </div>
          );
        }
        const icon =
          ev.step === 'fetching' ? '⟳' :
          ev.step === 'done'     ? '✓' :
          ev.step === 'failed'   ? '✗' : '—';
        const iconStyle =
          ev.step === 'done'   ? { color: '#4caf7d' } :
          ev.step === 'failed' ? { color: '#e05c5c' } :
          ev.step === 'fetching' ? { color: '#ffc107' } : {};
        return (
          <div key={i} className={styles.rssLogRow}>
            <span className={styles.rssLogIcon} style={iconStyle}>{icon}</span>
            <span className={styles.rssLogCounter}>[{ev.i}/{ev.n}]</span>
            <span className={styles.rssLogTitle}>{ev.title}</span>
            {ev.filename && <span className={styles.rssLogFile}>→ {ev.filename}</span>}
            {ev.error   && <span className={styles.rssLogErr}>→ {ev.error}</span>}
          </div>
        );
      })}
    </div>
  );
}

export function BlueCogPage() {
  const navigate = useNavigate();

  // ── Torrent list state ──────────────────────────────────────────────────────
  const [torrents, setTorrents] = useState<BlueCogTorrent[]>([]);
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set());

  // ── Submit state ────────────────────────────────────────────────────────────
  const [mode, setMode] = useState<'auto' | 'select'>('auto');
  const [label, setLabel] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [submitResults, setSubmitResults] = useState<SubmitResult[]>([]);
  const [submitError, setSubmitError] = useState<string | null>(null);

  // ── Manual URL fetch state ──────────────────────────────────────────────────
  const [fetchUrl, setFetchUrl] = useState('');
  const [fetching, setFetching] = useState(false);
  const [fetchMsg, setFetchMsg] = useState<string | null>(null);
  const [fetchError, setFetchError] = useState<string | null>(null);

  // ── RSS state ───────────────────────────────────────────────────────────────
  const [rssStatus, setRssStatus] = useState<RSSStatus | null>(null);
  const [rssRefreshing, setRssRefreshing] = useState(false);
  const [rssError, setRssError] = useState<string | null>(null);

  // ── Load torrent list ───────────────────────────────────────────────────────
  const loadTorrents = useCallback(async (q?: string) => {
    setListLoading(true);
    setListError(null);
    try {
      const data = await bluecogApi.listTorrents(q);
      setTorrents(data.torrents);
    } catch (e) {
      setListError(e instanceof APIError ? e.message : 'Failed to load torrents');
    } finally {
      setListLoading(false);
    }
  }, []);

  useEffect(() => { loadTorrents(); }, [loadTorrents]);

  // ── RSS status polling ──────────────────────────────────────────────────────
  const loadRssStatus = useCallback(async () => {
    try {
      const s = await bluecogApi.rssStatus();
      setRssStatus(s);
      return s;
    } catch {
      return null;
    }
  }, []);

  useEffect(() => {
    loadRssStatus();
  }, [loadRssStatus]);

  useEffect(() => {
    if (!rssStatus || rssStatus.status !== 'running') return;
    const id = setInterval(async () => {
      const s = await loadRssStatus();
      if (s && s.status !== 'running') {
        clearInterval(id);
        loadTorrents(search || undefined);
      }
    }, RSS_POLL_MS);
    return () => clearInterval(id);
  }, [rssStatus, loadRssStatus, loadTorrents, search]);

  // ── Search ──────────────────────────────────────────────────────────────────
  const handleSearch = (val: string) => {
    setSearch(val);
    loadTorrents(val || undefined);
  };

  // ── Selection ───────────────────────────────────────────────────────────────
  const toggleOne = (filename: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(filename) ? next.delete(filename) : next.add(filename);
      return next;
    });
  };

  const toggleAll = () => {
    if (selected.size === torrents.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(torrents.map((t) => t.filename)));
    }
  };

  // ── Submit ──────────────────────────────────────────────────────────────────
  const handleSubmit = async () => {
    if (selected.size === 0) return;
    setSubmitting(true);
    setSubmitError(null);
    setSubmitResults([]);
    try {
      const res = await bluecogApi.submit(
        Array.from(selected),
        mode,
        label.trim() || undefined,
      );
      setSubmitResults(res.submitted);
      if (res.errors.length > 0) {
        setSubmitError(res.errors.map((e) => `${e.filename}: ${e.error}`).join(' | '));
      }
      if (res.submitted.length === 1 && res.errors.length === 0) {
        navigate(`/tasks/${res.submitted[0].taskId}`);
        return;
      }
      setSelected(new Set());
    } catch (e) {
      setSubmitError(e instanceof APIError ? e.message : 'Submission failed');
    } finally {
      setSubmitting(false);
    }
  };

  // ── Manual URL fetch ────────────────────────────────────────────────────────
  const handleFetchUrl = async (e: React.FormEvent) => {
    e.preventDefault();
    const url = fetchUrl.trim();
    if (!url) return;
    setFetching(true);
    setFetchMsg(null);
    setFetchError(null);
    try {
      const res = await bluecogApi.fetchUrl(url);
      setFetchMsg(`Downloaded: ${res.filename}`);
      setFetchUrl('');
      await loadTorrents(search || undefined);
    } catch (err) {
      setFetchError(err instanceof APIError ? err.message : 'Fetch failed');
    } finally {
      setFetching(false);
    }
  };

  // ── RSS refresh ─────────────────────────────────────────────────────────────
  const handleRssRefresh = async () => {
    setRssRefreshing(true);
    setRssError(null);
    try {
      await bluecogApi.rssRefresh();
      // Immediately poll status so UI shows "running"
      await loadRssStatus();
    } catch (e) {
      setRssError(e instanceof APIError ? e.message : 'Refresh failed');
    } finally {
      setRssRefreshing(false);
    }
  };

  // ── Derived ─────────────────────────────────────────────────────────────────
  const allSelected = torrents.length > 0 && selected.size === torrents.length;
  const rssRunning  = rssStatus?.status === 'running';

  return (
    <div className={styles.page}>
      {/* ── Header bar ─────────────────────────────────────────────────────── */}
      <section className={styles.topBar}>
        <div className={styles.topLeft}>
          <h1 className={styles.title}>BlueCog</h1>
          <span className={styles.subtitle}>BlueCog scraper</span>
        </div>
        <div className={styles.topActions}>
          <Link to="/" className="btn btn-sm">Home</Link>
        </div>
      </section>

      <div className={styles.layout}>
        {/* ── Left column ─────────────────────────────────────────────────── */}
        <div className={styles.leftCol}>

          {/* Manual URL input */}
          <section className={styles.panel}>
            <h2 className={styles.panelTitle}>Manual URL Fetch</h2>
            <p className={styles.panelDesc}>
              Paste a BlueCog source URL to download its torrent file directly into the library below.
            </p>
            <form onSubmit={handleFetchUrl} className={styles.urlForm}>
              <input
                className="input"
                type="url"
                placeholder="https://…"
                value={fetchUrl}
                onChange={(e) => setFetchUrl(e.target.value)}
                disabled={fetching}
              />
              <button
                className="btn btn-primary"
                type="submit"
                disabled={fetching || !fetchUrl.trim()}
              >
                {fetching ? 'Fetching…' : 'Fetch'}
              </button>
            </form>
            {fetchMsg  && <p className={styles.fetchOk}>{fetchMsg}</p>}
            {fetchError && <p className={styles.fetchErr}>{fetchError}</p>}
            {fetching && (
              <p className={styles.fetchHint}>
                Opening browser — this may take up to 2 minutes…
              </p>
            )}
          </section>

          {/* Torrent library */}
          <section className={styles.panel}>
            <div className={styles.libraryHeader}>
              <h2 className={styles.panelTitle}>
                Torrent Library
                {!listLoading && (
                  <span className={styles.count}>{torrents.length}</span>
                )}
              </h2>
              <button
                className="btn btn-sm"
                onClick={() => loadTorrents(search || undefined)}
                disabled={listLoading}
              >
                Refresh
              </button>
            </div>

            {/* Search */}
            <div className={styles.searchRow}>
              <input
                className="input"
                type="search"
                placeholder="Search by title or filename…"
                value={search}
                onChange={(e) => handleSearch(e.target.value)}
              />
            </div>

            <ErrorBanner message={listError} onDismiss={() => setListError(null)} />

            {/* Table */}
            {listLoading ? (
              <div className={styles.loading}><span className="spinner" /> Loading…</div>
            ) : torrents.length === 0 ? (
              <p className={styles.empty}>
                {search ? 'No results for that search.' : 'No torrent files found in the scraper downloads folder.'}
              </p>
            ) : (
              <div className={styles.tableWrap}>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th style={{ width: 32 }}>
                        <input
                          type="checkbox"
                          checked={allSelected}
                          onChange={toggleAll}
                          aria-label="Select all"
                        />
                      </th>
                      <th>Title</th>
                      <th style={{ width: 90 }}>Size</th>
                      <th style={{ width: 130 }}>Downloaded</th>
                    </tr>
                  </thead>
                  <tbody>
                    {torrents.map((t) => (
                      <tr
                        key={t.filename}
                        className={selected.has(t.filename) ? styles.rowSelected : ''}
                        onClick={() => toggleOne(t.filename)}
                        style={{ cursor: 'pointer' }}
                      >
                        <td onClick={(e) => e.stopPropagation()}>
                          <input
                            type="checkbox"
                            checked={selected.has(t.filename)}
                            onChange={() => toggleOne(t.filename)}
                          />
                        </td>
                        <td>
                          <span className={styles.torrentTitle}>{t.title}</span>
                          {t.title !== t.filename && (
                            <span className={styles.torrentFilename}>{t.filename}</span>
                          )}
                        </td>
                        <td className="muted">{humanBytes(t.sizeBytes)}</td>
                        <td className="muted">{fmtDate(t.downloadedAt)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>

        {/* ── Right sidebar ────────────────────────────────────────────────── */}
        <div className={styles.rightCol}>

          {/* RSS panel */}
          <section className={styles.panel}>
            <h2 className={styles.panelTitle}>RSS Feed</h2>
            <p className={styles.panelDesc}>
              Auto-checks every 6 hours. Newly downloaded torrents appear in the
              library; use the button below to check now.
            </p>

            {rssStatus && (
              <div className={styles.rssStatus}>
                <div className={styles.rssRow}>
                  <span className={styles.rssLabel}>Status</span>
                  <span className={`${styles.rssBadge} ${styles[`rss_${rssStatus.status}`]}`}>
                    {rssStatus.status}
                  </span>
                </div>
                <div className={styles.rssRow}>
                  <span className={styles.rssLabel}>Last run</span>
                  <span className="muted">{fmtDate(rssStatus.lastRun)}</span>
                </div>
                {rssStatus.status === 'done' && rssStatus.count > 0 && (
                  <div className={styles.rssRow}>
                    <span className={styles.rssLabel}>Downloaded</span>
                    <span>{rssStatus.count} torrent{rssStatus.count !== 1 ? 's' : ''}</span>
                  </div>
                )}
                {rssStatus.errors.length > 0 && (
                  <details className={styles.rssErrors}>
                    <summary>{rssStatus.errors.length} error{rssStatus.errors.length !== 1 ? 's' : ''}</summary>
                    <ul>
                      {rssStatus.errors.map((e, i) => (
                        <li key={i}><span className={styles.fetchErr}>{e.title || '—'}: {e.error}</span></li>
                      ))}
                    </ul>
                  </details>
                )}
              </div>
            )}

            {/* Progress log — visible while running or after completion */}
            {rssStatus && rssStatus.progress && rssStatus.progress.length > 0 && (
              <RSSProgressLog events={rssStatus.progress} />
            )}

            {rssError && <p className={styles.fetchErr}>{rssError}</p>}

            <button
              className={`btn btn-primary ${styles.rssBtn}`}
              onClick={handleRssRefresh}
              disabled={rssRefreshing || rssRunning}
            >
              {rssRunning ? (
                <><span className="spinner spinner-sm" /> Running…</>
              ) : rssRefreshing ? (
                'Queuing…'
              ) : (
                'Check RSS Now'
              )}
            </button>
          </section>

          {/* Submit panel */}
          <section className={styles.panel}>
            <h2 className={styles.panelTitle}>
              Create Tasks
              {selected.size > 0 && (
                <span className={styles.count}>{selected.size} selected</span>
              )}
            </h2>

            {submitResults.length > 0 && (
              <div className={styles.submitResults}>
                {submitResults.map((r) => (
                  <div key={r.taskId} className={styles.submitResult}>
                    <Link to={`/tasks/${r.taskId}`} className={styles.taskLink}>
                      {r.filename}
                    </Link>
                    <span className="pill neutral">
                      {r.reused ? 'reused' : r.status}
                    </span>
                  </div>
                ))}
              </div>
            )}

            <ErrorBanner
              message={submitError}
              onDismiss={() => setSubmitError(null)}
              className="mb-4"
            />

            <div className="field">
              <label className="field-label">Label (optional)</label>
              <input
                className="input"
                type="text"
                placeholder="e.g. Game night pack"
                maxLength={500}
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                disabled={submitting}
              />
            </div>

            <div className="field">
              <label className="field-label">Download mode</label>
              <div className={styles.modeGroup}>
                {(['auto', 'select'] as const).map((m) => (
                  <label
                    key={m}
                    className={`${styles.modeOption} ${mode === m ? styles.modeSelected : ''}`}
                  >
                    <input
                      type="radio"
                      name="bluecog-mode"
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

            <button
              className="btn btn-primary"
              style={{ width: '100%' }}
              onClick={handleSubmit}
              disabled={submitting || selected.size === 0}
            >
              {submitting
                ? 'Creating…'
                : selected.size === 0
                ? 'Select torrents to create tasks'
                : `Create ${selected.size} task${selected.size !== 1 ? 's' : ''}`}
            </button>
          </section>
        </div>
      </div>
    </div>
  );
}
