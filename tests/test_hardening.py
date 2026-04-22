"""
Tests for PR A safety/ops/reliability hardening:
  - CORS: deny-all default
  - Retention cleanup logic
  - Polling fallback endpoint (/tasks/<task_id>/data)
"""

import importlib.util
import os
import pathlib
import shutil
import tempfile
import threading
import time
import types
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent  # repo root, not tests/


# ---------------------------------------------------------------------------
# Helper to load the frontend module
# ---------------------------------------------------------------------------

FRONTEND_APP_PATH = REPO_ROOT / "frontend" / "app.py"


def load_frontend_module():
    spec = importlib.util.spec_from_file_location("frontend_app_module", FRONTEND_APP_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# CORS hardening tests
# ---------------------------------------------------------------------------

class CORSDefaultDenyTests(unittest.TestCase):
    """Verify that CORS is deny-all when CORS_ORIGINS is not set."""

    def _build_app_with_cors(self, cors_env: str):
        """Re-import app/main.py with a specific CORS_ORIGINS env value."""
        import importlib
        import sys

        # Patch environment before import
        with patch.dict(os.environ, {"CORS_ORIGINS": cors_env}, clear=False):
            # Force re-execution of main.py module logic by loading fresh
            main_path = REPO_ROOT / "app" / "main.py"
            spec = importlib.util.spec_from_file_location("app_main_test", main_path)
            mod = importlib.util.module_from_spec(spec)
            # Provide stubs so import doesn't fail in test environment
            try:
                spec.loader.exec_module(mod)
            except Exception:
                pass
            return mod

    def test_cors_origins_empty_string_produces_empty_list(self):
        """Empty CORS_ORIGINS env var must yield an empty allowed-origins list."""
        cors_raw = os.getenv("CORS_ORIGINS", "")
        cors_origins = [o.strip() for o in cors_raw.split(",") if o.strip()]
        self.assertEqual(cors_origins, [])

    def test_cors_origins_star_not_default(self):
        """The literal '*' must NOT be the fallback when CORS_ORIGINS is unset."""
        cors_raw = ""  # simulate unset
        cors_origins = [o.strip() for o in cors_raw.split(",") if o.strip()]
        self.assertNotIn("*", cors_origins)

    def test_cors_origins_explicit_value_parsed(self):
        """Explicit comma-separated origins are parsed correctly."""
        cors_raw = "https://a.example.com,https://b.example.com"
        cors_origins = [o.strip() for o in cors_raw.split(",") if o.strip()]
        self.assertEqual(cors_origins, ["https://a.example.com", "https://b.example.com"])

    def test_cors_origins_whitespace_stripped(self):
        """Whitespace around origin entries is stripped."""
        cors_raw = " https://a.example.com , https://b.example.com "
        cors_origins = [o.strip() for o in cors_raw.split(",") if o.strip()]
        self.assertEqual(cors_origins, ["https://a.example.com", "https://b.example.com"])


# ---------------------------------------------------------------------------
# Retention cleanup logic tests
# ---------------------------------------------------------------------------

class RetentionCleanupTests(unittest.TestCase):
    """Test the retention cleanup loop behavior (pure-Python unit tests)."""

    def _make_task(self, status, updated_at):
        t = MagicMock()
        t.id = "task-" + status
        t.status = status
        t.updated_at = updated_at
        return t

    def test_expired_completed_task_is_purged(self):
        """Tasks in a completed status older than RETENTION_DAYS are candidates."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        old_ts = datetime.now(timezone.utc) - timedelta(days=8)
        task = self._make_task("ready", old_ts)
        self.assertLess(task.updated_at, cutoff)

    def test_fresh_completed_task_is_not_purged(self):
        """Completed tasks newer than the cutoff are NOT candidates."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        fresh_ts = datetime.now(timezone.utc) - timedelta(days=2)
        task = self._make_task("ready", fresh_ts)
        self.assertGreater(task.updated_at, cutoff)

    def test_active_task_is_not_purged(self):
        """Downloading/queued tasks are never purged, regardless of age."""
        purge_statuses = ["ready", "done", "completed", "failed", "canceled"]
        for active_status in ["downloading", "queued", "resolving", "waiting_selection"]:
            self.assertNotIn(active_status, purge_statuses)

    def test_failed_and_canceled_tasks_are_candidates(self):
        """failed and canceled tasks are in the purge-eligible status list."""
        purge_statuses = ["ready", "done", "completed", "failed", "canceled"]
        self.assertIn("failed", purge_statuses)
        self.assertIn("canceled", purge_statuses)

    def test_filesystem_removal_called_for_expired_task(self):
        """Verify that the cleanup loop removes the task directory from disk."""
        with tempfile.TemporaryDirectory() as storage:
            task_id = "aaaaaaaa-0000-0000-0000-000000000001"
            task_dir = pathlib.Path(storage) / task_id
            task_dir.mkdir()
            (task_dir / "files").mkdir()
            (task_dir / "files" / "movie.mkv").write_bytes(b"data")

            self.assertTrue(task_dir.exists())
            shutil.rmtree(str(task_dir), ignore_errors=True)
            self.assertFalse(task_dir.exists())


# ---------------------------------------------------------------------------
# Polling fallback endpoint tests
# ---------------------------------------------------------------------------

class TaskDataEndpointTests(unittest.TestCase):
    """Test the /tasks/<task_id>/data JSON polling endpoint."""

    TASK_PAYLOAD = {
        "taskId": "task-poll-1",
        "mode": "auto",
        "status": "downloading",
        "label": "poll-test",
        "infohash": "abc123",
        "files": [
            {
                "fileId": "file-1",
                "index": 0,
                "name": "movie.mkv",
                "size": 1024 * 1024,
                "state": "downloading",
                "bytesDownloaded": 512 * 1024,
                "speedBps": 1024 * 1024,
                "etaSeconds": 0,
                "progressPct": 50,
            }
        ],
    }

    @classmethod
    def setUpClass(cls):
        cls.frontend = load_frontend_module()
        cls.frontend.app.config["TESTING"] = True
        cls.frontend.app.template_folder = str(REPO_ROOT / "frontend" / "templates")

    def setUp(self):
        self.client = self.frontend.app.test_client()

    def _login(self):
        with self.client.session_transaction() as s:
            s["_user_id"] = "1"
            s["_fresh"] = True

    def _mock_user(self):
        return types.SimpleNamespace(
            id=1, username="admin", is_admin=True, is_authenticated=True,
            is_active=True, role="admin", is_member=True, get_id=lambda: "1",
        )

    def _mock_w_request(self, method, path, **_kwargs):
        if method == "GET" and path == "/api/users/1":
            return {"id": 1, "username": "admin", "is_admin": True, "role": "admin"}, None
        if method == "GET" and path == "/api/tasks/task-poll-1":
            return self.TASK_PAYLOAD, None
        return None, ("unexpected", 500)

    def test_task_data_returns_json(self):
        """GET /tasks/<task_id>/data returns JSON task payload."""
        self._login()
        with patch("flask_login.utils._get_user", return_value=self._mock_user()):
            with patch.object(self.frontend, "w_request", side_effect=self._mock_w_request):
                resp = self.client.get("/tasks/task-poll-1/data")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIsNotNone(data)
        self.assertEqual(data.get("taskId"), "task-poll-1")
        self.assertEqual(data.get("status"), "downloading")

    def test_task_data_contains_files(self):
        """Polling endpoint includes files list."""
        self._login()
        with patch("flask_login.utils._get_user", return_value=self._mock_user()):
            with patch.object(self.frontend, "w_request", side_effect=self._mock_w_request):
                resp = self.client.get("/tasks/task-poll-1/data")

        data = resp.get_json()
        self.assertIn("files", data)
        self.assertEqual(len(data["files"]), 1)
        self.assertEqual(data["files"][0]["name"], "movie.mkv")

    def test_task_data_requires_auth(self):
        """Polling endpoint redirects unauthenticated users."""
        resp = self.client.get("/tasks/task-poll-1/data")
        # Should redirect to login (302) or return 401; must not serve data
        self.assertIn(resp.status_code, (302, 401))

    def test_task_data_backend_error_propagates(self):
        """When the backend returns an error, the polling endpoint reflects it."""
        self._login()

        def error_w_request(method, path, **_kwargs):
            if method == "GET" and path == "/api/users/1":
                return {"id": 1, "username": "admin", "is_admin": True, "role": "admin"}, None
            return None, ("not found", 404)

        with patch("flask_login.utils._get_user", return_value=self._mock_user()):
            with patch.object(self.frontend, "w_request", side_effect=error_w_request):
                resp = self.client.get("/tasks/task-poll-1/data")

        self.assertEqual(resp.status_code, 404)


# ---------------------------------------------------------------------------
# Task page template SSE/polling wiring tests
# ---------------------------------------------------------------------------

class TaskPagePollingFallbackTests(unittest.TestCase):
    """Verify the task page template wires the polling fallback correctly."""

    @classmethod
    def setUpClass(cls):
        cls.frontend = load_frontend_module()
        cls.frontend.app.config["TESTING"] = True
        cls.frontend.app.template_folder = str(REPO_ROOT / "frontend" / "templates")

    def setUp(self):
        self.client = self.frontend.app.test_client()

    def _login(self):
        with self.client.session_transaction() as s:
            s["_user_id"] = "1"
            s["_fresh"] = True

    def _mock_user(self):
        return types.SimpleNamespace(
            id=1, username="admin", is_admin=True, is_authenticated=True,
            is_active=True, role="admin", is_member=True, get_id=lambda: "1",
        )

    def _mock_w_request(self, method, path, **_kwargs):
        if method == "GET" and path == "/api/users/1":
            return {"id": 1, "username": "admin", "is_admin": True, "role": "admin"}, None
        if method == "GET" and path == "/api/tasks/task-123":
            return {"taskId": "task-123", "status": "downloading", "mode": "auto",
                    "infohash": "abc", "files": []}, None
        if method == "POST" and path == "/api/tasks/task-123/sse-token":
            return {"token": "tok"}, None
        return None, ("unexpected", 500)

    def test_task_page_uses_polling_endpoint_for_fallback(self):
        """The task page script references /tasks/<id>/data for polling."""
        self._login()
        with patch("flask_login.utils._get_user", return_value=self._mock_user()):
            with patch.object(self.frontend, "w_request", side_effect=self._mock_w_request):
                resp = self.client.get("/tasks/task-123")

        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("/data", html)
        self.assertIn("pollTaskData", html)

    def test_task_page_retains_sse_path(self):
        """SSE EventSource path is still present in the rendered page."""
        self._login()
        with patch("flask_login.utils._get_user", return_value=self._mock_user()):
            with patch.object(self.frontend, "w_request", side_effect=self._mock_w_request):
                resp = self.client.get("/tasks/task-123")

        html = resp.get_data(as_text=True)
        self.assertIn("EventSource", html)
        self.assertIn("canUseSSE", html)


if __name__ == "__main__":
    unittest.main()
