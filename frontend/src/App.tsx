import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import { AppShell } from './components/AppShell';
import { LoginPage } from './pages/LoginPage';
import { CreateTaskPage } from './pages/CreateTaskPage';
import { TaskDetailPage } from './pages/TaskDetailPage';
import { FilesPage } from './pages/FilesPage';
import { PlayerPage } from './pages/PlayerPage';
import { AdminDashboardPage } from './pages/AdminDashboardPage';
import { AdminUsersPage } from './pages/AdminUsersPage';
import { AccessDeniedPage } from './pages/AccessDeniedPage';
import { BlueCogPage } from './pages/BlueCogPage';
import { DownloadsPage } from './pages/DownloadsPage';
import type { ReactNode } from 'react';
import type { UserRole } from './types';

function ProtectedRoute({ children, roles }: { children: ReactNode; roles?: UserRole[] }) {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <div className="loading-screen">
        <span className="spinner spinner-lg" />
        Loading…
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;
  if (roles && !roles.includes(user.role)) {
    return <Navigate to="/access-denied" replace />;
  }
  return <>{children}</>;
}

function RoleAwareRedirect() {
  const { user } = useAuth();
  if (!user) return <Navigate to="/login" replace />;
  return <Navigate to={user.role === 'user' ? '/downloads' : '/'} replace />;
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />

      <Route
        path="/access-denied"
        element={
          <ProtectedRoute>
            <AppShell>
              <AccessDeniedPage />
            </AppShell>
          </ProtectedRoute>
        }
      />

      <Route
        path="/"
        element={
          <ProtectedRoute roles={['admin', 'member']}>
            <AppShell>
              <CreateTaskPage />
            </AppShell>
          </ProtectedRoute>
        }
      />

      <Route
        path="/tasks/:taskId"
        element={
          <ProtectedRoute roles={['admin', 'member']}>
            <AppShell>
              <TaskDetailPage />
            </AppShell>
          </ProtectedRoute>
        }
      />

      <Route
        path="/tasks/:taskId/files"
        element={
          <ProtectedRoute roles={['admin', 'member', 'user']}>
            <AppShell>
              <FilesPage />
            </AppShell>
          </ProtectedRoute>
        }
      />

      <Route
        path="/tasks/:taskId/player"
        element={
          <ProtectedRoute roles={['admin', 'member', 'user']}>
            <AppShell>
              <PlayerPage />
            </AppShell>
          </ProtectedRoute>
        }
      />

      <Route
        path="/bluecog"
        element={
          <ProtectedRoute roles={['admin', 'member']}>
            <AppShell>
              <BlueCogPage />
            </AppShell>
          </ProtectedRoute>
        }
      />

      <Route
        path="/admin"
        element={
          <ProtectedRoute roles={['admin']}>
            <AppShell>
              <AdminDashboardPage />
            </AppShell>
          </ProtectedRoute>
        }
      />

      <Route
        path="/admin/users"
        element={
          <ProtectedRoute roles={['admin']}>
            <AppShell>
              <AdminUsersPage />
            </AppShell>
          </ProtectedRoute>
        }
      />

      <Route
        path="/downloads"
        element={
          <ProtectedRoute roles={['admin', 'member', 'user']}>
            <AppShell>
              <DownloadsPage />
            </AppShell>
          </ProtectedRoute>
        }
      />

      <Route path="*" element={<RoleAwareRedirect />} />
    </Routes>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </BrowserRouter>
  );
}
