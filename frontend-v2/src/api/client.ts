const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? '/v2';

export class APIError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = 'APIError';
  }
}

type Params = Record<string, string | number | boolean | undefined | null>;

async function request<T>(
  method: string,
  path: string,
  options?: { body?: unknown; params?: Params },
): Promise<T> {
  const url = new URL(`${API_BASE}${path}`, window.location.origin);
  if (options?.params) {
    for (const [key, value] of Object.entries(options.params)) {
      if (value !== undefined && value !== null) {
        url.searchParams.set(key, String(value));
      }
    }
  }

  const init: RequestInit = {
    method,
    credentials: 'include',
  };

  if (options?.body !== undefined) {
    init.headers = { 'Content-Type': 'application/json' };
    init.body = JSON.stringify(options.body);
  }

  const response = await fetch(url.toString(), init);

  if (response.status === 401) {
    window.location.href = '/login';
    throw new APIError('Unauthorized', 401);
  }

  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const data = (await response.json()) as Record<string, unknown>;
      const raw = data.message ?? data.detail ?? data.error;
      if (typeof raw === 'string') message = raw;
    } catch {
      // ignore
    }
    throw new APIError(message, response.status);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

export const api = {
  get: <T>(path: string, params?: Params) =>
    request<T>('GET', path, { params }),
  post: <T>(path: string, body?: unknown) =>
    request<T>('POST', path, { body }),
  delete: <T>(path: string, params?: Params) =>
    request<T>('DELETE', path, { params }),
};
