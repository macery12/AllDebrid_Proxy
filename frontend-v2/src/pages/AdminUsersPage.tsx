import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { adminApi } from '../api/admin';
import { useAuth } from '../context/AuthContext';
import type { AdminUser, UserRole } from '../types';
import { ErrorBanner } from '../components/ErrorBanner';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { EmptyState } from '../components/EmptyState';
import { formatBytes, formatDateTime } from '../lib/utils';
import { APIError } from '../api/client';
import styles from './AdminUsersPage.module.css';

const ROLES: UserRole[] = ['user', 'member', 'admin'];

export function AdminUsersPage() {
  const { user: currentUser } = useAuth();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [role, setRole] = useState<UserRole>('user');
  const [creating, setCreating] = useState(false);
  const [deleteUser, setDeleteUser] = useState<AdminUser | null>(null);
  const [resetUser, setResetUser] = useState<AdminUser | null>(null);
  const [resetPassword, setResetPassword] = useState('');
  const [submittingReset, setSubmittingReset] = useState(false);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await adminApi.users();
      setUsers(data.users);
    } catch (e) {
      setError(e instanceof APIError ? e.message : 'Failed to load users');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const sortedUsers = useMemo(() => {
    return [...users].sort((a, b) => a.username.localeCompare(b.username));
  }, [users]);

  const handleCreate = async (event: React.FormEvent) => {
    event.preventDefault();
    setCreating(true);
    setError(null);
    try {
      await adminApi.createUser({ username, password, role });
      setUsername('');
      setPassword('');
      setRole('user');
      await load();
    } catch (e) {
      setError(e instanceof APIError ? e.message : 'Failed to create user');
    } finally {
      setCreating(false);
    }
  };

  const handleRoleChange = async (userId: number, nextRole: UserRole) => {
    setError(null);
    try {
      await adminApi.setRole(userId, nextRole);
      await load();
    } catch (e) {
      setError(e instanceof APIError ? e.message : 'Failed to update role');
    }
  };

  const handleDelete = async () => {
    if (!deleteUser) return;
    try {
      await adminApi.deleteUser(deleteUser.id);
      setDeleteUser(null);
      await load();
    } catch (e) {
      setError(e instanceof APIError ? e.message : 'Failed to delete user');
    }
  };

  const handleResetPassword = async () => {
    if (!resetUser || !resetPassword) return;
    setSubmittingReset(true);
    try {
      await adminApi.resetPassword(resetUser.id, resetPassword);
      setResetPassword('');
      setResetUser(null);
    } catch (e) {
      setError(e instanceof APIError ? e.message : 'Failed to reset password');
    } finally {
      setSubmittingReset(false);
    }
  };

  return (
    <div className={styles.page}>
      <section className={styles.topBar}>
        <div>
          <h1 className={styles.title}>Admin Users</h1>
          <p className={styles.subtitle}>Create users, change roles, and reset credentials.</p>
        </div>
        <div className={styles.actions}>
          <Link to="/admin" className="btn">Admin</Link>
          <Link to="/" className="btn btn-good">New Task</Link>
        </div>
      </section>

      <ErrorBanner message={error} onDismiss={() => setError(null)} />

      <section className={styles.panel}>
        <p className={styles.panelTitle}>Create User</p>
        <form className={styles.createForm} onSubmit={handleCreate}>
          <input className="input" placeholder="Username" value={username} onChange={(e) => setUsername(e.target.value)} required />
          <input className="input" type="password" placeholder="Password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          <select className="select" value={role} onChange={(e) => setRole(e.target.value as UserRole)}>
            <option value="user">User</option>
            <option value="member">Member</option>
            <option value="admin">Admin</option>
          </select>
          <button className="btn btn-good" type="submit" disabled={creating}>{creating ? 'Creating…' : 'Create User'}</button>
        </form>
      </section>

      <section className={styles.panel}>
        <p className={styles.panelTitle}>Users</p>
        {loading ? (
          <div className="flex flex-center gap-2 muted" style={{ padding: 40 }}>
            <span className="spinner" />
            Loading users…
          </div>
        ) : sortedUsers.length === 0 ? (
          <EmptyState message="No users found" />
        ) : (
          <div className={styles.tableWrap}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Username</th>
                  <th>Role</th>
                  <th>Stats</th>
                  <th>Created</th>
                  <th>Last Login</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {sortedUsers.map((user) => {
                  const isCurrent = user.id === currentUser?.id;
                  return (
                    <tr key={user.id}>
                      <td className="muted small">{user.id}</td>
                      <td>
                        <div className={styles.userName}>{user.username} {isCurrent && <span className={styles.selfTag}>you</span>}</div>
                      </td>
                      <td>
                        <select
                          className="select"
                          value={user.role}
                          disabled={isCurrent}
                          onChange={(e) => void handleRoleChange(user.id, e.target.value as UserRole)}
                        >
                          {ROLES.map((roleOption) => (
                            <option key={roleOption} value={roleOption}>{roleOption}</option>
                          ))}
                        </select>
                      </td>
                      <td className={styles.statsCell}>
                        <span>{user.stats?.total_downloads ?? 0} downloads</span>
                        <span>{formatBytes(user.stats?.total_bytes_downloaded ?? 0)}</span>
                      </td>
                      <td className="muted small">{formatDateTime(user.created_at ?? null)}</td>
                      <td className="muted small">{formatDateTime(user.last_login ?? null)}</td>
                      <td>
                        {isCurrent ? (
                          <span className="muted small">Current account</span>
                        ) : (
                          <div className={styles.rowActions}>
                            <button className="btn btn-sm" onClick={() => setResetUser(user)}>Reset Password</button>
                            <button className="btn btn-danger btn-sm" onClick={() => setDeleteUser(user)}>Delete</button>
                          </div>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <ConfirmDialog
        open={!!deleteUser}
        title="Delete user?"
        message={deleteUser ? `Delete ${deleteUser.username}? This cannot be undone.` : ''}
        confirmLabel="Delete"
        dangerous
        onConfirm={() => void handleDelete()}
        onCancel={() => setDeleteUser(null)}
      />

      {resetUser && (
        <div className="dialog-backdrop" onClick={(e) => { if (e.target === e.currentTarget) setResetUser(null); }}>
          <div className="dialog-box">
            <p className="dialog-title">Reset Password</p>
            <p className="dialog-message">Set a new password for {resetUser.username}.</p>
            <input
              className="input"
              type="password"
              placeholder="New password"
              value={resetPassword}
              onChange={(e) => setResetPassword(e.target.value)}
            />
            <div className="dialog-actions" style={{ marginTop: 16 }}>
              <button className="btn" onClick={() => { setResetUser(null); setResetPassword(''); }}>Cancel</button>
              <button className="btn btn-good" onClick={() => void handleResetPassword()} disabled={submittingReset || !resetPassword}>
                {submittingReset ? 'Saving…' : 'Save Password'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
