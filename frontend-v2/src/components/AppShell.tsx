import type { ReactNode } from 'react';
import { TopBar } from './TopBar';
import styles from './AppShell.module.css';

interface AppShellProps {
  children: ReactNode;
}

export function AppShell({ children }: AppShellProps) {
  return (
    <div className={styles.shell}>
      <TopBar />
      <main className={styles.main}>{children}</main>
    </div>
  );
}
