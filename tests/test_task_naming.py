"""
Tests for app/task_naming.py

Covers:
  - Name generation from different metadata shapes
  - Safe fallback naming when metadata is missing
  - Local filesystem paths are never returned
  - Normalisation (collapsing separators, unsafe chars removed, max length)
  - Clickable recent task links route to the correct task detail page (integration)
"""

import importlib.util
import pathlib
import re
import types
import unittest
from unittest.mock import patch

REPO_ROOT = pathlib.Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# Load modules under test without triggering DB/Redis imports
# ---------------------------------------------------------------------------

def _load_task_naming():
    spec = importlib.util.spec_from_file_location(
        "app_task_naming", REPO_ROOT / "app" / "task_naming.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_frontend():
    spec = importlib.util.spec_from_file_location(
        "frontend_app_module", REPO_ROOT / "frontend" / "app.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Unit tests — generate_task_name
# ---------------------------------------------------------------------------

class TaskNamingTests(unittest.TestCase):
    """Unit tests for generate_task_name."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_task_naming()

    def _gen(self, *args, **kwargs):
        """Thin wrapper so tests can call self._gen(...) without descriptor binding."""
        return self.mod.generate_task_name(*args, **kwargs)

    # ── Priority 1: explicit label ──────────────────────────────────────────

    def test_explicit_label_wins_over_everything(self):
        name = self._gen(
            "magnet:?xt=urn:btih:abc123&dn=Ignored+Name",
            label="My Custom Label",
            torrent_name="Should Not Appear",
            task_id="00000000-0000-0000-0000-000000000001",
        )
        self.assertIn("My", name)
        self.assertIn("Custom", name)
        self.assertNotIn("Ignored", name)

    # ── Priority 2: torrent_name ────────────────────────────────────────────

    def test_torrent_name_used_when_no_label(self):
        name = self._gen(
            "magnet:?xt=urn:btih:abc123",
            torrent_name="Show.Name.S01E02.1080p",
            task_id="00000000-0000-0000-0000-000000000002",
        )
        self.assertIn("Show", name)
        self.assertIn("S01E02", name)
        self.assertIn("1080p", name)

    # ── Priority 3: magnet dn= ──────────────────────────────────────────────

    def test_magnet_dn_extracted(self):
        magnet = "magnet:?xt=urn:btih:deadbeef&dn=Movie+Title+2024+2160p"
        name = self._gen(magnet, task_id="00000000-0000-0000-0000-000000000003")
        self.assertIn("Movie", name)
        self.assertIn("2024", name)
        self.assertIn("2160p", name)

    def test_magnet_dn_url_encoded(self):
        magnet = "magnet:?xt=urn:btih:deadbeef&dn=Artist%20-%20Album%20%282023%29"
        name = self._gen(magnet, task_id="00000000-0000-0000-0000-000000000004")
        self.assertIn("Artist", name)
        self.assertIn("Album", name)
        self.assertIn("2023", name)

    # ── Priority 3 (link): URL filename ────────────────────────────────────

    def test_url_filename_extracted_for_link(self):
        url = "https://example.com/files/Documentary.2023.720p.mkv"
        name = self._gen(url, source_type="link", task_id="00000000-0000-0000-0000-000000000005")
        self.assertIn("Documentary", name)
        self.assertIn("2023", name)
        self.assertIn("720p", name)

    # ── Priority 4: filenames ───────────────────────────────────────────────

    def test_best_filename_picked(self):
        name = self._gen(
            "magnet:?xt=urn:btih:abc123",
            filenames=["subs/en.srt", "Show.S02E03.HDTV.mkv", "cover.jpg"],
            task_id="00000000-0000-0000-0000-000000000006",
        )
        # Longest meaningful name should win
        self.assertIn("Show", name)
        self.assertIn("S02E03", name)

    # ── Priority 5: task-ID fallback ───────────────────────────────────────

    def test_fallback_to_task_id_when_no_metadata(self):
        name = self._gen(
            "magnet:?xt=urn:btih:abc123",
            task_id="a3f2b1c4-0000-0000-0000-000000000000",
        )
        self.assertRegex(name, r"Task-[a-f0-9]{8}")

    def test_fallback_unnamed_when_no_task_id(self):
        name = self._gen("magnet:?xt=urn:btih:abc123")
        self.assertEqual(name, "Unnamed-Task")

    # ── Normalisation ───────────────────────────────────────────────────────

    def test_unsafe_chars_removed(self):
        name = self._gen(
            "magnet:?xt=urn:btih:abc123",
            label="Bad<>&\"'`chars;in|label",
        )
        for ch in "<>&\"'`|;":
            self.assertNotIn(ch, name, f"Unsafe char {ch!r} not removed")

    def test_repeated_separators_collapsed(self):
        name = self._gen(
            "magnet:?xt=urn:btih:abc123",
            label="A...B---C   D",
        )
        # No run of 2+ separator chars should remain
        self.assertNotRegex(name, r"[\s._\-]{2,}")

    def test_max_length_enforced(self):
        long_label = "A" * 200
        name = self._gen("magnet:?xt=urn:btih:abc123", label=long_label)
        self.assertLessEqual(len(name), self.mod.MAX_TASK_NAME_LENGTH)

    # ── Path safety ─────────────────────────────────────────────────────────

    def test_unix_absolute_path_not_returned_as_is(self):
        """A Unix absolute path label must not leak the directory structure."""
        name = self._gen(
            "magnet:?xt=urn:btih:abc123",
            label="/srv/storage/some-task-id/files/movie.mkv",
        )
        self.assertNotIn("/srv", name)
        self.assertNotIn("storage", name)
        # The basename component should still be present
        self.assertIn("movie", name)

    def test_windows_absolute_path_not_returned_as_is(self):
        """A Windows absolute path label must not leak the directory structure."""
        name = self._gen(
            "magnet:?xt=urn:btih:abc123",
            label=r"C:\Users\admin\Downloads\movie.mkv",
        )
        self.assertNotIn("C:", name)
        self.assertNotIn("Users", name)
        # The basename component should still be present
        self.assertIn("movie", name)

    def test_path_in_filename_not_leaked(self):
        """Filenames with directory components must expose only the basename."""
        name = self._gen(
            "magnet:?xt=urn:btih:abc123",
            filenames=["/srv/storage/abc/files/Season 1/Episode.mkv"],
        )
        self.assertNotIn("/srv", name)
        self.assertNotIn("storage", name)
        # The episode filename should be present
        self.assertIn("Episode", name)

    def test_torrent_name_with_path_separator(self):
        """Torrent names that include slashes must be sanitised."""
        name = self._gen(
            "magnet:?xt=urn:btih:abc123",
            torrent_name="Top/Dir/Show.S01E01.mkv",
        )
        self.assertNotIn("/", name)

    def test_empty_label_falls_through_to_magnet_dn(self):
        """An empty label must not be used; fall through to the next candidate."""
        magnet = "magnet:?xt=urn:btih:abc123&dn=RealName"
        name = self._gen(magnet, label="   ", task_id="00000000-0000-0000-0000-ffffffffffff")
        self.assertIn("RealName", name)


# ---------------------------------------------------------------------------
# Integration test — recent tasks navigation via /tasks/recent
# ---------------------------------------------------------------------------

class RecentTasksNavigationTests(unittest.TestCase):
    """Verify the /tasks/recent endpoint and clickable-link behaviour."""

    @classmethod
    def setUpClass(cls):
        cls.frontend = _load_frontend()
        cls.frontend.app.config["TESTING"] = True
        cls.frontend.app.template_folder = str(REPO_ROOT / "frontend" / "templates")

    def _make_client(self, role: str):
        client = self.frontend.app.test_client()
        uid = {"admin": 1, "member": 2}[role]
        user_data = {"id": uid, "username": role, "is_admin": role == "admin", "role": role}
        tasks_payload = {
            "tasks": [
                {
                    "taskId": "task-abc123",
                    "id": "task-abc123",
                    "label": "Test Movie 2024",
                    "status": "completed",
                    "mode": "auto",
                    "source": "magnet:?xt=urn:btih:abc123",
                    "infohash": "abc123",
                    "created_at": "2024-01-01T00:00:00",
                    "updated_at": "2024-01-01T00:00:00",
                }
            ],
            "total": 1,
        }

        def mock_w_request(method, path, **kw):
            if method == "GET" and path == f"/api/users/{uid}":
                return user_data, None
            if method == "GET" and path == "/api/tasks":
                return tasks_payload, None
            return None, ("unexpected call", 500)

        with client.session_transaction() as sess:
            sess["_user_id"] = str(uid)
            sess["_fresh"] = True

        return client, mock_w_request

    def test_admin_can_access_recent_tasks_endpoint(self):
        client, mock_fn = self._make_client("admin")
        with patch.object(self.frontend, "w_request", side_effect=mock_fn):
            resp = client.get("/tasks/recent?limit=6")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("tasks", data)
        self.assertEqual(len(data["tasks"]), 1)

    def test_member_can_access_recent_tasks_endpoint(self):
        client, mock_fn = self._make_client("member")
        with patch.object(self.frontend, "w_request", side_effect=mock_fn):
            resp = client.get("/tasks/recent?limit=6")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("tasks", data)

    def test_recent_tasks_returns_task_id_field(self):
        """Both 'taskId' and 'id' fields are present so JS links work."""
        client, mock_fn = self._make_client("admin")
        with patch.object(self.frontend, "w_request", side_effect=mock_fn):
            resp = client.get("/tasks/recent?limit=6")
        task = resp.get_json()["tasks"][0]
        self.assertIn("taskId", task)
        self.assertIn("id", task)
        self.assertEqual(task["taskId"], task["id"])

    def test_recent_tasks_label_populated(self):
        """The label field must be present so it renders in the recent-tasks list."""
        client, mock_fn = self._make_client("admin")
        with patch.object(self.frontend, "w_request", side_effect=mock_fn):
            resp = client.get("/tasks/recent?limit=6")
        task = resp.get_json()["tasks"][0]
        self.assertEqual(task["label"], "Test Movie 2024")

    def test_recent_tasks_limit_clamped(self):
        """A huge limit must not be forwarded to the backend as-is."""
        client, mock_fn = self._make_client("admin")
        captured_params = {}

        def capturing_mock(method, path, **kw):
            if method == "GET" and path == "/api/tasks":
                captured_params.update(kw.get("params", {}))
                return {"tasks": [], "total": 0}, None
            uid = 1
            if method == "GET" and path == f"/api/users/{uid}":
                return {"id": uid, "username": "admin", "is_admin": True, "role": "admin"}, None
            return None, ("unexpected", 500)

        with patch.object(self.frontend, "w_request", side_effect=capturing_mock):
            client.get("/tasks/recent?limit=9999")
        # The clamped limit must be at most 50
        self.assertLessEqual(captured_params.get("limit", 0), 50)

    def test_member_recent_tasks_filters_by_user_id(self):
        """Members must receive only their own tasks (user_id param forwarded)."""
        client, mock_fn = self._make_client("member")
        captured_params = {}

        def capturing_mock(method, path, **kw):
            if method == "GET" and path == "/api/users/2":
                return {"id": 2, "username": "member", "is_admin": False, "role": "member"}, None
            if method == "GET" and path == "/api/tasks":
                captured_params.update(kw.get("params", {}))
                return {"tasks": [], "total": 0}, None
            return None, ("unexpected", 500)

        with patch.object(self.frontend, "w_request", side_effect=capturing_mock):
            client.get("/tasks/recent?limit=6")
        self.assertEqual(captured_params.get("user_id"), 2)

    def test_admin_recent_tasks_does_not_filter_by_user_id(self):
        """Admins should see all tasks, so no user_id filter is forwarded."""
        client, mock_fn = self._make_client("admin")
        captured_params = {}

        def capturing_mock(method, path, **kw):
            if method == "GET" and path == "/api/users/1":
                return {"id": 1, "username": "admin", "is_admin": True, "role": "admin"}, None
            if method == "GET" and path == "/api/tasks":
                captured_params.update(kw.get("params", {}))
                return {"tasks": [], "total": 0}, None
            return None, ("unexpected", 500)

        with patch.object(self.frontend, "w_request", side_effect=capturing_mock):
            client.get("/tasks/recent?limit=6")
        self.assertNotIn("user_id", captured_params)

    def test_index_page_uses_recent_tasks_endpoint_url(self):
        """The index page JS must reference /tasks/recent, not /admin/tasks."""
        client = self.frontend.app.test_client()
        uid = 1
        user_data = {"id": uid, "username": "admin", "is_admin": True, "role": "admin"}

        def mock_fn(method, path, **kw):
            if method == "GET" and path == f"/api/users/{uid}":
                return user_data, None
            return None, ("unexpected", 500)

        with client.session_transaction() as sess:
            sess["_user_id"] = str(uid)
            sess["_fresh"] = True

        with patch.object(self.frontend, "w_request", side_effect=mock_fn):
            resp = client.get("/")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("/tasks/recent", html)
        # Should NOT use the admin-only endpoint for the recent tasks widget
        self.assertNotIn("fetch('/admin/tasks", html)

    def test_index_page_js_uses_taskid_not_id(self):
        """The recent-tasks JS must use t.taskId (not t.id alone) for the link href."""
        client = self.frontend.app.test_client()
        uid = 1
        user_data = {"id": uid, "username": "admin", "is_admin": True, "role": "admin"}

        def mock_fn(method, path, **kw):
            if method == "GET" and path == f"/api/users/{uid}":
                return user_data, None
            return None, ("unexpected", 500)

        with client.session_transaction() as sess:
            sess["_user_id"] = str(uid)
            sess["_fresh"] = True

        with patch.object(self.frontend, "w_request", side_effect=mock_fn):
            resp = client.get("/")
        html = resp.get_data(as_text=True)
        self.assertIn("t.taskId", html)


if __name__ == "__main__":
    unittest.main()
