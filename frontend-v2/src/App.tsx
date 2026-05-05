import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import { AppShell } from './components/AppShell';
import { LoginPage } from './pages/LoginPage';
import { CreateTaskPage } from './pages/CreateTaskPage';
import { TaskDetailPage } from './pages/TaskDetailPage';
import { FilesPage } from './pages/FilesPage';
import type { ReactNode } from 'react';

function ProtectedRoute({ children }: { children: ReactNode }) {
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
  return <>{children}</>;
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />

      <Route
        path="/"
        element={
          <ProtectedRoute>
            <AppShell>
              <CreateTaskPage />
            </AppShell>
          </ProtectedRoute>
        }
      />

      <Route
        path="/tasks/:taskId"
        element={
          <ProtectedRoute>
            <AppShell>
              <TaskDetailPage />
            </AppShell>
          </ProtectedRoute>
        }
      />

      <Route
        path="/tasks/:taskId/files"
        element={
          <ProtectedRoute>
            <AppShell>
              <FilesPage />
            </AppShell>
          </ProtectedRoute>
        }
      />

      {/* Catch-all: redirect to home */}
      <Route path="*" element={<Navigate to="/" replace />} />
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
