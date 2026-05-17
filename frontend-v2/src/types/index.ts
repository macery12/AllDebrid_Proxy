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

export interface ProviderProgress {
  statusCode: number;
  statusText: string;
  filename: string;
  totalSize: number;
  downloaded: number;
  seeders: number;
  downloadSpeed: number;
  uploadSpeed: number;
}

export interface Task {
  taskId: string;
  mode: TaskMode;
  status: TaskStatus | string;
  label: string | null;
  infohash: string;
  files: TaskFile[];
  storage: StorageInfo | null;
  /** Transient: populated from provider.progress SSE events while resolving */
  providerProgress?: ProviderProgress | null;
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

export interface UserStats {
  total_magnets_processed: number;
  total_downloads: number;
  total_bytes_downloaded: number;
}

export interface AdminUser extends User {
  created_at?: string | null;
  last_login?: string | null;
  stats?: UserStats | null;
}

export interface AdminStats {
  tasks: {
    total: number;
    queued: number;
    resolving: number;
    downloading: number;
    waiting_selection: number;
    active: number;
    completed: number;
    failed: number;
    canceled: number;
  };
  files: {
    total: number;
    downloading: number;
    completed: number;
    failed: number;
  };
  downloads: {
    active_count: number;
    total_bytes: number;
    downloaded_bytes: number;
    progress_pct: number;
  };
  storage: {
    free_bytes: number;
    reserved_bytes: number;
    low_space_floor_bytes: number;
  };
  users: {
    total_users: number;
    aggregate_downloads: number;
    aggregate_bytes_downloaded: number;
  };
  queue: {
    length: number;
  };
  health: {
    worker_healthy: boolean;
  };
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
  | 'files.listed'
  | 'provider.progress';

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
  // provider.progress fields
  statusCode?: number;
  statusText?: string;
  filename?: string;
  totalSize?: number;
  downloaded?: number;
  seeders?: number;
  downloadSpeed?: number;
  uploadSpeed?: number;
  [key: string]: unknown;
}
