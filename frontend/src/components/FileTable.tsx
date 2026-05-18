import type { TaskFile } from '../types';
import { StatusBadge } from './StatusBadge';
import { ProgressBar } from './ProgressBar';
import { EmptyState } from './EmptyState';
import { formatBytes, formatSpeed, formatEta } from '../lib/utils';
import styles from './FileTable.module.css';

interface FileTableProps {
  files: TaskFile[];
  selectable?: boolean;
  selectedIds?: Set<string>;
  onToggle?: (fileId: string) => void;
  onToggleAll?: (select: boolean) => void;
  loading?: boolean;
}

export function FileTable({
  files,
  selectable = false,
  selectedIds = new Set(),
  onToggle,
  onToggleAll,
  loading = false,
}: FileTableProps) {
  const allSelected = files.length > 0 && files.every((f) => selectedIds.has(f.fileId));
  const someSelected = files.some((f) => selectedIds.has(f.fileId));

  if (loading) {
    return (
      <EmptyState>
        <div className="flex flex-center gap-2" style={{ marginTop: 8 }}>
          <span className="spinner" />
          <span className="muted small">Waiting for file list…</span>
        </div>
      </EmptyState>
    );
  }

  if (files.length === 0) {
    return (
      <EmptyState>
        <div className="flex flex-center gap-2" style={{ marginTop: 8 }}>
          <span className="spinner" />
          <span className="muted small">Waiting for file list…</span>
        </div>
      </EmptyState>
    );
  }

  return (
    <div className={styles.wrapper}>
      <table className="data-table">
        <thead>
          <tr>
            {selectable && (
              <th style={{ width: 44, textAlign: 'center' }}>
                <input
                  type="checkbox"
                  className="check"
                  checked={allSelected}
                  ref={(el) => { if (el) el.indeterminate = !allSelected && someSelected; }}
                  onChange={(e) => onToggleAll?.(e.target.checked)}
                  aria-label="Select all"
                />
              </th>
            )}
            <th>File</th>
            <th style={{ width: 120, textAlign: 'right' }}>Size</th>
            <th style={{ width: 300 }}>Progress</th>
            <th style={{ width: 120 }}>State</th>
          </tr>
        </thead>
        <tbody>
          {files.map((file) => {
            const sizeBytes = file.size ?? 0;
            const downloaded = file.bytesDownloaded ?? 0;
            const percent =
              sizeBytes > 0
                ? Math.max(0, Math.min(100, Math.round((downloaded / sizeBytes) * 100)))
                : (file.progressPct ?? 0);
            const isResolving =
              sizeBytes === 0 && (file.state || '').toLowerCase() === 'downloading';
            const isFinalFile =
              file.state === 'done' || file.state === 'failed';
            const speedBps = isFinalFile ? 0 : (file.speedBps ?? 0);

            return (
              <tr
                key={file.fileId}
                data-file-id={file.fileId}
                className={selectable && selectedIds.has(file.fileId) ? styles.rowSelected : ''}
              >
                {selectable && (
                  <td style={{ textAlign: 'center' }}>
                    <input
                      type="checkbox"
                      className="check"
                      checked={selectedIds.has(file.fileId)}
                      onChange={() => onToggle?.(file.fileId)}
                      aria-label={`Select ${file.name}`}
                    />
                  </td>
                )}
                <td>
                  <div className={styles.fileName}>{file.name || file.fileId}</div>
                </td>
                <td style={{ textAlign: 'right' }} className="muted small">
                  {sizeBytes > 0 ? formatBytes(sizeBytes) : '—'}
                </td>
                <td>
                  <div className={styles.progressCell}>
                    <ProgressBar percent={percent} indeterminate={isResolving} />
                    <div className={styles.progressMeta}>
                      {isResolving ? (
                        <span className="muted">Resolving…</span>
                      ) : (
                        <span>{formatBytes(downloaded)} / {formatBytes(sizeBytes)}</span>
                      )}
                      <span>{formatSpeed(speedBps)}</span>
                      <span>{isResolving ? '' : formatEta(file.etaSeconds)}</span>
                    </div>
                  </div>
                </td>
                <td>
                  <StatusBadge status={file.state || '—'} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
