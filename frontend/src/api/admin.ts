import { api } from './client';
import type { AdminStats, AdminUser, TaskSummary, UserRole } from '../types';

export interface AdminTasksResponse {
  tasks: TaskSummary[];
  total: number;
}

export interface AdminUsersResponse {
  users: AdminUser[];
}

export interface CreateAdminUserPayload {
  username: string;
  password: string;
  role: UserRole;
}

export const adminApi = {
  stats: () => api.get<AdminStats>('/admin/stats'),

  tasks: (params?: { status?: string; limit?: number; offset?: number }) =>
    api.get<AdminTasksResponse>('/admin/tasks', params),

  users: () => api.get<AdminUsersResponse>('/admin/users'),

  createUser: (data: CreateAdminUserPayload) =>
    api.post<AdminUser>('/admin/users', data),

  setRole: (userId: number, role: UserRole) =>
    api.post<{ role: UserRole; is_admin: boolean }>(`/admin/users/${userId}/role`, { role }),

  resetPassword: (userId: number, password: string) =>
    api.post<{ ok: boolean }>(`/admin/users/${userId}/reset-password`, { password }),

  deleteUser: (userId: number) =>
    api.delete<{ ok: boolean }>(`/admin/users/${userId}`),
};
