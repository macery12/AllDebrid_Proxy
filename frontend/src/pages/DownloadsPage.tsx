import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

export function DownloadsPage() {
  const [taskId, setTaskId] = useState('');
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const id = taskId.trim();
    if (!id) {
      setError('Please enter a task ID');
      return;
    }
    // Basic UUID shape check
    if (!/^[0-9a-f-]{36}$/.test(id)) {
      setError('Invalid task ID format');
      return;
    }
    navigate(`/tasks/${encodeURIComponent(id)}/files`);
  };

  return (
    <div style={{ maxWidth: 500, margin: '0 auto', padding: '2rem 1rem' }}>
      <h1 style={{ marginBottom: '1.5rem' }}>Downloads</h1>
      <div className="card" style={{ padding: '1.5rem' }}>
        <p className="muted" style={{ marginBottom: '1rem' }}>
          Enter a task ID to view and download files.
        </p>
        <form onSubmit={handleSubmit} style={{ display: 'flex', gap: '0.5rem' }}>
          <input
            className="input"
            type="text"
            placeholder="Paste task ID…"
            value={taskId}
            onChange={(e) => {
              setTaskId(e.target.value);
              setError(null);
            }}
            style={{ flex: 1 }}
            autoComplete="off"
            spellCheck={false}
          />
          <button className="btn btn-primary" type="submit">
            Open
          </button>
        </form>
        {error && (
          <p className="muted small" style={{ marginTop: '0.5rem', color: 'var(--color-error, #e74c3c)' }}>
            {error}
          </p>
        )}
      </div>
    </div>
  );
}
