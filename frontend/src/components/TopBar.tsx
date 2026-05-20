import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { HealthBadge } from './HealthBadge';
import styles from './TopBar.module.css';

export function TopBar() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = async () => {
    await logout();
    navigate('/login');
  };

  const isUser = user?.role === 'user';

  return (
    <header className={styles.header}>
      <Link to={isUser ? '/downloads' : '/'} className={styles.logo}>
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
          <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" />
        </svg>
        AllDebrid Proxy
      </Link>
      <nav className={styles.nav}>
        {user?.role === 'admin' && (
          <>
            <Link to="/admin" className={styles.navLink}>Admin</Link>
            <Link to="/admin/users" className={styles.navLink}>Users</Link>
          </>
        )}
        {(user?.role === 'admin' || user?.role === 'member') && (
          <>
            <Link to="/" className={styles.navLink}>Tasks</Link>
            <Link to="/bluecog" className={styles.navLink}>BlueCog</Link>
          </>
        )}
        {isUser && (
          <Link to="/downloads" className={styles.navLink}>Downloads</Link>
        )}
        <HealthBadge />
        {user && (
          <>
            <span className={styles.username}>{user.username}</span>
            <button className="btn btn-sm" onClick={handleLogout}>
              Logout
            </button>
          </>
        )}
      </nav>
    </header>
  );
}
