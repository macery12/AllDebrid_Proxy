import { api } from './client';
import type { Task, TaskSummary, FileEntry } from '../types';
export type { TaskSummary };

export interface CreateTaskPayload {
  source: string;
  mode: 'auto' | 'select';
  label?: string;
}

export interface CreateTaskResponse {
  taskId: string;
  status: string;
  reused: boolean;
  message?: string;
}

export interface TaskListResponse {
  tasks: TaskSummary[];
  total: number;
}

export interface FilesResponse {
  entries: FileEntry[];
}

export interface DownloadTokenResponse {
  token: string;
  expires_in: number;
}

export const tasksApi = {
  list: (params?: { limit?: number; offset?: number }) =>
    api.get<TaskListResponse>('/tasks', params),

  create: (data: CreateTaskPayload) =>
    api.post<CreateTaskResponse>('/tasks', data),

  get: (taskId: string) => api.get<Task>(`/tasks/${taskId}`),

  select: (taskId: string, fileIds: string[]) =>
    api.post<{ status: string }>(`/tasks/${taskId}/select`, { fileIds }),

  cancel: (taskId: string) =>
    api.post<{ status: string }>(`/tasks/${taskId}/cancel`),

  delete: (taskId: string, purgeFiles = false) =>
    api.delete<{ ok: boolean }>(`/tasks/${taskId}`, { purge_files: purgeFiles }),

  getFiles: (taskId: string) =>
    api.get<FilesResponse>(`/tasks/${taskId}/files`),

  /** Obtain a short-lived download token for use in ?token= query params. */
  getDownloadToken: (taskId: string) =>
    api.post<DownloadTokenResponse>(`/files/${taskId}/dl-token`),
};
