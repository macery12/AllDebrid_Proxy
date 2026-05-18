import { useState, useEffect } from 'react';
import { api } from '../api/client';

type Health = 'loading' | 'ok' | 'down';

type HealthResponse = {
  ok?: boolean;
  status?: string;
};

export function HealthBadge() {
  const [health, setHealth] = useState<Health>('loading');

  useEffect(() => {
    const check = () => {
      api
        .get<HealthResponse>('/health')
        .then((d) => {
          const healthy = d.ok === true || d.status === 'ok' || d.status === 'healthy';
          setHealth(healthy ? 'ok' : 'down');
        })
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
