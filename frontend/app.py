from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file, abort, make_response, session, Response, stream_with_context
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from pathlib import Path
from dotenv import load_dotenv
import os, io, tarfile, logging, requests, mimetypes, hashlib, secrets, re, threading, queue
from datetime import datetime

# ------------------------------------------------------------------------------
# Bootstrapping / App setup
# ------------------------------------------------------------------------------
load_dotenv()

# Import shared utilities (no database connections)
from app.constants import Limits
from app.utils import torrent_to_magnet
from app.validation import validate_torrent_file_data

# Transcoding pipeline (ffmpeg-based HLS for browser-incompatible formats)
import frontend.transcoding as _transcoding

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
login_manager.login_view = "login"
login_manager.init_app(app)

# UUID pattern (reused from backend constants without importing DB-connected modules)
_UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE)

# ------------------------------------------------------------------------------
# CSRF helpers (lightweight, session-based)
# ------------------------------------------------------------------------------
def _csrf_token() -> str:
    """Return (and lazily create) the CSRF token stored in the user's session."""
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_hex(32)
    return session["_csrf_token"]

def _validate_csrf():
    """Validate CSRF token submitted with a state-changing POST request.
    Aborts with 403 on mismatch to prevent cross-site request forgery."""
    token = request.form.get("_csrf_token") or request.headers.get("X-CSRFToken")
    expected = session.get("_csrf_token")
    if not token or not expected or not secrets.compare_digest(token, expected):
        log.warning("CSRF validation failed for %s %s", request.method, request.path)
        abort(403, "Invalid or missing CSRF token")

# Expose the helper in Jinja2 templates so every form can render the hidden field.
app.jinja_env.globals["csrf_token"] = _csrf_token

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
    flash("Please log in to continue.", "error")
    return redirect(url_for("login"))

def admin_required(f):
    """Decorator to require admin access"""
    from functools import wraps
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_admin:
            return render_template("access_denied.html"), 403
        return f(*args, **kwargs)
    return decorated_function

def member_required(f):
    """Decorator to require member or admin access (home page, task management).
    Users with role 'user' are redirected to the downloads area."""
    from functools import wraps
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_member:
            return render_template("access_denied.html"), 403
        return f(*args, **kwargs)
    return decorated_function

# ------------------------------------------------------------------------------
# Jinja filters (global)
# ------------------------------------------------------------------------------
def human_bytes(n):
    try:
        n = int(n)
    except Exception:
        return "—"
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    k = 1024.0
    i = 0
    v = float(n)
    while v >= k and i < len(units) - 1:
        v /= k
        i += 1
    return (f"{v:.1f}" if (v < 10 and i >= 2) else f"{int(v)}") + f" {units[i]}"

def percent(a, b):
    try:
        a = float(a); b = float(b)
        if b <= 0: return 0
        p = (a / b) * 100.0
        if p < 0: p = 0
        if p > 100: p = 100
        return int(round(p))
    except Exception:
        return 0

app.add_template_filter(human_bytes, "hbytes")
app.add_template_filter(percent, "percent")

# ------------------------------------------------------------------------------
# Lightweight data classes (used where templates expect ORM-style objects)
# ------------------------------------------------------------------------------
def _parse_dt(iso_str):
    """Parse an ISO-format datetime string from the API; return None on failure."""
    if not iso_str:
        return None
    try:
        return datetime.fromisoformat(iso_str)
    except ValueError:
        return None

class _UserStats:
    """Thin wrapper over the stats dict returned by the API."""
    __slots__ = ("total_magnets_processed", "total_downloads", "total_bytes_downloaded")
    def __init__(self, d: dict):
        self.total_magnets_processed = d.get("total_magnets_processed", 0)
        self.total_downloads = d.get("total_downloads", 0)
        self.total_bytes_downloaded = d.get("total_bytes_downloaded", 0)

class _UserData:
    """Thin wrapper over a user dict returned by the API (template-compatible)."""
    __slots__ = ("id", "username", "is_admin", "role", "created_at", "last_login", "stats")
    def __init__(self, d: dict):
        self.id = d["id"]
        self.username = d["username"]
        self.is_admin = d.get("is_admin", False)
        self.role = d.get("role", "user")
        self.created_at = _parse_dt(d.get("created_at"))
        self.last_login = _parse_dt(d.get("last_login"))
        self.stats = _UserStats(d["stats"]) if d.get("stats") else None

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
    """Check if a file is a video or audio media file (including transcodable formats)."""
    return _transcoding.is_media_file(filename)

def _is_still_downloading(filepath: Path) -> bool:
    """Check if a file is still being downloaded by aria2c"""
    aria2_control = Path(str(filepath) + ".aria2")
    return aria2_control.exists()

def _should_include_file(filepath: Path) -> bool:
    """Check if a file should be included in listings (exclude .aria2 control files)"""
    return not filepath.name.endswith(".aria2")

# ------------------------------------------------------------------------------
# Pages / Routes
# ------------------------------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    # Check if this is first-time setup (no users exist)
    check_data, check_err = w_request("GET", "/api/users/check")
    is_first_time = (not check_err) and (not check_data.get("has_users", True))

    if request.method == "POST":
        _validate_csrf()
        _login_rate_check()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        if not username or not password:
            flash("Username and password are required.", "error")
            return render_template("login.html", is_first_time=is_first_time)

        if is_first_time:
            # First-time setup: create the first admin account
            body, err = w_request("POST", "/api/users",
                                  json_body={"username": username, "password": password, "is_admin": True})
            if err:
                flash(str(err[0]), "error")
                return render_template("login.html", is_first_time=is_first_time)
            flash(f"Admin account '{username}' created successfully! Please log in.", "success")
            return redirect(url_for("login"))
        else:
            # Normal login — verify credentials via the API
            body, err = w_request("POST", "/api/auth/verify",
                                  json_body={"username": username, "password": password})
            if not err and body:
                user = User(body["id"], body["username"], body["is_admin"], body.get("role", "user"))
                login_user(user)
                flash("Logged in successfully!", "success")
                return redirect(url_for("index"))
            else:
                flash("Invalid username or password.", "error")

    return render_template("login.html", is_first_time=is_first_time)

@app.route("/logout")
def logout():
    logout_user()
    flash("Logged out successfully!", "success")
    return redirect(url_for("index"))

@app.route('/test-task')
@admin_required
def test_task_view():
    task_id = 'test-task-id'
    t = {
        'status': 'waiting_selection',
        'files': ['file1', 'file2', 'file3']
    }
    refresh = None
    mode = request.args.get('mode', 'auto')
    return render_template('task.html', task_id=task_id, t=t, refresh=refresh, mode=mode)

@app.get("/")
@member_required
def index():
    return render_template("index.html")

@app.post("/tasks/new")
@member_required
def create_task():
    """Create a new download task with validation - supports multiple sources and torrent files"""
    _validate_csrf()
    mode = request.form.get("mode", "auto")
    source = request.form.get("source", "").strip()
    label = request.form.get("label", "").strip() or None
    
    # Collect sources from text input
    sources = []
    if source:
        # Input validation for text sources
        if len(source) > MAX_SOURCE_LENGTH:
            flash(f"Source input is too long (max {MAX_SOURCE_LENGTH} characters)", "error")
            return redirect(url_for("index"))
        
        # Split sources by newline and filter empty lines
        sources = [line.strip() for line in source.split('\n') if line.strip()]
    
    # Process torrent file uploads
    torrent_files = request.files.getlist('torrent_files')
    torrent_magnets = []
    
    if torrent_files:
        for i, file in enumerate(torrent_files):
            if not file or not file.filename:
                continue
                
            try:
                # Read file data
                file_data = file.read()
                
                # Validate torrent file
                validate_torrent_file_data(file_data, file.filename)
                
                # Convert to magnet link
                magnet = torrent_to_magnet(file_data)
                torrent_magnets.append(magnet)
                
                log.info(f"Converted torrent file '{file.filename}' to magnet link")
                
            except Exception as e:
                log.error(f"Failed to process torrent file '{file.filename}': {e}")
                flash(f"❌ Failed to process torrent file '{file.filename}': {str(e)}", "error")
    
    # Combine text sources and torrent-derived magnets
    sources.extend(torrent_magnets)
    
    # Validate we have at least one source
    if not sources:
        flash("Please either upload torrent file(s) or enter magnet link(s)/URL(s)", "error")
        return redirect(url_for("index"))
    
    # Validate mode
    if mode not in ("auto", "select"):
        flash("Invalid mode selected", "error")
        return redirect(url_for("index"))
    
    if label and len(label) > MAX_LABEL_LENGTH:
        flash(f"Label is too long (max {MAX_LABEL_LENGTH} characters)", "error")
        return redirect(url_for("index"))
    
    # Deduplicate sources while preserving order
    seen_sources = set()
    unique_sources = []
    duplicate_count = 0
    for src in sources:
        src_lower = src.lower()  # Case-insensitive deduplication
        if src_lower not in seen_sources:
            seen_sources.add(src_lower)
            unique_sources.append(src)
        else:
            duplicate_count += 1
    
    sources = unique_sources
    
    if duplicate_count > 0:
        log.info(f"Removed {duplicate_count} duplicate source(s) from submission")
        flash(f"ℹ️ Removed {duplicate_count} duplicate source(s) from submission", "info")
    
    if not sources:
        flash("No unique sources to process after removing duplicates", "error")
        return redirect(url_for("index"))
    
    log.info(f"Processing {len(sources)} unique source(s)")
    
    # Check max sources limit (matching backend limit)
    if len(sources) > Limits.MAX_SOURCES_PER_SUBMISSION:
        flash(f"Too many sources (maximum {Limits.MAX_SOURCES_PER_SUBMISSION} allowed)", "error")
        return redirect(url_for("index"))
    
    # Create tasks for each source
    created_tasks = []
    reused_tasks = []
    failed_sources = []
    task_id_to_source = {}  # Track which source created which task
    
    for i, src in enumerate(sources):
        # Prepare payload with user_id for tracking
        payload = {"mode": mode, "source": src, "user_id": current_user.id}
        if label:
            # Add index suffix for multi-source labels
            if len(sources) > 1:
                suffix = f" ({i+1}/{len(sources)})"
                # Ensure label doesn't exceed max length with suffix
                max_base_len = MAX_LABEL_LENGTH - len(suffix)
                base_label = label[:max_base_len] if len(label) > max_base_len else label
                payload["label"] = base_label + suffix
            else:
                payload["label"] = label
        
        # Make API request
        log.info(f"Creating task {i+1}/{len(sources)}: mode={mode}, source_len={len(src)}, user_id={current_user.id}")
        body, err = w_request("POST", "/api/tasks", json_body=payload)
        
        if err:
            log.error(f"Task creation failed for source {i+1}: {err[0]}")
            failed_sources.append(f"Source {i+1}: {err[0]}")
            continue
        
        task_id = body.get("taskId") or body.get("id")
        if not task_id:
            log.error(f"Task created but no taskId returned for source {i+1}")
            failed_sources.append(f"Source {i+1}: No task ID returned")
            continue
        
        # Track task ID to source mapping
        task_id_to_source[task_id] = src
        
        # Check if task was reused
        if body.get("reused"):
            log.info(f"Task reused: {task_id}")
            if task_id not in reused_tasks:  # Avoid duplicate task IDs
                reused_tasks.append(task_id)
        else:
            log.info(f"New task created: {task_id}")
            if task_id not in created_tasks:  # Avoid duplicate task IDs
                created_tasks.append(task_id)
    
    # Show results to user
    if created_tasks:
        flash(f"✅ Created {len(created_tasks)} new task(s): {', '.join(created_tasks)}", "ok")
    if reused_tasks:
        flash(f"♻️ Reused {len(reused_tasks)} existing task(s): {', '.join(reused_tasks)}", "success")
    if failed_sources:
        flash(f"❌ Failed to create {len(failed_sources)} task(s): {'; '.join(failed_sources)}", "error")
    
    # Redirect logic with better handling
    all_tasks = created_tasks + reused_tasks
    
    if len(all_tasks) == 0:
        # No tasks created or reused, go back to index
        flash("No tasks were created. Please check your sources and try again.", "error")
        return redirect(url_for("index"))
    elif len(all_tasks) == 1:
        # Single task - redirect to task view
        task_id = all_tasks[0]
        try:
            # Verify the task exists before redirecting
            task_data, err = w_request("GET", f"/api/tasks/{task_id}")
            if err:
                log.warning(f"Task {task_id} verification failed: {err[0]}, redirecting to admin page")
                flash(f"⚠️ Task created but couldn't load details. Check the admin page.", "warning")
                return redirect(url_for("admin_page"))
            return redirect(url_for("task_view", mode=mode, task_id=task_id, refresh=request.args.get("refresh", 3)))
        except Exception as e:
            log.error(f"Error verifying task {task_id}: {e}")
            flash(f"⚠️ Task created but couldn't verify. Check the admin page.", "warning")
            return redirect(url_for("admin_page"))
    else:
        # Multiple tasks - redirect to admin page to view all
        return redirect(url_for("admin_page"))

@app.post("/tasks/upload")
@admin_required
def upload_file():
    """Upload a file directly and create a task - admin only"""
    _validate_csrf()
    # Get uploaded file
    if 'upload_file' not in request.files:
        flash("No file provided", "error")
        return redirect(url_for("index"))
    
    file = request.files['upload_file']
    
    if not file or not file.filename:
        flash("No file selected", "error")
        return redirect(url_for("index"))
    
    # Get label
    label = request.form.get("upload_label", "").strip() or None
    
    if label and len(label) > MAX_LABEL_LENGTH:
        flash(f"Label is too long (max {MAX_LABEL_LENGTH} characters)", "error")
        return redirect(url_for("index"))
    
    # Prepare multipart form data
    files = {'file': (file.filename, file.stream, file.content_type)}
    data = {'user_id': str(current_user.id)}
    if label:
        data['label'] = label
    
    log.info(f"Uploading file: {file.filename}, size: {file.content_length if hasattr(file, 'content_length') else 'unknown'}")
    
    # Make API request with file upload
    url = w_url("/api/tasks/upload")
    headers = w_headers()
    
    try:
        # Use requests to upload file with streaming to handle large files
        r = requests.post(url, headers=headers, files=files, data=data, timeout=600)
        
        log.info(f"← WORKER {r.status_code} {url}")
        
        if not r.ok:
            try:
                error_data = r.json()
                msg = error_data.get("detail") or error_data.get("message") or r.text
            except Exception:
                msg = r.text
            flash(f"Upload failed: {msg}", "error")
            return redirect(url_for("index"))
        
        # Parse response
        try:
            body = r.json()
        except Exception:
            flash("Upload succeeded but response was invalid", "warning")
            return redirect(url_for("admin_page"))
        
        task_id = body.get("taskId") or body.get("id")
        if not task_id:
            flash("Upload succeeded but no task ID returned", "warning")
            return redirect(url_for("admin_page"))
        
        # Show success message
        filename = body.get("filename", file.filename)
        size_bytes = body.get("size", 0)
        size_str = human_bytes(size_bytes) if size_bytes else "unknown size"
        flash(f"✅ File uploaded successfully: {filename} ({size_str})", "ok")
        
        # Redirect to task view
        return redirect(url_for("task_view", task_id=task_id))
        
    except requests.exceptions.Timeout:
        flash("Upload timed out - file may be too large or connection is slow", "error")
        return redirect(url_for("index"))
    except Exception as e:
        log.error(f"Upload failed: {e}")
        flash(f"Upload failed: {str(e)}", "error")
        return redirect(url_for("index"))

@app.get("/admin")
@admin_required
def admin_page():
    """Admin dashboard to view and manage all tasks"""
    log.info("Admin page accessed")
    # Don't pass worker_key to frontend - it's a security risk
    # Frontend will use session-based auth to request data from backend
    return render_template("admin.html")

@app.get("/admin/tasks")
@admin_required
def admin_tasks():
    """Proxy endpoint for admin page to get tasks without exposing worker key"""
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

@app.get("/tasks/recent")
@member_required
def recent_tasks():
    """
    Return recent tasks for the current user.

    Admins see all tasks; members see only their own tasks.
    This endpoint is intentionally member-accessible (not admin-only)
    so that the recent-tasks widget on the home page works for all
    member-tier users.
    """
    limit = request.args.get("limit", 10, type=int)
    # Clamp to a sensible maximum to avoid over-fetching
    limit = max(1, min(limit, 50))

    params = {"limit": limit, "offset": 0}
    if not current_user.is_admin:
        # Members only see their own tasks
        params["user_id"] = current_user.id

    body, err = w_request("GET", "/api/tasks", params=params)
    if err:
        log.warning("recent_tasks backend error (status=%s)", err[1])
        return jsonify({"error": "Failed to load tasks"}), err[1]
    return jsonify(body)

@app.get("/admin/stats")
@admin_required
def get_stats():
    """Proxy endpoint to get system stats without exposing worker key"""
    if not app.config["WORKER_KEY"]:
        return jsonify({"error": "WORKER_API_KEY not configured"}), 500
    
    body, err = w_request("GET", "/api/stats")
    if err:
        return jsonify({"error": err[0]}), err[1]
    return jsonify(body)

@app.get("/admin/users")
@admin_required
def admin_users_page():
    """Admin page for user management"""
    data, err = w_request("GET", "/api/users")
    if err:
        flash(f"Failed to load users: {err[0]}", "error")
        users = []
    else:
        users = [_UserData(u) for u in data.get("users", [])]
    return render_template("admin_users.html", users=users)

@app.post("/admin/users/create")
@admin_required
def create_user_route():
    """Create a new user"""
    _validate_csrf()
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()
    role = request.form.get("role", "user").strip()

    if not username or not password:
        flash("Username and password are required", "error")
        return redirect(url_for("admin_users_page"))

    _, err = w_request("POST", "/api/users",
                       json_body={"username": username, "password": password, "role": role})
    if err:
        flash(str(err[0]), "error")
    else:
        flash(f"User '{username}' created successfully with role '{role}'", "success")
    return redirect(url_for("admin_users_page"))

@app.post("/admin/users/<int:user_id>/delete")
@admin_required
def delete_user_route(user_id: int):
    """Delete a user"""
    _validate_csrf()
    if user_id == current_user.id:
        flash("You cannot delete your own account", "error")
        return redirect(url_for("admin_users_page"))

    _, err = w_request("DELETE", f"/api/users/{user_id}")
    if err:
        flash(f"Failed to delete user: {err[0]}", "error")
    else:
        flash("User deleted successfully", "success")
    return redirect(url_for("admin_users_page"))

@app.post("/admin/users/<int:user_id>/toggle-admin")
@admin_required
def toggle_admin_route(user_id: int):
    """Toggle admin status (legacy; prefer set-role)"""
    _validate_csrf()
    if user_id == current_user.id:
        flash("You cannot modify your own role", "error")
        return redirect(url_for("admin_users_page"))

    body, err = w_request("POST", f"/api/users/{user_id}/toggle-admin")
    if err:
        flash(f"Failed to update user: {err[0]}", "error")
    else:
        is_admin = body.get("is_admin", False)
        flash(f"User is now {'an admin' if is_admin else 'a regular user'}", "success")
    return redirect(url_for("admin_users_page"))

@app.post("/admin/users/<int:user_id>/set-role")
@admin_required
def set_role_route(user_id: int):
    """Set a user's role"""
    _validate_csrf()
    if user_id == current_user.id:
        flash("You cannot modify your own role", "error")
        return redirect(url_for("admin_users_page"))

    role = request.form.get("role", "").strip()
    if role not in ("admin", "member", "user"):
        flash("Invalid role selected", "error")
        return redirect(url_for("admin_users_page"))

    body, err = w_request("POST", f"/api/users/{user_id}/set-role", json_body={"role": role})
    if err:
        flash(f"Failed to update role: {err[0]}", "error")
    else:
        flash(f"User role updated to '{role}'", "success")
    return redirect(url_for("admin_users_page"))

@app.post("/admin/users/<int:user_id>/reset-password")
@admin_required
def reset_password_route(user_id: int):
    """Reset user password"""
    _validate_csrf()
    new_password = request.form.get("new_password", "").strip()

    if not new_password:
        flash("New password is required", "error")
        return redirect(url_for("admin_users_page"))

    _, err = w_request("POST", f"/api/users/{user_id}/reset-password",
                       json_body={"password": new_password})
    if err:
        flash(f"Failed to reset password: {err[0]}", "error")
    else:
        flash("Password reset successfully", "success")
    return redirect(url_for("admin_users_page"))

@app.errorhandler(404)
def not_found(e):
    """Handle 404 errors"""
    log.warning(f"404 error: {request.url}")
    flash("Page not found", "error")
    return redirect(url_for("index"))

@app.errorhandler(500)
def server_error(e):
    """Handle 500 errors"""
    log.error(f"500 error: {str(e)}")
    flash("An internal error occurred. Please try again.", "error")
    return redirect(url_for("index"))

def get_task(task_id: str):
    body, err = w_request("GET", f"/api/tasks/{task_id}")
    if err:
        return None, err
    return body, None

@app.get("/tasks/<task_id>")
@member_required
def task_view(task_id):
    t, err = get_task(task_id)
    if err:
        flash(f"Load failed: {err[0]}", "error")
        t = None
    
    # Generate a secure SSE token (never expose WORKER_API_KEY to frontend)
    sse_token = None
    token_response, token_err = w_request("POST", f"/api/tasks/{task_id}/sse-token")
    if not token_err and token_response:
        sse_token = token_response.get("token")
    
    mode = (t or {}).get("mode") or request.args.get("mode", "auto")
    # Pass secure SSE token to template (use relative URL /api for nginx proxy)
    return render_template("task.html", task_id=task_id, t=t, mode=mode, 
                         sse_token=sse_token)

@app.get("/tasks/<task_id>/data")
@member_required
def task_data(task_id):
    """JSON endpoint for polling task state (SSE fallback)."""
    t, err = get_task(task_id)
    if err:
        msg, code = err
        log.warning(f"task_data fetch failed for {task_id}: {msg}")
        return jsonify({"error": "Failed to load task"}), code
    return jsonify(t or {})

@app.post("/tasks/<task_id>/select")
@member_required
def task_select(task_id):
    _validate_csrf()
    file_ids = request.form.getlist("fileIds")
    if not file_ids:
        flash("Pick at least one file", "error")
        return redirect(url_for("task_view", task_id=task_id))
    _, err = w_request("POST", f"/api/tasks/{task_id}/select", json_body={"fileIds": file_ids})
    if err:
        flash(f"Select failed: {err[0]}", "error")
    else:
        flash("Selection submitted", "ok")
    return redirect(url_for("task_view", task_id=task_id, refresh=request.args.get("refresh", 3)))

@app.post("/tasks/<task_id>/cancel")
@member_required
def task_cancel(task_id):
    _validate_csrf()
    _, err = w_request("POST", f"/api/tasks/{task_id}/cancel")
    if err:
        flash(f"Cancel failed: {err[0]}", "error")
    else:
        flash("Canceled", "ok")
    return redirect(url_for("task_view", task_id=task_id))

@app.post("/tasks/<task_id>/delete")
@member_required
def task_delete(task_id):
    _validate_csrf()
    purge = request.form.get("purge_files", "false").lower() == "true"
    _, err = w_request("DELETE", f"/api/tasks/{task_id}", params={"purge_files": purge})
    if err:
        flash(f"Delete failed: {err[0]}", "error")
        return redirect(url_for("task_view", task_id=task_id))
    flash("Deleted", "ok")
    return redirect(url_for("index"))

# ------------------------------------------------------------------------------
# Debug
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

@app.get("/d/<task_id>/")
@login_required
def list_folder(task_id):
    base = safe_task_base(task_id)
    items = []
    for p in sorted(base.rglob("*")):
        # Skip symlinks that escape the base directory (traversal via symlink)
        if p.is_symlink() and not p.resolve().is_relative_to(base):
            continue
        if p.is_file() and _should_include_file(p):
            rel = p.relative_to(base).as_posix()
            items.append({
                "rel": rel,
                "size": p.stat().st_size,
                "is_video": _is_video(p.name),
                "is_downloading": _is_still_downloading(p)
            })
    return render_template("folder.html", task_id=task_id, entries=items)

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

@app.get("/d/<task_id>/play/<path:relpath>")
@login_required
def play_video(task_id, relpath):
    """Smart media player page — supports direct play and ffmpeg transcoding."""
    base = safe_task_base(task_id)
    full = _safe_resolve_relpath(base, relpath)

    # Check if file is still being downloaded
    if _is_still_downloading(full):
        flash("This file is still being downloaded. Please wait until the download completes.", "error")
        return redirect(url_for("list_folder", task_id=task_id))

    if not _is_video(full.name):
        flash("This file is not a supported media type", "error")
        return redirect(url_for("list_folder", task_id=task_id))

    st = full.stat()
    mime = _guess_mime(full.name)

    # Determine browser compatibility and ffmpeg availability
    needs_transcode = not _transcoding.is_browser_compatible(full.name)
    has_ffmpeg = _transcoding.ffmpeg_available()
    job_id = _transcoding.job_id_for(task_id, relpath)
    existing_job = _transcoding.get_job(job_id)

    return render_template(
        "player.html",
        task_id=task_id,
        relpath=relpath,
        filename=full.name,
        size=st.st_size,
        mime_type=mime,
        video_url=url_for("stream_video", task_id=task_id, relpath=relpath),
        download_url=url_for("raw_file", task_id=task_id, relpath=relpath),
        back_url=url_for("list_folder", task_id=task_id),
        needs_transcode=needs_transcode,
        has_ffmpeg=has_ffmpeg,
        job_id=job_id,
        existing_job=existing_job,
        min_segments_to_play=_transcoding.MIN_SEGMENTS_TO_PLAY,
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

# ------------------------------------------------------------------------------
# Transcoding routes (ffmpeg-based HLS for browser-incompatible formats)
# ------------------------------------------------------------------------------

@app.get("/api/player/status")
@login_required
def player_status():
    """Return ffmpeg availability, current load, and active job counts."""
    return jsonify({
        "ffmpeg_available": _transcoding.ffmpeg_available(),
        "active_jobs": _transcoding.active_job_count(),
        "max_jobs": _transcoding.MAX_CONCURRENT_TRANSCODES,
        "system_load": round(_transcoding.get_system_load(), 2),
        "load_limit": _transcoding.CPU_LOAD_LIMIT,
        "overloaded": _transcoding.is_overloaded(),
    })


@app.post("/d/<task_id>/transcode/<path:relpath>")
@login_required
def start_transcode(task_id, relpath):
    """Start (or return the existing) transcode job for a media file."""
    base = safe_task_base(task_id)
    full = _safe_resolve_relpath(base, relpath)

    if _is_still_downloading(full):
        return jsonify({"error": "File is still being downloaded"}), 409

    if not _transcoding.is_media_file(full.name):
        return jsonify({"error": "Not a supported media file"}), 400

    try:
        job = _transcoding.start_transcode(task_id, relpath, full)
    except RuntimeError as exc:
        # exc.args[0] is a controlled message we set in start_transcode
        return jsonify({"error": exc.args[0] if exc.args else "Transcoding service is currently unavailable"}), 503

    return jsonify(job), 202


@app.get("/d/<task_id>/transcode/job/<job_id>")
@login_required
def transcode_job_status(task_id, job_id):
    """Poll the status of a transcode job."""
    job = _transcoding.get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    # Sanity-check that this job belongs to the requesting task
    if job.get("task_id") != task_id:
        abort(403)

    # Expose the HLS URL as soon as enough segments are ready to start playing,
    # not just when the full transcode is complete.
    if job.get("playable"):
        job["hls_url"] = url_for(
            "serve_hls",
            job_id=job_id,
            filename="index.m3u8",
            _external=False,
        )

    return jsonify(job)


@app.get("/hls/<job_id>/<path:filename>")
@login_required
def serve_hls(job_id, filename):
    """Serve HLS playlist or segment files.

    Files are served as soon as they exist on disk — the job does not need
    to be fully complete.  This enables progressive / live-transcode playback:
    the browser fetches the playlist, discovers new segments as ffmpeg writes
    them, and plays without waiting for the entire transcode to finish.

    Cache policy:
    - While transcoding the m3u8 playlist must not be cached (it changes).
    - After completion the playlist is static and may be cached.
    - Segment (.ts) files are immutable once written and are always cacheable.
    """
    job = _transcoding.get_job(job_id)
    if not job:
        abort(404)

    # Allow access whenever the job is transcoding or done
    if job["status"] not in ("transcoding", "done"):
        abort(404, "Transcode output not available")

    out_dir = Path(job["output_dir"])
    # Restrict to the job's own output directory (path-traversal guard)
    try:
        target = (out_dir / filename).resolve()
        target.relative_to(out_dir.resolve())  # raises ValueError if escaping
    except (ValueError, OSError):
        abort(403)

    if not target.exists():
        abort(404)

    # Choose the right MIME type and cache policy
    if filename.endswith(".m3u8"):
        mime = "application/vnd.apple.mpegurl"
        if job["status"] == "transcoding":
            # Live playlist — must not be cached; browser must re-fetch to get new segments
            resp = make_response(send_file(target, mimetype=mime))
            resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            resp.headers["Pragma"] = "no-cache"
            resp.headers["Expires"] = "0"
            return resp
        # Completed — static, cacheable
        return send_file(target, mimetype=mime, max_age=3600)
    elif filename.endswith(".ts"):
        # Segments are immutable once written
        return send_file(target, mimetype="video/MP2T", max_age=86400)
    else:
        return send_file(target, mimetype="application/octet-stream", max_age=3600)


# ------------------------------------------------------------------------------
# Dev server entrypoint
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=True)
