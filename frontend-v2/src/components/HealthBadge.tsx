import { useState, useEffect } from 'react';
import { api } from '../api/client';

type Health = 'loading' | 'ok' | 'down';

export function HealthBadge() {
  const [health, setHealth] = useState<Health>('loading');

  useEffect(() => {
    const check = () => {
      api
        .get<{ status: string }>('/health')
        .then((d) => setHealth(d.status === 'ok' ? 'ok' : 'down'))
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
