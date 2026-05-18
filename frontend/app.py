from flask import Flask, request, jsonify, send_file, abort, make_response, Response, stream_with_context
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from pathlib import Path
from dotenv import load_dotenv
import os, io, tarfile, logging, requests, mimetypes, hashlib, re, threading, queue

# ------------------------------------------------------------------------------
# Bootstrapping / App setup
# ------------------------------------------------------------------------------
load_dotenv()

# Import shared utilities (no database connections)
from app.constants import Limits
from app.utils import torrent_to_magnet
from app.validation import validate_torrent_file_data

# Constants
MAX_SOURCE_LENGTH = 10000  # Maximum length for magnet/URL source
MAX_LABEL_LENGTH = 500     # Maximum length for task label

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')
log = logging.getLogger("ad-frontend-v1")

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "dev-secret")

# Config via env
app.config["WORKER_BASE_URL"] = os.environ.get("WORKER_BASE_URL", "http://localhost:8080").rstrip("/")
app.config["WORKER_KEY"] = os.environ.get("WORKER_API_KEY", "")
app.config["STORAGE_ROOT"] = os.environ.get("STORAGE_ROOT", "/srv/storage")
app.config["USE_X_ACCEL"] = os.environ.get("USE_X_ACCEL", "0") == "1"
app.config["NGINX_ACCEL_PREFIX"] = os.environ.get("NGINX_ACCEL_PREFIX", "/protected")

# Minimal startup validation
if not app.config["WORKER_KEY"]:
    log.warning("WORKER_API_KEY not set - backend API calls will fail")
elif app.config["WORKER_KEY"] == "change-me":
    log.warning("WORKER_API_KEY is still set to default 'change-me' - please change it")

if app.secret_key == "dev-secret":
    log.warning("FLASK_SECRET is not set or is still 'dev-secret'. Sessions are insecure in production.")

login_manager = LoginManager()
login_manager.init_app(app)

# UUID pattern (reused from backend constants without importing DB-connected modules)
_UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE)

# ------------------------------------------------------------------------------
# Security headers
# ------------------------------------------------------------------------------
@app.after_request
def set_security_headers(response):
    """Add defensive HTTP headers to every response."""
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    # Rate of change is low; avoid caching private pages at all.
    if response.content_type and "text/html" in response.content_type:
        response.headers.setdefault("Cache-Control", "no-store")
    return response

# ------------------------------------------------------------------------------
# Login rate limiter (in-process, per IP)
# ------------------------------------------------------------------------------
import time as _time
_login_attempts: dict = {}   # {ip: [timestamp, ...]}
_LOGIN_WINDOW = 300          # 5-minute sliding window
_LOGIN_MAX_ATTEMPTS = 20     # max failed+successful POSTs per window per IP

def _login_rate_check():
    """Raise 429 if the client IP has exceeded the login rate limit."""
    ip = request.remote_addr or "unknown"
    now = _time.time()
    window_start = now - _LOGIN_WINDOW
    attempts = [t for t in _login_attempts.get(ip, []) if t > window_start]
    if len(attempts) >= _LOGIN_MAX_ATTEMPTS:
        log.warning("Login rate limit exceeded for IP %s", ip)
        abort(429, "Too many login attempts. Please wait a few minutes and try again.")
    attempts.append(now)
    _login_attempts[ip] = attempts

# ------------------------------------------------------------------------------
# Auth / Users (Database-backed)
# ------------------------------------------------------------------------------
class User(UserMixin):
    def __init__(self, user_id: int, username: str, is_admin: bool = False, role: str = "user"):
        self.id = user_id
        self.username = username
        self.is_admin = is_admin
        self.role = role

    @property
    def is_active(self):
        return True

    @property
    def is_member(self) -> bool:
        """True for admin and member roles — can access home/tasks pages."""
        return self.role in ("admin", "member")

    def get_id(self):
        """Return user ID as string for Flask-Login"""
        return str(self.id)

@login_manager.user_loader
def load_user(user_id):
    try:
        numeric_id = int(user_id)
        data, err = w_request("GET", f"/api/users/{numeric_id}")
        if not err and data:
            return User(data["id"], data["username"], data["is_admin"], data.get("role", "user"))
    except (ValueError, TypeError):
        pass
    return None

@login_manager.unauthorized_handler
def _unauth():
    return jsonify({"error": "Authentication required"}), 401

def admin_required(f):
    """Decorator to require admin access"""
    from functools import wraps
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_admin:
            return jsonify({"error": "Admin access required"}), 403
        return f(*args, **kwargs)
    return decorated_function

def member_required(f):
    """Decorator to require member or admin access."""
    from functools import wraps
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_member:
            return jsonify({"error": "Access denied"}), 403
        return f(*args, **kwargs)
    return decorated_function

# ------------------------------------------------------------------------------
# Worker helpers
# ------------------------------------------------------------------------------
def w_headers():
    h = {}
    if app.config["WORKER_KEY"]:
        h["X-Worker-Key"] = app.config["WORKER_KEY"]
    else:
        log.warning("WORKER_KEY not configured - authentication will fail")
    return h

def w_url(path: str) -> str:
    if not path.startswith("/"):
        path = "/" + path
    return app.config["WORKER_BASE_URL"] + path

def w_request(method: str, path: str, *, params=None, json_body=None):
    url = w_url(path)
    headers = w_headers()
    
    log.info(f"→ WORKER {method} {url}")
    try:
        r = requests.request(method, url, headers=headers, params=params, json=json_body, timeout=30)
    except Exception as e:
        log.error(f"WORKER request failed: {e}")
        return None, (str(e), 502)
    log.info(f"← WORKER {r.status_code} {url}")
    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text}
    if not r.ok:
        msg = data.get("message") or data.get("reason") or data.get("detail") or r.text
        return None, (msg, r.status_code)
    return data, None

# ------------------------------------------------------------------------------
# Download helpers (offload & caching)
# ------------------------------------------------------------------------------
def _etag_for_stat(st) -> str:
    mtime_ns = getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))
    payload = f"{st.st_ino}:{st.st_size}:{mtime_ns}".encode()
    return '"' + hashlib.md5(payload).hexdigest() + '"'

def _http_time(ts: float) -> str:
    import email.utils
    return email.utils.formatdate(ts, usegmt=True)

def _guess_mime(name: str) -> str:
    m, _ = mimetypes.guess_type(name)
    return m or "application/octet-stream"

def _accel_path(task_id: str, relpath: str) -> str:
    relpath = relpath.lstrip("/").replace("\\", "/")
    return f"{app.config['NGINX_ACCEL_PREFIX']}/{task_id}/files/{relpath}"

def _is_video(filename: str) -> bool:
    """Check if a file is a video based on extension"""
    video_exts = {'.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v', '.mpg', '.mpeg', '.3gp', '.ogv'}
    ext = Path(filename).suffix.lower()
    return ext in video_exts

def _is_still_downloading(filepath: Path) -> bool:
    """Check if a file is still being downloaded by aria2c"""
    aria2_control = Path(str(filepath) + ".aria2")
    return aria2_control.exists()

def _should_include_file(filepath: Path) -> bool:
    """Check if a file should be included in listings (exclude .aria2 control files)"""
    return not filepath.name.endswith(".aria2")

# ------------------------------------------------------------------------------
# Debug
# (V1 form-based pages/routes removed — all UI is now served by the V2 React SPA)
# ------------------------------------------------------------------------------
@app.get("/debug/config")
@admin_required
def debug_config():
    return jsonify({
        "worker_base_url": app.config["WORKER_BASE_URL"],
        "worker_key_present": bool(app.config["WORKER_KEY"]),
    })

# ------------------------------------------------------------------------------
# Fileshare
# ------------------------------------------------------------------------------
def safe_task_base(task_id: str) -> Path:
    # Validate task_id is a well-formed UUID to prevent path-injection.
    if not _UUID_RE.match(task_id):
        abort(400, "Invalid task ID")
    root = Path(app.config["STORAGE_ROOT"]).resolve()
    base = (root / task_id / "files").resolve()
    # Use is_relative_to (Python 3.9+) to avoid the startswith prefix-confusion
    # bug where /srv/storage2/... would pass a plain startswith(/srv/storage) check.
    if not base.is_relative_to(root):
        abort(400, "Invalid task ID")
    if not base.exists():
        abort(404, "Task folder not found")
    return base

@app.get("/d/<task_id>/links.txt")
@login_required
def links_txt(task_id):
    base = safe_task_base(task_id)
    out = io.StringIO()
    for p in sorted(base.rglob("*")):
        # Skip symlinks that escape the base directory
        if p.is_symlink() and not p.resolve().is_relative_to(base):
            continue
        if p.is_file() and _should_include_file(p):
            rel = p.relative_to(base).as_posix()
            base_url = request.host_url.rstrip("/")
            out.write(f"{base_url}/d/{task_id}/raw/{rel}\n")
    return out.getvalue(), 200, {"Content-Type": "text/plain; charset=utf-8"}

@app.get("/d/<task_id>.tar.gz")
@login_required
def tar_all(task_id):
    base = safe_task_base(task_id)

    def safe_tar_filter(tarinfo):
        """Exclude .aria2 control files and any symlinks (which could point
        outside the base directory and leak filesystem paths/content)."""
        if not _should_include_file(Path(tarinfo.name)):
            return None
        # Drop symlinks entirely — a symlink's target is not verified to be
        # within the task directory and could leak arbitrary filesystem data.
        if tarinfo.issym() or tarinfo.islnk():
            return None
        return tarinfo

    # Build an ETag from the most-recent mtime of any file in the task dir.
    try:
        mtimes = [f.stat().st_mtime for f in base.rglob("*") if f.is_file()]
        latest_mtime = max(mtimes) if mtimes else base.stat().st_mtime
        etag = f'"{task_id}-{int(latest_mtime)}"'
    except Exception:
        etag = f'"{task_id}"'

    # Honour conditional GET (If-None-Match).
    inm = request.headers.get("If-None-Match", "").strip()
    if inm and inm == etag:
        return Response("", 304, headers={"ETag": etag})

    # Stream the archive using a background thread + queue so the entire
    # compressed output is never buffered in memory at once.
    chunk_queue: queue.Queue = queue.Queue(maxsize=32)

    class _QueueWriter:
        def write(self, data: bytes) -> int:
            chunk_queue.put(bytes(data))
            return len(data)
        def close(self) -> None:
            chunk_queue.put(None)  # sentinel

    writer = _QueueWriter()

    def _pack() -> None:
        try:
            with tarfile.open(fileobj=writer, mode="w|gz") as tar:  # type: ignore[arg-type]  # _QueueWriter satisfies write() protocol
                tar.add(base, arcname=f"{task_id}/files", filter=safe_tar_filter)
        finally:
            writer.close()

    pack_thread = threading.Thread(target=_pack, daemon=True)
    pack_thread.start()

    def generate():
        while True:
            chunk = chunk_queue.get()
            if chunk is None:
                break
            yield chunk

    headers = {
        "Content-Disposition": f'attachment; filename="{task_id}.tar.gz"',
        "ETag": etag,
        "Cache-Control": "private, no-transform",
    }
    return Response(
        stream_with_context(generate()),
        mimetype="application/gzip",
        headers=headers,
    )

def _safe_resolve_relpath(base: Path, relpath: str) -> Path:
    """Resolve *relpath* under *base* and verify it stays within *base*.

    Uses Path.is_relative_to() (Python 3.9+) instead of a plain startswith()
    check to avoid the prefix-confusion bug where a path like
    /base_extension/evil passes startswith(/base).
    Aborts with 400 on traversal attempt, 404 if the file doesn't exist.
    """
    full = (base / relpath).resolve()
    if not full.is_relative_to(base):
        abort(400, "Invalid path")
    if not full.exists() or not full.is_file():
        abort(404)
    return full

@app.get("/d/<task_id>/raw/<path:relpath>")
@login_required
def raw_file(task_id, relpath):
    base = safe_task_base(task_id)
    full = _safe_resolve_relpath(base, relpath)

    # Check if file is still being downloaded
    if _is_still_downloading(full):
        abort(409, "File is still being downloaded. Please wait until the download completes.")

    # Metadata
    st = full.stat()
    etag = _etag_for_stat(st)
    last_mod = _http_time(st.st_mtime)
    mime = _guess_mime(full.name)
    inline = request.args.get("inline", "0") in ("1", "true", "yes")
    # Use RFC 6266 filename* parameter (percent-encoded UTF-8) to safely handle
    # any filename, including those with quotes, backslashes, or control characters.
    from urllib.parse import quote as _urlquote
    encoded_name = _urlquote(full.name, safe="")
    cd = ("inline" if inline else "attachment") + f"; filename*=UTF-8''{encoded_name}"

    # Conditional GET
    inm = request.headers.get("If-None-Match")
    if inm and inm.strip() == etag:
        resp = make_response("", 304)
        resp.headers["ETag"] = etag
        resp.headers["Last-Modified"] = last_mod
        return resp

    if app.config["USE_X_ACCEL"]:
        accel = _accel_path(task_id, full.relative_to(base).as_posix())
        resp = make_response("", 200)
        resp.headers["X-Accel-Redirect"] = accel
        resp.headers["Content-Type"] = mime
        resp.headers["Content-Length"] = str(st.st_size)
        resp.headers["Accept-Ranges"] = "bytes"
        resp.headers["Cache-Control"] = "private, max-age=600"
        resp.headers["ETag"] = etag
        resp.headers["Last-Modified"] = last_mod
        resp.headers["Content-Disposition"] = cd
        return resp

    # Fallback: Python serves the file
    return send_file(
        full,
        mimetype=mime,
        as_attachment=not inline,
        download_name=full.name,
        conditional=True,
        max_age=600
    )

@app.get("/d/<task_id>/stream/<path:relpath>")
@login_required
def stream_video(task_id, relpath):
    """Stream video with Range request support"""
    base = safe_task_base(task_id)
    full = _safe_resolve_relpath(base, relpath)

    # Check if file is still being downloaded
    if _is_still_downloading(full):
        abort(409, "File is still being downloaded. Please wait until the download completes.")

    # Get file metadata
    st = full.stat()
    file_size = st.st_size
    mime = _guess_mime(full.name)
    etag = _etag_for_stat(st)
    last_mod = _http_time(st.st_mtime)

    # Handle Range requests for video seeking
    range_header = request.headers.get('Range')
    if not range_header:
        # No range, send full file with Flask's built-in conditional support
        return send_file(
            full,
            mimetype=mime,
            conditional=True,
            max_age=3600
        )

    # Parse Range header (simple byte range only, ignore multi-range)
    try:
        # Extract byte range - expect format like "bytes=0-1023" or "bytes=1024-"
        if not range_header.startswith('bytes='):
            abort(416)

        byte_range = range_header[6:].split(',')[0].strip()  # Take first range only
        parts = byte_range.split('-')

        if len(parts) != 2:
            abort(416)

        # Parse start and end, handling empty strings
        start = int(parts[0]) if parts[0].strip() else 0
        end = int(parts[1]) if parts[1].strip() else file_size - 1

        # Ensure valid range
        if start < 0 or start >= file_size or end >= file_size or start > end:
            abort(416)  # Range Not Satisfiable

        length = end - start + 1

        # For small ranges (< 5MB), read directly to avoid generator overhead
        # This significantly improves seeking performance
        if length < 5 * 1024 * 1024:
            with open(full, 'rb') as f:
                f.seek(start)
                data = f.read(length)

            resp = make_response(data)
            resp.status_code = 206
            resp.headers["Content-Type"] = mime
            resp.headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
            resp.headers["Content-Length"] = str(length)
            resp.headers["Accept-Ranges"] = "bytes"
            resp.headers["ETag"] = etag
            resp.headers["Last-Modified"] = last_mod
            # private: authenticated content must not be stored in shared caches
            resp.headers["Cache-Control"] = "private, max-age=3600"
            return resp

        # For larger ranges, use chunked streaming
        def generate():
            with open(full, 'rb') as f:
                f.seek(start)
                remaining = length
                chunk_size = 256 * 1024  # 256KB chunks for better throughput
                while remaining > 0:
                    chunk = f.read(min(chunk_size, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        resp = make_response(generate())
        resp.status_code = 206  # Partial Content
        resp.headers["Content-Type"] = mime
        resp.headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
        resp.headers["Content-Length"] = str(length)
        resp.headers["Accept-Ranges"] = "bytes"
        resp.headers["ETag"] = etag
        resp.headers["Last-Modified"] = last_mod
        # private: authenticated content must not be stored in shared caches
        resp.headers["Cache-Control"] = "private, max-age=3600"

        return resp
    except (ValueError, IndexError):
        abort(416, "Invalid Range header")

# ==============================================================================
# JSON API v2  — consumed by the Vite + React frontend
# ==============================================================================
# These endpoints mirror the existing template-based routes but respond with
# JSON only, enabling the new frontend-v2 SPA to communicate over fetch().
# All state-changing endpoints use Flask session auth (same cookie the SPA
# receives on login) — no CSRF tokens are needed because the SPA uses
# application/json with credentials:include (not form submissions).
# ==============================================================================

from werkzeug.exceptions import HTTPException as _HTTPException


@app.get("/v2/auth/setup-status")
def v2_setup_status():
    """Check whether first-time admin setup is still required."""
    check_data, check_err = w_request("GET", "/api/users/check")
    is_first_time = (not check_err) and (not check_data.get("has_users", True))
    return jsonify({"first_time_setup": is_first_time})


@app.post("/v2/auth/login")
def v2_login():
    """JSON login — supports both first-time setup and normal login."""
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()

    if not username or not password:
        return jsonify({"error": "Username and password are required"}), 400

    # Inline rate-limiting (same window/limit as the template login route)
    ip = request.remote_addr or "unknown"
    now = _time.time()
    window_start = now - _LOGIN_WINDOW
    ip_attempts = [ts for ts in _login_attempts.get(ip, []) if ts > window_start]
    if len(ip_attempts) >= _LOGIN_MAX_ATTEMPTS:
        log.warning("v2 login rate limit exceeded for IP %s", ip)
        return jsonify({"error": "Too many login attempts. Please wait a few minutes."}), 429
    ip_attempts.append(now)
    _login_attempts[ip] = ip_attempts

    # First-time setup check
    check_data, check_err = w_request("GET", "/api/users/check")
    is_first_time = (not check_err) and (not check_data.get("has_users", True))

    if is_first_time:
        body, err = w_request(
            "POST", "/api/users",
            json_body={"username": username, "password": password, "is_admin": True},
        )
        if err:
            return jsonify({"error": str(err[0])}), err[1]
        return jsonify({
            "first_time_setup": True,
            "message": f"Admin account '{username}' created. Please log in.",
        }), 201

    body, err = w_request(
        "POST", "/api/auth/verify",
        json_body={"username": username, "password": password},
    )
    if err or not body:
        return jsonify({"error": "Invalid username or password"}), 401

    user = User(body["id"], body["username"], body["is_admin"], body.get("role", "user"))
    login_user(user)
    return jsonify({
        "user": {
            "id": user.id,
            "username": user.username,
            "is_admin": user.is_admin,
            "role": user.role,
        }
    })


@app.post("/v2/auth/logout")
@login_required
def v2_logout():
    """JSON logout."""
    logout_user()
    return jsonify({"ok": True})


@app.get("/v2/auth/me")
@login_required
def v2_me():
    """Return the current authenticated user."""
    return jsonify({
        "id": current_user.id,
        "username": current_user.username,
        "is_admin": current_user.is_admin,
        "role": current_user.role,
    })


@app.get("/v2/health")
def v2_health():
    """Proxy the FastAPI health endpoint. Returns JSON."""
    body, err = w_request("GET", "/health")
    if err:
        return jsonify({"status": "down", "error": err[0]}), err[1]
    return jsonify(body)


@app.get("/v2/tasks")
@member_required
def v2_list_tasks():
    """List tasks for member-tier users (admin/member)."""
    limit = max(1, min(request.args.get("limit", 20, type=int), 100))
    offset = max(0, request.args.get("offset", 0, type=int))
    params = {"limit": limit, "offset": offset}
    body, err = w_request("GET", "/api/tasks", params=params)
    if err:
        return jsonify({"error": err[0]}), err[1]
    return jsonify(body)


@app.post("/v2/tasks")
@member_required
def v2_create_task():
    """Create a task from a magnet / URL. Accepts JSON. Returns JSON."""
    data = request.get_json(silent=True) or {}
    source = (data.get("source") or "").strip()
    mode = (data.get("mode") or "auto").strip()
    label = (data.get("label") or "").strip() or None

    if not source:
        return jsonify({"error": "source is required"}), 400
    if len(source) > MAX_SOURCE_LENGTH:
        return jsonify({"error": f"source too long (max {MAX_SOURCE_LENGTH} chars)"}), 400
    if mode not in ("auto", "select"):
        return jsonify({"error": "mode must be 'auto' or 'select'"}), 400
    if label and len(label) > MAX_LABEL_LENGTH:
        return jsonify({"error": f"label too long (max {MAX_LABEL_LENGTH} chars)"}), 400

    payload = {"mode": mode, "source": source, "user_id": current_user.id}
    if label:
        payload["label"] = label

    body, err = w_request("POST", "/api/tasks", json_body=payload)
    if err:
        return jsonify({"error": err[0]}), err[1]
    return jsonify(body)


@app.post("/v2/tasks/from-torrent")
@member_required
def v2_create_task_from_torrent():
    """Create a task by uploading a .torrent file. Converts to magnet link."""
    mode = request.form.get("mode", "auto")
    label = (request.form.get("label") or "").strip() or None

    if mode not in ("auto", "select"):
        return jsonify({"error": "mode must be 'auto' or 'select'"}), 400

    file = request.files.get("torrent_file")
    if not file or not file.filename:
        return jsonify({"error": "torrent_file is required"}), 400

    try:
        file_data = file.read()
        validate_torrent_file_data(file_data, file.filename)
        magnet = torrent_to_magnet(file_data)
    except Exception as exc:
        return jsonify({"error": f"Invalid torrent file: {exc}"}), 400

    payload = {"mode": mode, "source": magnet, "user_id": current_user.id}
    if label:
        payload["label"] = label

    body, err = w_request("POST", "/api/tasks", json_body=payload)
    if err:
        return jsonify({"error": err[0]}), err[1]
    return jsonify(body)


@app.get("/v2/tasks/<task_id>")
@member_required
def v2_get_task(task_id):
    """Return full task data as JSON."""
    body, err = w_request("GET", f"/api/tasks/{task_id}")
    if err:
        return jsonify({"error": err[0]}), err[1]
    return jsonify(body)


@app.post("/v2/tasks/<task_id>/sse-token")
@member_required
def v2_sse_token(task_id):
    """Obtain a short-lived SSE token for the given task.
    The SPA uses this token to open an EventSource directly against
    /api/tasks/{task_id}/events?token=... (FastAPI, via nginx)."""
    body, err = w_request("POST", f"/api/tasks/{task_id}/sse-token")
    if err:
        return jsonify({"error": err[0]}), err[1]
    return jsonify(body)


@app.post("/v2/tasks/<task_id>/select")
@member_required
def v2_select_files(task_id):
    """Submit file selection. Accepts JSON {fileIds: [...]}."""
    data = request.get_json(silent=True) or {}
    file_ids = data.get("fileIds") or []
    if not file_ids:
        return jsonify({"error": "fileIds must be a non-empty list"}), 400
    body, err = w_request(
        "POST", f"/api/tasks/{task_id}/select",
        json_body={"fileIds": file_ids},
    )
    if err:
        return jsonify({"error": err[0]}), err[1]
    return jsonify(body)


@app.post("/v2/tasks/<task_id>/cancel")
@member_required
def v2_cancel_task(task_id):
    """Cancel a running task."""
    body, err = w_request("POST", f"/api/tasks/{task_id}/cancel")
    if err:
        return jsonify({"error": err[0]}), err[1]
    return jsonify(body)


@app.delete("/v2/tasks/<task_id>")
@member_required
def v2_delete_task(task_id):
    """Delete a task. Pass ?purge_files=true to also remove downloaded files."""
    purge = request.args.get("purge_files", "false").lower() == "true"
    body, err = w_request(
        "DELETE", f"/api/tasks/{task_id}",
        params={"purge_files": purge},
    )
    if err:
        return jsonify({"error": err[0]}), err[1]
    return jsonify(body or {"ok": True})


@app.get("/v2/tasks/<task_id>/files")
@login_required
def v2_task_files(task_id):
    """Return the filesystem file listing for a task as JSON."""
    try:
        base = safe_task_base(task_id)
    except _HTTPException as exc:
        return jsonify({"error": exc.description or "Not found"}), exc.code
    except Exception:
        return jsonify({"error": "Task files not found"}), 404

    items = []
    try:
        for p in sorted(base.rglob("*")):
            if p.is_symlink() and not p.resolve().is_relative_to(base):
                continue
            if p.is_file() and _should_include_file(p):
                rel = p.relative_to(base).as_posix()
                items.append({
                    "rel": rel,
                    "size": p.stat().st_size,
                    "is_video": _is_video(p.name),
                    "is_downloading": _is_still_downloading(p),
                })
    except Exception as exc:
        log.error("v2_task_files error: %s", exc)
        return jsonify({"error": "Failed to list files"}), 500

    return jsonify({"entries": items})


def _v2_admin_forbidden():
    return jsonify({"error": "Admin access required"}), 403


# ------------------------------------------------------------------------------
# BlueCog view — v2 proxy routes
# ------------------------------------------------------------------------------

@app.get("/v2/bluecog/torrents")
@member_required
def v2_bluecog_list():
    """List .torrent files from the scraper downloads directory."""
    q = request.args.get("q", "").strip()
    params = {"q": q} if q else {}
    body, err = w_request("GET", "/api/bluecog/torrents", params=params)
    if err:
        return jsonify({"error": err[0]}), err[1]
    return jsonify(body)


@app.get("/v2/bluecog/rss/status")
@member_required
def v2_bluecog_rss_status():
    """Return the last RSS refresh status."""
    body, err = w_request("GET", "/api/bluecog/rss/status")
    if err:
        return jsonify({"error": err[0]}), err[1]
    return jsonify(body)


@app.post("/v2/bluecog/rss/refresh")
@member_required
def v2_bluecog_rss_refresh():
    """Signal the worker to run an RSS refresh immediately."""
    body, err = w_request("POST", "/api/bluecog/rss/refresh")
    if err:
        return jsonify({"error": err[0]}), err[1]
    return jsonify(body)


@app.post("/v2/bluecog/fetch-url")
@member_required
def v2_bluecog_fetch_url():
    """Fetch a single BlueCog source URL — runs Playwright in the worker.

    Uses a longer HTTP timeout because the Playwright fetch can take up to
    2 minutes.
    """
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "url is required"}), 400

    # Override the default 30-second w_request timeout for this slow operation
    worker_url = w_url("/api/bluecog/fetch-url")
    headers    = w_headers()
    try:
        r = requests.post(worker_url, headers=headers, json={"url": url}, timeout=150)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502

    try:
        body = r.json()
    except Exception:
        body = {"raw": r.text}

    if not r.ok:
        msg = body.get("detail") or body.get("error") or r.text
        return jsonify({"error": msg}), r.status_code
    return jsonify(body)


@app.post("/v2/bluecog/submit")
@member_required
def v2_bluecog_submit():
    """Create AllDebrid tasks from selected .torrent files."""
    data      = request.get_json(silent=True) or {}
    filenames = data.get("filenames") or []
    mode      = (data.get("mode") or "auto").strip()
    label     = (data.get("label") or "").strip() or None

    if not filenames:
        return jsonify({"error": "filenames is required"}), 400

    body, err = w_request("POST", "/api/bluecog/submit", json_body={
        "filenames": filenames,
        "mode":      mode,
        "label":     label,
        "user_id":   current_user.id,
    })
    if err:
        return jsonify({"error": err[0]}), err[1]
    return jsonify(body)





@app.get("/v2/admin/tasks")
@login_required
def v2_admin_tasks():
    if not current_user.is_admin:
        return _v2_admin_forbidden()

    status = request.args.get("status")
    limit = request.args.get("limit", 100, type=int)
    offset = request.args.get("offset", 0, type=int)

    params = {"limit": limit, "offset": offset}
    if status:
        params["status"] = status

    body, err = w_request("GET", "/api/tasks", params=params)
    if err:
        return jsonify({"error": err[0]}), err[1]
    return jsonify(body)


@app.get("/v2/admin/stats")
@login_required
def v2_admin_stats():
    if not current_user.is_admin:
        return _v2_admin_forbidden()

    body, err = w_request("GET", "/api/stats")
    if err:
        return jsonify({"error": err[0]}), err[1]
    return jsonify(body)


@app.get("/v2/admin/users")
@login_required
def v2_admin_users():
    if not current_user.is_admin:
        return _v2_admin_forbidden()

    body, err = w_request("GET", "/api/users")
    if err:
        return jsonify({"error": err[0]}), err[1]
    return jsonify(body)


@app.post("/v2/admin/users")
@login_required
def v2_admin_create_user():
    if not current_user.is_admin:
        return _v2_admin_forbidden()

    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    role = (data.get("role") or "user").strip()

    if not username or not password:
        return jsonify({"error": "Username and password are required"}), 400
    if role not in ("admin", "member", "user"):
        return jsonify({"error": "Invalid role"}), 400

    body, err = w_request(
        "POST",
        "/api/users",
        json_body={"username": username, "password": password, "role": role},
    )
    if err:
        return jsonify({"error": err[0]}), err[1]
    return jsonify(body), 201


@app.delete("/v2/admin/users/<int:user_id>")
@login_required
def v2_admin_delete_user(user_id: int):
    if not current_user.is_admin:
        return _v2_admin_forbidden()
    if user_id == current_user.id:
        return jsonify({"error": "You cannot delete your own account"}), 400

    body, err = w_request("DELETE", f"/api/users/{user_id}")
    if err:
        return jsonify({"error": err[0]}), err[1]
    return jsonify(body or {"ok": True})


@app.post("/v2/admin/users/<int:user_id>/role")
@login_required
def v2_admin_set_role(user_id: int):
    if not current_user.is_admin:
        return _v2_admin_forbidden()
    if user_id == current_user.id:
        return jsonify({"error": "You cannot modify your own role"}), 400

    data = request.get_json(silent=True) or {}
    role = (data.get("role") or "").strip()
    if role not in ("admin", "member", "user"):
        return jsonify({"error": "Invalid role"}), 400

    body, err = w_request("POST", f"/api/users/{user_id}/set-role", json_body={"role": role})
    if err:
        return jsonify({"error": err[0]}), err[1]
    return jsonify(body)


@app.post("/v2/admin/users/<int:user_id>/reset-password")
@login_required
def v2_admin_reset_password(user_id: int):
    if not current_user.is_admin:
        return _v2_admin_forbidden()
    if user_id == current_user.id:
        return jsonify({"error": "You cannot reset your own password here"}), 400

    data = request.get_json(silent=True) or {}
    password = (data.get("password") or "").strip()
    if not password:
        return jsonify({"error": "Password is required"}), 400

    body, err = w_request(
        "POST",
        f"/api/users/{user_id}/reset-password",
        json_body={"password": password},
    )
    if err:
        return jsonify({"error": err[0]}), err[1]
    return jsonify(body or {"ok": True})


# ==============================================================================
# Serve the Vite React SPA (production)
# ==============================================================================
# In development the Vite dev server (port 5173) proxies /v2/ and /d/ to Flask.
# In production, `vite build` outputs to frontend/static/dist/. Flask serves
# that directory for all SPA routes so that client-side routing works correctly.
# ==============================================================================

_DIST_DIR = Path(__file__).parent / "static" / "dist"


@app.get("/app/")
@app.get("/app/<path:path>")
def serve_vite_spa(path: str = ""):
    """Serve the built Vite SPA under /app/. Falls back gracefully if the
    build directory does not exist (development mode)."""
    if not _DIST_DIR.exists():
        return jsonify({"error": "SPA not built. Run: cd frontend && npm run build"}), 404
    from flask import send_from_directory as _sfd
    # Serve real assets (JS/CSS/images) from dist/; everything else → index.html
    asset = _DIST_DIR / path
    if path and asset.exists() and asset.is_file():
        return _sfd(str(_DIST_DIR), path)
    return _sfd(str(_DIST_DIR), "index.html")


# ------------------------------------------------------------------------------
# Dev server entrypoint
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=True)
