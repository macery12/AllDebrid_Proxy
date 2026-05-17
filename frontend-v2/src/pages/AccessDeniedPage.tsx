import { useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import styles from './AccessDeniedPage.module.css';

export function AccessDeniedPage() {
  const { user } = useAuth();
  const location = useLocation();

  const role = user?.role ?? 'user';

  const roleGuidance =
    role === 'admin'
      ? {
          heading: 'Admin access is required for this area.',
          allowed: [
            'Task creation and task detail pages',
            'File browser and video player pages',
            'Admin dashboard and user management pages',
          ],
        }
      : role === 'member'
        ? {
            heading: 'This area is limited to administrators.',
            allowed: [
              'Task creation page',
              'Task detail pages',
              'Task files and player pages',
            ],
          }
        : {
            heading: 'Your account currently has download-only access.',
            allowed: [
              'Direct download links provided to your account',
              'Direct streaming links provided to your account',
              'No task or admin management pages',
            ],
          };

  return (
    <div className={styles.page}>
      <div className={styles.panel}>
        <p className={styles.code}>403</p>
        <h1 className={styles.title}>Access denied</h1>
        <p className={styles.message}>{roleGuidance.heading}</p>

        <div className={styles.infoBlock}>
          <p className={styles.infoTitle}>Requested area</p>
          <p className={styles.path}>{location.pathname}</p>
        </div>

        <div className={styles.infoBlock}>
          <p className={styles.infoTitle}>Allowed for your role ({role})</p>
          <ul className={styles.allowedList}>
            {roleGuidance.allowed.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>

        <p className={styles.note}>If you need broader access, contact an administrator to update your role.</p>
      </div>
    </div>
  );
}
