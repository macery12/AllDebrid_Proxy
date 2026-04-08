import importlib.util
import pathlib
import types
import unittest
from unittest.mock import patch


REPO_ROOT = pathlib.Path("/home/runner/work/AllDebrid_Proxy/AllDebrid_Proxy")
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
        self.mock_user = types.SimpleNamespace(id=1, username="admin", is_admin=True)
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
        if method == "GET" and path == "/api/tasks/task-123":
            return self.task_payload, None
        if method == "POST" and path == "/api/tasks/task-123/sse-token":
            return {"token": "sse-token-1"}, None
        return None, ("unexpected call", 500)

    def test_task_page_renders_refresh_controls_and_progress_ui(self):
        self._login_admin()
        with patch.object(self.frontend.user_manager, "get_user_by_id", return_value=self.mock_user), \
             patch.object(self.frontend, "w_request", side_effect=self._mock_worker_request):
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
        with patch.object(self.frontend.user_manager, "get_user_by_id", return_value=self.mock_user), \
             patch.object(self.frontend, "w_request", side_effect=self._mock_worker_request):
            response = self.client.get("/tasks/task-123")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("merged.speedBps", html)
        self.assertIn("merged.etaSeconds", html)
        self.assertIn("fallbackPollingActive = true;", html)
        self.assertIn("restartAutoRefreshTimer();", html)
        self.assertIn("Task completed (auto refresh stopped)", html)


if __name__ == "__main__":
    unittest.main()
