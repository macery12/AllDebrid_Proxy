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

  // Tasks live at /api/tasks (admin sees all tasks via require_member which includes admin)
  tasks: (params?: { status?: string; limit?: number; offset?: number }) =>
    api.get<AdminTasksResponse>('/tasks', params),

  // User management lives at /api/users (already admin-only via require_admin)
  users: () => api.get<AdminUsersResponse>('/users'),

  createUser: (data: CreateAdminUserPayload) =>
    api.post<AdminUser>('/users', data),

  setRole: (userId: number, role: UserRole) =>
    api.post<{ role: UserRole; is_admin: boolean }>(`/users/${userId}/role`, { role }),

  resetPassword: (userId: number, password: string) =>
    api.post<{ ok: boolean }>(`/users/${userId}/reset-password`, { password }),

  deleteUser: (userId: number) =>
    api.delete<{ ok: boolean }>(`/users/${userId}`),
};
