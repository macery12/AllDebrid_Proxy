import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { authApi } from '../api/auth';
import { APIError } from '../api/client';
import { ErrorBanner } from '../components/ErrorBanner';
import styles from './LoginPage.module.css';

export function LoginPage() {
  const { user, login } = useAuth();
  const navigate = useNavigate();

  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [isFirstTime, setIsFirstTime] = useState(false);
  const [setupSuccess, setSetupSuccess] = useState<string | null>(null);

  // Redirect if already logged in
  useEffect(() => {
    if (user) navigate('/', { replace: true });
  }, [user, navigate]);

  // Check first-time setup
  useEffect(() => {
    authApi
      .setupStatus()
      .then((d) => setIsFirstTime(d.first_time_setup))
      .catch(() => setIsFirstTime(false));
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password.trim()) {
      setError('Username and password are required.');
      return;
    }

    setLoading(true);
    setError(null);
    setSetupSuccess(null);

    try {
      const res = await authApi.login({ username: username.trim(), password: password.trim() });

      if (res.first_time_setup) {
        // Admin account created — prompt to log in
        setSetupSuccess(res.message ?? 'Admin account created. Please log in.');
        setIsFirstTime(false);
        setPassword('');
      } else {
        await login({ username: username.trim(), password: password.trim() });
        navigate('/', { replace: true });
      }
    } catch (e) {
      setError(e instanceof APIError ? e.message : 'Login failed. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className={styles.page}>
      <div className={styles.box}>
        <div className={styles.logo}>
          <div className={styles.logoIcon}>
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2" aria-hidden>
              <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" />
            </svg>
          </div>
        </div>

        <h1 className={styles.title}>
          {isFirstTime ? 'Create Admin Account' : 'Sign In'}
        </h1>
        <p className={styles.subtitle}>
          {isFirstTime
            ? 'No accounts exist yet. Create the first admin account.'
            : 'AllDebrid Proxy control panel'}
        </p>

        {setupSuccess && (
          <div className={`alert alert-success ${styles.setupBadge}`} role="status">
            {setupSuccess}
          </div>
        )}

        <ErrorBanner message={error} onDismiss={() => setError(null)} />

        <form className={styles.form} onSubmit={handleSubmit} noValidate>
          <div className="field">
            <label htmlFor="username" className="field-label">Username</label>
            <input
              id="username"
              className="input"
              type="text"
              autoComplete="username"
              autoFocus
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              disabled={loading}
              required
            />
          </div>

          <div className="field">
            <label htmlFor="password" className="field-label">Password</label>
            <input
              id="password"
              className="input"
              type="password"
              autoComplete={isFirstTime ? 'new-password' : 'current-password'}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={loading}
              required
            />
          </div>

          <button
            type="submit"
            className={`btn btn-primary btn-lg ${styles.submitBtn}`}
            disabled={loading}
          >
            {loading && <span className="spinner" />}
            {isFirstTime ? 'Create Admin Account' : 'Sign In'}
          </button>
        </form>
      </div>
    </div>
  );
}
