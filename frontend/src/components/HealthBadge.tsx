import { useState, useEffect } from 'react';

type Health = 'loading' | 'ok' | 'down';

type HealthResponse = {
  ok?: boolean;
  status?: string;
};

export function HealthBadge() {
  const [health, setHealth] = useState<Health>('loading');

  useEffect(() => {
    // Call /health directly — not through the /api prefix wrapper
    const check = () => {
      fetch('/health', { credentials: 'include' })
        .then((r) => r.json() as Promise<HealthResponse>)
        .then((d) => setHealth(d.ok === true ? 'ok' : 'down'))
        .catch(() => setHealth('down'));
    };
    check();
    const interval = setInterval(check, 30_000);
    return () => clearInterval(interval);
  }, []);

  if (health === 'loading') return null;

  return (
    <span className={`pill ${health === 'ok' ? 'good' : 'bad'}`}>
      {health === 'ok' ? '● API' : '● API Down'}
    </span>
  );
}
