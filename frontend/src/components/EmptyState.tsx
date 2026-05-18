interface EmptyStateProps {
  message?: string;
  icon?: React.ReactNode;
  children?: React.ReactNode;
}

export function EmptyState({ message, icon, children }: EmptyStateProps) {
  return (
    <div className="empty-state">
      {icon ?? (
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden>
          <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" />
          <polyline points="13 2 13 9 20 9" />
        </svg>
      )}
      {message && <p>{message}</p>}
      {children}
    </div>
  );
}
