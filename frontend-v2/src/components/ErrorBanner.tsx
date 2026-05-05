interface ErrorBannerProps {
  message: string | null | undefined;
  onDismiss?: () => void;
  className?: string;
}

export function ErrorBanner({ message, onDismiss, className = '' }: ErrorBannerProps) {
  if (!message) return null;
  return (
    <div className={`alert alert-error ${className}`} role="alert">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden style={{ flexShrink: 0, marginTop: 2 }}>
        <circle cx="12" cy="12" r="10" />
        <line x1="12" y1="8" x2="12" y2="12" />
        <line x1="12" y1="16" x2="12.01" y2="16" />
      </svg>
      <span style={{ flex: 1 }}>{message}</span>
      {onDismiss && (
        <button
          className="btn btn-sm"
          style={{ border: 'none', padding: '0 4px', marginLeft: 'auto', color: 'inherit', background: 'transparent' }}
          onClick={onDismiss}
          aria-label="Dismiss"
        >
          ✕
        </button>
      )}
    </div>
  );
}
