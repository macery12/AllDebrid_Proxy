interface ProgressBarProps {
  percent: number;
  indeterminate?: boolean;
  className?: string;
}

export function ProgressBar({ percent, indeterminate = false, className = '' }: ProgressBarProps) {
  return (
    <div className={`progress-track ${indeterminate ? 'indeterminate' : ''} ${className}`}>
      <div
        className="progress-fill"
        style={indeterminate ? undefined : { width: `${Math.max(0, Math.min(100, percent))}%` }}
      />
    </div>
  );
}
