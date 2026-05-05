// Domain types matching the FastAPI schema

export type TaskStatus =
  | 'queued'
  | 'resolving'
  | 'waiting_selection'
  | 'downloading'
  | 'ready'
  | 'done'
  | 'completed'
  | 'failed'
  | 'canceled';

export type FileState = 'listed' | 'selected' | 'downloading' | 'done' | 'failed';

export type TaskMode = 'auto' | 'select';

export type UserRole = 'admin' | 'member' | 'user';

export interface TaskFile {
  fileId: string;
  index: number;
  name: string;
  size: number | null;
  state: FileState | string;
  bytesDownloaded: number;
  speedBps: number;
  etaSeconds: number | null;
  progressPct: number;
}

export interface StorageInfo {
  freeBytes: number;
  taskTotalSize: number;
  taskReservedBytes: number;
  globalReservedBytes: number;
  lowSpaceFloorBytes: number;
  willStartWhenFreeBytesAtLeast: number | null;
}

export interface Task {
  taskId: string;
  mode: TaskMode;
  status: TaskStatus | string;
  label: string | null;
  infohash: string;
  files: TaskFile[];
  storage: StorageInfo | null;
}

export interface TaskSummary {
  taskId: string;
  id: string;
  label: string | null;
  mode: TaskMode;
  status: TaskStatus | string;
  created_at: string | null;
  updated_at: string | null;
  source?: string;
}

export interface User {
  id: number;
  username: string;
  is_admin: boolean;
  role: UserRole;
}

export interface FileEntry {
  rel: string;
  size: number;
  is_video: boolean;
  is_downloading: boolean;
}

// SSE event payloads
export type SSEEventType =
  | 'hello'
  | 'state'
  | 'file.state'
  | 'file.progress'
  | 'file.done'
  | 'file.failed'
  | 'files.listed';

export interface SSEEvent {
  type: SSEEventType | string;
  taskId?: string;
  status?: string;
  files?: TaskFile[];
  fileId?: string;
  state?: string;
  bytesDownloaded?: number;
  speedBps?: number;
  etaSeconds?: number;
  progressPct?: number;
  name?: string;
  size?: number;
  [key: string]: unknown;
}
