"""
Security-focused tests covering the hardening changes:
  - validate_file_path (path traversal, symlink, null-byte)
  - safe_task_base (UUID validation, prefix-confusion bypass)
  - _safe_resolve_relpath (path traversal via relpath)
  - CSRF protection on all state-changing POST routes
  - Security response headers
  - Login rate limiting
  - /debug/config no longer leaks storage_root
"""

import importlib.util
import io
import os
import pathlib
import secrets
import tempfile
import types
import unittest
from unittest.mock import patch, MagicMock

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
REPO_ROOT = pathlib.Path(__file__).resolve().parent
FRONTEND_APP_PATH = REPO_ROOT / "frontend" / "app.py"


def load_frontend_module():
    spec = importlib.util.spec_from_file_location("frontend_app_module", FRONTEND_APP_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# validate_file_path tests
# ---------------------------------------------------------------------------
class ValidateFilePathTests(unittest.TestCase):
    """Test the backend validate_file_path function in app/validation.py."""

    def setUp(self):
        # Import directly to avoid importing DB/Redis modules
        import sys
        sys.path.insert(0, str(REPO_ROOT))
        # Lazy import only validation module
        spec = importlib.util.spec_from_file_location(
            "app_validation", REPO_ROOT / "app" / "validation.py"
        )
        self.mod = importlib.util.module_from_spec(spec)
        # Provide the minimal stubs validation.py needs at import time
        import app.constants  # type: ignore[import]
        spec.loader.exec_module(self.mod)

    def _call(self, file_path: str, base_dir: str) -> str:
        return self.mod.validate_file_path(file_path, base_dir)

    def test_valid_path_returns_absolute(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "file.txt"
            p.write_text("ok")
            result = self._call("file.txt", d)
            self.assertEqual(result, str(p.resolve()))

    def test_directory_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(self.mod.ValidationError):
                self._call("../../etc/passwd", d)

    def test_null_byte_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(self.mod.ValidationError):
                self._call("file\x00.txt", d)

    def test_prefix_confusion_rejected(self):
        """'/base_extra/evil' must NOT pass the containment check for '/base'."""
        with tempfile.TemporaryDirectory() as parent:
            base = pathlib.Path(parent) / "base"
            base.mkdir()
            # Create a sibling directory whose name starts with 'base'
            evil = pathlib.Path(parent) / "base_extra"
            evil.mkdir()
            evil_file = evil / "secret.txt"
            evil_file.write_text("secret")
            # Attempt to escape via relative path
            with self.assertRaises(self.mod.ValidationError):
                self._call("../base_extra/secret.txt", str(base))

    def test_symlink_outside_base_rejected(self):
        """A symlink whose target is outside base_dir must be rejected."""
        with tempfile.TemporaryDirectory() as parent:
            base = pathlib.Path(parent) / "base"
            base.mkdir()
            outside = pathlib.Path(parent) / "secret.txt"
            outside.write_text("secret")
            link = base / "link.txt"
            link.symlink_to(outside)
            with self.assertRaises(self.mod.ValidationError):
                self._call("link.txt", str(base))


# ---------------------------------------------------------------------------
# Frontend fileshare security tests
# ---------------------------------------------------------------------------
class FileshareSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frontend = load_frontend_module()
        cls.frontend.app.config["TESTING"] = True
        cls.frontend.app.template_folder = str(REPO_ROOT / "frontend" / "templates")

    def setUp(self):
        self.client = self.frontend.app.test_client()

    def _login(self, is_admin=True):
        with self.client.session_transaction() as s:
            s["_user_id"] = "1"
            s["_fresh"] = True

    def _mock_user(self, is_admin=True):
        return types.SimpleNamespace(
            id=1, username="admin" if is_admin else "user",
            is_admin=is_admin, is_authenticated=True, is_active=True,
            role="admin" if is_admin else "user",
            is_member=is_admin,
            get_id=lambda: "1",
        )

    # ------------------------------------------------------------------
    # safe_task_base: UUID validation
    # ------------------------------------------------------------------
    def test_non_uuid_task_id_rejected_in_list_folder(self):
        self._login()
        with patch("flask_login.utils._get_user", return_value=self._mock_user()):
            resp = self.client.get("/d/../etc/")
            # Must not return 200 (file listing); expect 400 or redirect
            self.assertNotEqual(resp.status_code, 200)

    def test_path_traversal_task_id_rejected(self):
        self._login()
        with patch("flask_login.utils._get_user", return_value=self._mock_user()):
            resp = self.client.get("/d/../../etc/passwd/")
            self.assertIn(resp.status_code, (400, 404, 302))

    def test_valid_uuid_task_id_404_when_folder_missing(self):
        self._login()
        task_id = "00000000-0000-0000-0000-000000000001"
        with patch("flask_login.utils._get_user", return_value=self._mock_user()):
            # Storage root is default (/srv/storage) which won't exist in test env.
            # Flask's 404 handler redirects to index (302), so accept 302/404/400.
            resp = self.client.get(f"/d/{task_id}/")
            self.assertIn(resp.status_code, (302, 400, 404))

    # ------------------------------------------------------------------
    # raw_file: relpath containment
    # ------------------------------------------------------------------
    def test_relpath_traversal_rejected(self):
        self._login()
        task_id = "00000000-0000-0000-0000-000000000002"
        with tempfile.TemporaryDirectory() as storage:
            self.frontend.app.config["STORAGE_ROOT"] = storage
            task_dir = pathlib.Path(storage) / task_id / "files"
            task_dir.mkdir(parents=True)
            secret = pathlib.Path(storage) / "secret.txt"
            secret.write_text("top-secret")

            with patch("flask_login.utils._get_user", return_value=self._mock_user()):
                resp = self.client.get(f"/d/{task_id}/raw/../../../secret.txt")
                self.assertIn(resp.status_code, (400, 404))

    def test_prefix_confusion_relpath_rejected(self):
        """relpath that would escape via a sibling dir with a prefix name."""
        self._login()
        task_id = "00000000-0000-0000-0000-000000000003"
        with tempfile.TemporaryDirectory() as storage:
            self.frontend.app.config["STORAGE_ROOT"] = storage
            task_dir = pathlib.Path(storage) / task_id / "files"
            task_dir.mkdir(parents=True)
            # Create a sibling directory whose name starts with 'files'
            sibling = pathlib.Path(storage) / task_id / "files_extra"
            sibling.mkdir()
            (sibling / "secret.txt").write_text("secret")

            with patch("flask_login.utils._get_user", return_value=self._mock_user()):
                # Attempt to escape via ../files_extra/secret.txt
                resp = self.client.get(f"/d/{task_id}/raw/../files_extra/secret.txt")
                self.assertIn(resp.status_code, (400, 404))

    # ------------------------------------------------------------------
    # list_folder: symlink protection
    # ------------------------------------------------------------------
    def test_symlink_outside_base_not_listed(self):
        """Files reachable only via symlinks pointing outside base must not appear."""
        task_id = "00000000-0000-0000-0000-000000000004"
        with tempfile.TemporaryDirectory() as storage:
            self.frontend.app.config["STORAGE_ROOT"] = storage
            task_dir = pathlib.Path(storage) / task_id / "files"
            task_dir.mkdir(parents=True)
            # Create a file outside the task directory
            outside = pathlib.Path(storage) / "outside.txt"
            outside.write_text("should not appear")
            # Create a symlink inside the task directory pointing outside
            link = task_dir / "link.txt"
            link.symlink_to(outside)

            with patch("flask_login.utils._get_user", return_value=self._mock_user()):
                resp = self.client.get(f"/d/{task_id}/")
                self.assertEqual(resp.status_code, 200)
                # The symlinked file must not appear in the listing
                self.assertNotIn(b"link.txt", resp.data)


# ---------------------------------------------------------------------------
# CSRF protection tests
# ---------------------------------------------------------------------------
class CSRFProtectionTests(unittest.TestCase):
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

    def _get_csrf_token(self) -> str:
        """Fetch a CSRF token from the session by making a GET request."""
        with self.client.session_transaction() as s:
            if "_csrf_token" not in s:
                s["_csrf_token"] = secrets.token_hex(32)
            return s["_csrf_token"]

    def _post_without_csrf(self, url, data=None):
        return self.client.post(url, data=data or {})

    def _post_with_csrf(self, url, data=None):
        token = self._get_csrf_token()
        d = dict(data or {})
        d["_csrf_token"] = token
        return self.client.post(url, data=d)

    def test_login_post_without_csrf_rejected(self):
        resp = self._post_without_csrf("/login", {"username": "x", "password": "y"})
        self.assertEqual(resp.status_code, 403)

    def test_login_post_with_csrf_proceeds(self):
        """With a valid CSRF token the login handler proceeds (may fail auth, but not 403)."""
        def mock_w_request(method, path, **kwargs):
            if path == "/api/users/check":
                return {"has_users": True}, None
            if path == "/api/auth/verify":
                # Return invalid credentials error so login fails gracefully
                return None, ("Invalid username or password", 401)
            return None, ("unexpected", 500)

        with patch.object(self.frontend, "w_request", side_effect=mock_w_request):
            resp = self._post_with_csrf("/login", {"username": "x", "password": "y"})
            # Should not be a 403 (CSRF); login fails with 200 (re-render form)
            self.assertNotEqual(resp.status_code, 403)

    def test_task_cancel_without_csrf_rejected(self):
        self._login()
        with patch("flask_login.utils._get_user", return_value=self._mock_user()):
            task_id = "00000000-0000-0000-0000-000000000005"
            resp = self._post_without_csrf(f"/tasks/{task_id}/cancel")
            self.assertEqual(resp.status_code, 403)

    def test_task_delete_without_csrf_rejected(self):
        self._login()
        with patch("flask_login.utils._get_user", return_value=self._mock_user()):
            task_id = "00000000-0000-0000-0000-000000000006"
            resp = self._post_without_csrf(f"/tasks/{task_id}/delete")
            self.assertEqual(resp.status_code, 403)

    def test_create_user_without_csrf_rejected(self):
        self._login()
        with patch("flask_login.utils._get_user", return_value=self._mock_user()):
            resp = self._post_without_csrf("/admin/users/create",
                                           {"username": "x", "password": "y", "role": "user"})
            self.assertEqual(resp.status_code, 403)

    def test_reset_password_without_csrf_rejected(self):
        self._login()
        with patch("flask_login.utils._get_user", return_value=self._mock_user()):
            resp = self._post_without_csrf("/admin/users/1/reset-password",
                                           {"new_password": "newpass"})
            self.assertEqual(resp.status_code, 403)

    def test_delete_user_without_csrf_rejected(self):
        self._login()
        with patch("flask_login.utils._get_user", return_value=self._mock_user()):
            resp = self._post_without_csrf("/admin/users/2/delete")
            self.assertEqual(resp.status_code, 403)

    def test_set_role_without_csrf_rejected(self):
        self._login()
        with patch("flask_login.utils._get_user", return_value=self._mock_user()):
            resp = self._post_without_csrf("/admin/users/2/set-role", {"role": "user"})
            self.assertEqual(resp.status_code, 403)


# ---------------------------------------------------------------------------
# Security response headers
# ---------------------------------------------------------------------------
class SecurityHeaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frontend = load_frontend_module()
        cls.frontend.app.config["TESTING"] = True
        cls.frontend.app.template_folder = str(REPO_ROOT / "frontend" / "templates")

    def setUp(self):
        self.client = self.frontend.app.test_client()

    def _mock_user(self):
        return types.SimpleNamespace(
            id=1, username="admin", is_admin=True, is_authenticated=True,
            is_active=True, role="admin", is_member=True, get_id=lambda: "1",
        )

    def test_login_page_has_security_headers(self):
        resp = self.client.get("/login")
        self.assertEqual(resp.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(resp.headers.get("X-Frame-Options"), "SAMEORIGIN")

    def test_html_pages_not_cached(self):
        resp = self.client.get("/login")
        cc = resp.headers.get("Cache-Control", "")
        self.assertIn("no-store", cc)

    def test_debug_config_does_not_leak_storage_root(self):
        with self.client.session_transaction() as s:
            s["_user_id"] = "1"
            s["_fresh"] = True
        with patch("flask_login.utils._get_user", return_value=self._mock_user()):
            resp = self.client.get("/debug/config")
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertNotIn("storage_root", data)


# ---------------------------------------------------------------------------
# Login rate limiting
# ---------------------------------------------------------------------------
class LoginRateLimitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frontend = load_frontend_module()
        cls.frontend.app.config["TESTING"] = True
        cls.frontend.app.template_folder = str(REPO_ROOT / "frontend" / "templates")

    def setUp(self):
        self.client = self.frontend.app.test_client()
        # Reset rate-limit state between tests
        self.frontend._login_attempts.clear()

    def _get_csrf(self) -> str:
        with self.client.session_transaction() as s:
            if "_csrf_token" not in s:
                s["_csrf_token"] = secrets.token_hex(32)
            return s["_csrf_token"]

    def test_rate_limit_triggered_after_max_attempts(self):
        """After exceeding _LOGIN_MAX_ATTEMPTS requests the endpoint must 429."""
        max_att = self.frontend._LOGIN_MAX_ATTEMPTS
        token = self._get_csrf()

        def mock_w_request(method, path, **kwargs):
            if path == "/api/users/check":
                return {"has_users": True}, None
            if path == "/api/auth/verify":
                return None, ("Invalid credentials", 401)
            return None, ("unexpected", 500)

        with patch.object(self.frontend, "w_request", side_effect=mock_w_request):
            # Exhaust the rate limit
            for _ in range(max_att):
                self.client.post("/login", data={
                    "_csrf_token": token,
                    "username": "x",
                    "password": "y",
                })

            # The next request should be rate-limited
            resp = self.client.post("/login", data={
                "_csrf_token": token,
                "username": "x",
                "password": "y",
            })
            self.assertEqual(resp.status_code, 429)


if __name__ == "__main__":
    unittest.main()
