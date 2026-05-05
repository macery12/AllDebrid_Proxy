import { getStatusVariant } from '../lib/utils';

interface StatusBadgeProps {
  status: string;
  className?: string;
}

export function StatusBadge({ status, className = '' }: StatusBadgeProps) {
  const variant = getStatusVariant(status);
  return (
    <span className={`pill ${variant} ${className}`}>
      {status}
    </span>
  );
}
