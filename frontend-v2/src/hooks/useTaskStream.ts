import { useState, useEffect, useRef } from 'react';
import type { Task, SSEEvent } from '../types';
import { tasksApi } from '../api/tasks';
import { isFinalState, mergeTaskEvent } from '../lib/utils';

export type StreamStatus =
  | 'idle'
  | 'connecting'
  | 'connected'
  | 'reconnecting'
  | 'final'
  | 'closed';

/**
 * Opens an SSE stream for a task once `enabled` is true.
 * Calls `onUpdate` with a functional state updater whenever events arrive.
 * Reconnects with exponential backoff on failure (max 5 attempts).
 */
export function useTaskStream(
  taskId: string | undefined,
  enabled: boolean,
  onUpdate: (updater: (prev: Task | null) => Task | null) => void,
): StreamStatus {
  const [status, setStatus] = useState<StreamStatus>('idle');

  // Keep onUpdate stable so the effect closure always has the latest version
  const onUpdateRef = useRef(onUpdate);
  useEffect(() => {
    onUpdateRef.current = onUpdate;
  });

  useEffect(() => {
    if (!taskId || !enabled) {
      setStatus(enabled ? 'idle' : 'final');
      return;
    }

    let active = true;
    let attempts = 0;
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined;
    let es: EventSource | null = null;

    async function connect() {
      if (!active) return;

      try {
        const { token } = await tasksApi.getSseToken(taskId!);
        if (!active) return;

        const url =
          `/api/tasks/${encodeURIComponent(taskId!)}/events` +
          `?token=${encodeURIComponent(token)}`;

        es = new EventSource(url);
        setStatus('connecting');

        es.onopen = () => {
          if (!active) return;
          setStatus('connected');
          attempts = 0;
        };

        es.onmessage = (evt) => {
          if (!active) return;
          try {
            const event = JSON.parse(evt.data) as SSEEvent;

            onUpdateRef.current((prev) =>
              prev ? mergeTaskEvent(prev, event) : prev,
            );

            if (event.status && isFinalState(event.status)) {
              setStatus('final');
              active = false;
              es?.close();
            }
          } catch {
            // ignore malformed events
          }
        };

        es.onerror = () => {
          es?.close();
          es = null;
          if (!active) return;

          if (attempts >= 5) {
            setStatus('closed');
            return;
          }

          setStatus('reconnecting');
          const delay = Math.min(2 ** attempts * 1000, 30_000);
          attempts += 1;
          reconnectTimer = setTimeout(connect, delay);
        };
      } catch {
        if (active) setStatus('closed');
      }
    }

    void connect();

    return () => {
      active = false;
      clearTimeout(reconnectTimer);
      es?.close();
    };
  }, [taskId, enabled]);

  return status;
}
