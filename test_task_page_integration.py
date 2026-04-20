import importlib.util
import pathlib
import types
import unittest
from unittest.mock import patch


REPO_ROOT = pathlib.Path(__file__).resolve().parent
FRONTEND_APP_PATH = REPO_ROOT / "frontend" / "app.py"


def load_frontend_module():
    spec = importlib.util.spec_from_file_location("frontend_app_module", FRONTEND_APP_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class TaskPageIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frontend = load_frontend_module()
        cls.frontend.app.config["TESTING"] = True
        cls.frontend.app.template_folder = str(REPO_ROOT / "frontend" / "templates")

    def setUp(self):
        self.client = self.frontend.app.test_client()
        # mock_user now includes role for the new 3-tier system
        self.mock_user = types.SimpleNamespace(
            id=1, username="admin", is_admin=True, role="admin",
        )
        self.task_payload = {
            "taskId": "task-123",
            "mode": "auto",
            "status": "downloading",
            "label": "integration-test",
            "infohash": "abc123",
            "files": [
                {
                    "fileId": "file-1",
                    "index": 0,
                    "name": "movie.mkv",
                    "size": 1024 * 1024 * 1024,
                    "state": "downloading",
                    "bytesDownloaded": 256 * 1024 * 1024,
                    "speedBps": 8 * 1024 * 1024,
                    "etaSeconds": 96,
                    "progressPct": 25,
                }
            ],
        }

    def _login_admin(self):
        with self.client.session_transaction() as session:
            session["_user_id"] = "1"
            session["_fresh"] = True

    def _mock_worker_request(self, method, path, **_kwargs):
        if method == "GET" and path == "/api/users/1":
            # Return admin user data so load_user() can authenticate
            return {"id": 1, "username": "admin", "is_admin": True, "role": "admin"}, None
        if method == "GET" and path == "/api/tasks/task-123":
            return self.task_payload, None
        if method == "POST" and path == "/api/tasks/task-123/sse-token":
            return {"token": "sse-token-1"}, None
        return None, ("unexpected call", 500)

    def test_task_page_renders_refresh_controls_and_progress_ui(self):
        self._login_admin()
        with patch.object(self.frontend, "w_request", side_effect=self._mock_worker_request):
            response = self.client.get("/tasks/task-123")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('id="autoRefreshEnabled"', html)
        self.assertIn('id="autoRefreshInterval"', html)
        self.assertIn('class="progress-bar"', html)
        self.assertIn("metric-rate", html)
        self.assertIn("metric-eta", html)

    def test_task_page_script_wires_sse_fallback_and_final_state_stop(self):
        self._login_admin()
        with patch.object(self.frontend, "w_request", side_effect=self._mock_worker_request):
            response = self.client.get("/tasks/task-123")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("merged.speedBps", html)
        self.assertIn("merged.etaSeconds", html)
        self.assertIn("fallbackPollingActive = true;", html)
        self.assertIn("restartAutoRefreshTimer();", html)
        self.assertIn("Task completed (auto refresh stopped)", html)

    def test_task_page_does_not_expose_local_path(self):
        """file-path div and localPath JS should not appear in the rendered task page."""
        self._login_admin()
        with patch.object(self.frontend, "w_request", side_effect=self._mock_worker_request):
            response = self.client.get("/tasks/task-123")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertNotIn('class="file-path"', html)
        self.assertNotIn("localPath", html)


class RoleAccessControlTests(unittest.TestCase):
    """Verify that each role can access only its permitted routes."""

    @classmethod
    def setUpClass(cls):
        cls.frontend = load_frontend_module()
        cls.frontend.app.config["TESTING"] = True
        cls.frontend.app.template_folder = str(REPO_ROOT / "frontend" / "templates")

    def _make_client_for_role(self, role: str):
        """Return (client, mock_worker_fn) wired up for a user with the given role."""
        client = self.frontend.app.test_client()
        uid = {"admin": 1, "member": 2, "user": 3}[role]
        user_data = {
            "id": uid,
            "username": role,
            "is_admin": role == "admin",
            "role": role,
        }

        def mock_w_request(method, path, **_kw):
            if method == "GET" and path == f"/api/users/{uid}":
                return user_data, None
            # admin page data
            if method == "GET" and path == "/api/tasks":
                return {"tasks": []}, None
            if method == "GET" and path == "/api/stats":
                return {}, None
            if method == "GET" and path == "/api/users":
                return {"users": []}, None
            return None, ("unexpected call", 500)

        with client.session_transaction() as sess:
            sess["_user_id"] = str(uid)
            sess["_fresh"] = True

        return client, mock_w_request

    def test_admin_can_access_home(self):
        client, mock_fn = self._make_client_for_role("admin")
        with patch.object(self.frontend, "w_request", side_effect=mock_fn):
            resp = client.get("/")
        self.assertEqual(resp.status_code, 200)

    def test_admin_can_access_admin_page(self):
        client, mock_fn = self._make_client_for_role("admin")
        with patch.object(self.frontend, "w_request", side_effect=mock_fn):
            resp = client.get("/admin")
        self.assertEqual(resp.status_code, 200)

    def test_member_can_access_home(self):
        client, mock_fn = self._make_client_for_role("member")
        with patch.object(self.frontend, "w_request", side_effect=mock_fn):
            resp = client.get("/")
        self.assertEqual(resp.status_code, 200)

    def test_member_cannot_access_admin_page(self):
        client, mock_fn = self._make_client_for_role("member")
        with patch.object(self.frontend, "w_request", side_effect=mock_fn):
            resp = client.get("/admin")
        self.assertEqual(resp.status_code, 403)

    def test_user_cannot_access_home(self):
        client, mock_fn = self._make_client_for_role("user")
        with patch.object(self.frontend, "w_request", side_effect=mock_fn):
            resp = client.get("/")
        self.assertEqual(resp.status_code, 403)

    def test_user_cannot_access_admin_page(self):
        client, mock_fn = self._make_client_for_role("user")
        with patch.object(self.frontend, "w_request", side_effect=mock_fn):
            resp = client.get("/admin")
        self.assertEqual(resp.status_code, 403)


if __name__ == "__main__":
    unittest.main()
