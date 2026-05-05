import type { StreamStatus } from '../hooks/useTaskStream';

const LABELS: Record<StreamStatus, string> = {
  idle:         'Idle',
  connecting:   'Connecting…',
  connected:    'Live',
  reconnecting: 'Reconnecting…',
  final:        'Completed',
  closed:       'Disconnected',
};

interface StreamIndicatorProps {
  status: StreamStatus;
}

export function StreamIndicator({ status }: StreamIndicatorProps) {
  return (
    <span className="stream-indicator">
      <span className={`stream-dot ${status}`} />
      {LABELS[status]}
    </span>
  );
}
