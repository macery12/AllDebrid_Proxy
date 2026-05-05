import { useState, useEffect } from 'react';
import type { Task } from '../types';
import { tasksApi } from '../api/tasks';
import { APIError } from '../api/client';

export function useTask(taskId: string | undefined) {
  const [task, setTask] = useState<Task | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!taskId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    setTask(null);

    tasksApi
      .get(taskId)
      .then(setTask)
      .catch((e: unknown) => {
        setError(e instanceof APIError ? e.message : 'Failed to load task');
      })
      .finally(() => setLoading(false));
  }, [taskId]);

  return { task, setTask, loading, error };
}
