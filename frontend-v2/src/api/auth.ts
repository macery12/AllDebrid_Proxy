import { api } from './client';
import type { User } from '../types';

export interface LoginRequest {
  username: string;
  password: string;
}

export interface LoginResponse {
  user: User;
  first_time_setup?: boolean;
  message?: string;
}

export interface SetupStatusResponse {
  first_time_setup: boolean;
}

export const authApi = {
  me: () => api.get<User>('/auth/me'),
  login: (data: LoginRequest) => api.post<LoginResponse>('/auth/login', data),
  logout: () => api.post<{ ok: boolean }>('/auth/logout'),
  setupStatus: () => api.get<SetupStatusResponse>('/auth/setup-status'),
};
