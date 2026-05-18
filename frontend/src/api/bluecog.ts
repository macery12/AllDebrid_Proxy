import { api } from './client';

export interface BlueCogTorrent {
  filename: string;
  title: string;
  link: string | null;
  downloadedAt: string | null;
  sizeBytes: number;
}

export interface BlueCogTorrentsResponse {
  torrents: BlueCogTorrent[];
  total: number;
}

export type RSSProgressEvent =
  | { type: 'item'; i: number; n: number; title: string;
      step: 'fetching' | 'done' | 'failed' | 'skipped';
      filename?: string; error?: string }
  | { type: 'waiting'; seconds: number };

export interface RSSStatus {
  status: 'idle' | 'running' | 'done' | 'error';
  lastRun: string | null;
  count: number;
  errors: Array<{ title: string; error: string }>;
  progress?: RSSProgressEvent[];
}

export interface FetchUrlResponse {
  filename: string;
  updated: boolean;
}

export interface SubmitResult {
  filename: string;
  taskId: string;
  status: string;
  reused: boolean;
}

export interface SubmitResponse {
  submitted: SubmitResult[];
  errors: Array<{ filename: string; error: string }>;
}

export const bluecogApi = {
  listTorrents: (q?: string) =>
    api.get<BlueCogTorrentsResponse>('/bluecog/torrents', q ? { q } : undefined),

  rssStatus: () =>
    api.get<RSSStatus>('/bluecog/rss/status'),

  rssRefresh: () =>
    api.post<{ queued: boolean }>('/bluecog/rss/refresh'),

  fetchUrl: (url: string) =>
    api.post<FetchUrlResponse>('/bluecog/fetch-url', { url }),

  submit: (filenames: string[], mode: 'auto' | 'select', label?: string) =>
    api.post<SubmitResponse>('/bluecog/submit', { filenames, mode, label }),
};
