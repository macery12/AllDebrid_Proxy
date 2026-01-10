from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file, abort, make_response
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash
from pathlib import Path
from dotenv import load_dotenv
import os, io, tarfile, logging, requests, mimetypes, hashlib

# ------------------------------------------------------------------------------
# Bootstrapping / App setup
# ------------------------------------------------------------------------------
load_dotenv()

# Import user management utilities
from app import user_manager
from app.constants import Limits
from app.utils import torrent_to_magnet
from app.validation import validate_torrent_file_data

# Constants
MAX_SOURCE_LENGTH = 10000  # Maximum length for magnet/URL source
MAX_LABEL_LENGTH = 500     # Maximum length for task label

logging.basicConfig(
    level=logging.DEBUG if os.environ.get("DEBUG") == "1" else logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s'
)
log = logging.getLogger("ad-frontend-v1")

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "dev-secret")

# Config via env
app.config["WORKER_BASE_URL"] = os.environ.get("WORKER_BASE_URL", "http://localhost:8080").rstrip("/")
app.config["WORKER_KEY"] = os.environ.get("WORKER_API_KEY", "")
app.config["STORAGE_ROOT"] = os.environ.get("STORAGE_ROOT", "/srv/storage")
app.config["USE_X_ACCEL"] = os.environ.get("USE_X_ACCEL", "0") == "1"
app.config["NGINX_ACCEL_PREFIX"] = os.environ.get("NGINX_ACCEL_PREFIX", "/protected")

# Startup validation
if not app.config["WORKER_KEY"]:
    log.warning("=" * 80)
    log.warning("WARNING: WORKER_API_KEY environment variable is not set!")
    log.warning("Backend API calls will fail with 401 Unauthorized errors.")
    log.warning("Please set WORKER_API_KEY in your .env file.")
    log.warning("=" * 80)
elif app.config["WORKER_KEY"] == "change-me":
    log.warning("=" * 80)
    log.warning("WARNING: WORKER_API_KEY is still set to the default 'change-me'!")
    log.warning("Please change it to a secure value in your .env file.")
    log.warning("=" * 80)
else:
    log.info(f"WORKER_API_KEY configured (length: {len(app.config['WORKER_KEY'])} chars)")
    log.info(f"WORKER_BASE_URL: {app.config['WORKER_BASE_URL']}")

login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.init_app(app)

# ------------------------------------------------------------------------------
# Auth / Users (Database-backed)
# ------------------------------------------------------------------------------
class User(UserMixin):
    def __init__(self, user_id: int, username: str, is_admin: bool = False):
        self.id = user_id
        self.username = username
        self.is_admin = is_admin
    
    @property
    def is_active(self):
        return True
    
    def get_id(self):
        """Return user ID as string for Flask-Login"""
        return str(self.id)

@login_manager.user_loader
def load_user(user_id):
    try:
        # Convert to int, handle both numeric and string IDs
        numeric_id = int(user_id)
        db_user = user_manager.get_user_by_id(numeric_id)
        if db_user:
            return User(db_user.id, db_user.username, db_user.is_admin)
    except (ValueError, TypeError):
        # Invalid user_id format (e.g., old session with username)
        # Return None to force re-login
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
            # Show access denied page for non-admin users
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
    
    # Debug logging
    log.info(f"→ WORKER {method} {url}")
    log.debug(f"  Headers: {list(headers.keys())}")
    log.debug(f"  Worker key present: {bool(headers.get('X-Worker-Key'))}")
    if headers.get('X-Worker-Key'):
        # Log first and last 4 chars for debugging (never log the full key)
        key = headers['X-Worker-Key']
        log.debug(f"  Worker key pattern: {key[:4]}...{key[-4:] if len(key) > 8 else ''}")
    
    try:
        r = requests.request(method, url, headers=headers, params=params, json=json_body, timeout=30)
    except Exception as e:
        log.error(f"WORKER request failed: {e}")
        return None, (str(e), 502)
    log.info(f"← WORKER {r.status_code} {url}")
    if not r.ok:
        log.error(f"  Response: {r.text[:200]}")
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
# Pages / Routes
# ------------------------------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    # Check if this is first-time setup (no users exist)
    is_first_time = not user_manager.has_any_users()
    
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        
        if not username or not password:
            flash("Username and password are required.", "error")
            return render_template("login.html", is_first_time=is_first_time)
        
        if is_first_time:
            # First-time setup: create admin user
            try:
                user_manager.create_user(username, password, is_admin=True)
                flash(f"Admin account '{username}' created successfully! Please log in.", "success")
                # Redirect to login page (non-first-time mode)
                return redirect(url_for("login"))
            except ValueError as e:
                flash(str(e), "error")
                return render_template("login.html", is_first_time=is_first_time)
        else:
            # Normal login
            db_user = user_manager.verify_user(username, password)
            if db_user:
                user = User(db_user.id, db_user.username, db_user.is_admin)
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
@admin_required
def index():
    return render_template("index.html")

@app.post("/tasks/new")
@admin_required
def create_task():
    """Create a new download task with validation - supports multiple sources and torrent files"""
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

@app.get("/api/stats")
@admin_required
def get_stats():
    """Proxy endpoint to get system stats without exposing worker key"""
    if not app.config["WORKER_KEY"]:
        log.error("WORKER_API_KEY environment variable not set - cannot authenticate with backend")
        return jsonify({"error": "Backend authentication not configured. Please set WORKER_API_KEY in .env file"}), 500
    
    body, err = w_request("GET", "/api/stats")
    if err:
        log.error(f"Stats API request failed: {err[0]} (status {err[1]})")
        return jsonify({"error": err[0]}), err[1]
    return jsonify(body)

@app.get("/admin/users")
@admin_required
def admin_users_page():
    """Admin page for user management"""
    users = user_manager.get_all_users()
    return render_template("admin_users.html", users=users)

@app.post("/admin/users/create")
@admin_required
def create_user_route():
    """Create a new user"""
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()
    is_admin = request.form.get("is_admin") == "on"
    
    if not username or not password:
        flash("Username and password are required", "error")
        return redirect(url_for("admin_users_page"))
    
    try:
        user_manager.create_user(username, password, is_admin)
        flash(f"User '{username}' created successfully", "success")
    except ValueError as e:
        flash(str(e), "error")
    
    return redirect(url_for("admin_users_page"))

@app.post("/admin/users/<int:user_id>/delete")
@admin_required
def delete_user_route(user_id: int):
    """Delete a user"""
    if user_id == current_user.id:
        flash("You cannot delete your own account", "error")
        return redirect(url_for("admin_users_page"))
    
    user_manager.delete_user(user_id)
    flash("User deleted successfully", "success")
    return redirect(url_for("admin_users_page"))

@app.post("/admin/users/<int:user_id>/toggle-admin")
@admin_required
def toggle_admin_route(user_id: int):
    """Toggle admin status"""
    if user_id == current_user.id:
        flash("You cannot modify your own admin status", "error")
        return redirect(url_for("admin_users_page"))
    
    is_admin = user_manager.toggle_admin(user_id)
    flash(f"User is now {'an admin' if is_admin else 'a regular user'}", "success")
    return redirect(url_for("admin_users_page"))

@app.post("/admin/users/<int:user_id>/reset-password")
@admin_required
def reset_password_route(user_id: int):
    """Reset user password"""
    new_password = request.form.get("new_password", "").strip()
    
    if not new_password:
        flash("New password is required", "error")
        return redirect(url_for("admin_users_page"))
    
    user_manager.update_user_password(user_id, new_password)
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
@admin_required
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

@app.post("/tasks/<task_id>/select")
@admin_required
def task_select(task_id):
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
@admin_required
def task_cancel(task_id):
    _, err = w_request("POST", f"/api/tasks/{task_id}/cancel")
    if err:
        flash(f"Cancel failed: {err[0]}", "error")
    else:
        flash("Canceled", "ok")
    return redirect(url_for("task_view", task_id=task_id))

@app.post("/tasks/<task_id>/delete")
@admin_required
def task_delete(task_id):
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
        "storage_root": app.config["STORAGE_ROOT"],
    })

# ------------------------------------------------------------------------------
# Fileshare
# ------------------------------------------------------------------------------
def safe_task_base(task_id: str) -> Path:
    root = Path(app.config["STORAGE_ROOT"]).resolve()
    base = (root / task_id / "files").resolve()
    if not str(base).startswith(str(root)):
        abort(400, "Invalid task id")
    if not base.exists():
        abort(404, "Task folder not found")
    return base

@app.get("/d/<task_id>/")
@login_required
def list_folder(task_id):
    base = safe_task_base(task_id)
    items = []
    for p in sorted(base.rglob("*")):
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
        if p.is_file() and _should_include_file(p):
            rel = p.relative_to(base).as_posix()
            out.write(f"/d/{task_id}/raw/{rel}\n")
    return out.getvalue(), 200, {"Content-Type": "text/plain; charset=utf-8"}

@app.get("/d/<task_id>.tar.gz")
@login_required
def tar_all(task_id):
    base = safe_task_base(task_id)
    mem = io.BytesIO()
    
    def exclude_aria2(tarinfo):
        """Filter function to exclude .aria2 files from tar archive"""
        if not _should_include_file(Path(tarinfo.name)):
            return None
        return tarinfo
    
    with tarfile.open(fileobj=mem, mode="w:gz") as tar:
        tar.add(base, arcname=f"{task_id}/files", filter=exclude_aria2)
    mem.seek(0)
    return send_file(mem, mimetype="application/gzip", as_attachment=True, download_name=f"{task_id}.tar.gz")

@app.get("/d/<task_id>/raw/<path:relpath>")
@login_required
def raw_file(task_id, relpath):
    base = safe_task_base(task_id)
    full = (base / relpath).resolve()
    if not str(full).startswith(str(base)):
        abort(400, "Invalid path")
    if not full.exists() or not full.is_file():
        abort(404)
    
    # Check if file is still being downloaded
    if _is_still_downloading(full):
        abort(409, "File is still being downloaded. Please wait until the download completes.")

    # Metadata
    st = full.stat()
    etag = _etag_for_stat(st)
    last_mod = _http_time(st.st_mtime)
    mime = _guess_mime(full.name)
    inline = request.args.get("inline", "0") in ("1", "true", "yes")
    cd = ("inline" if inline else "attachment") + f'; filename="{full.name}"'

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
    """Video player page"""
    base = safe_task_base(task_id)
    full = (base / relpath).resolve()
    if not str(full).startswith(str(base)):
        abort(400, "Invalid path")
    if not full.exists() or not full.is_file():
        abort(404)
    
    # Check if file is still being downloaded
    if _is_still_downloading(full):
        flash("This file is still being downloaded. Please wait until the download completes.", "error")
        return redirect(url_for("list_folder", task_id=task_id))
    
    if not _is_video(full.name):
        flash("This file is not a video", "error")
        return redirect(url_for("list_folder", task_id=task_id))
    
    st = full.stat()
    mime = _guess_mime(full.name)
    
    return render_template(
        "player.html",
        task_id=task_id,
        relpath=relpath,
        filename=full.name,
        size=st.st_size,
        mime_type=mime,
        video_url=url_for("stream_video", task_id=task_id, relpath=relpath),
        download_url=url_for("raw_file", task_id=task_id, relpath=relpath),
        back_url=url_for("list_folder", task_id=task_id)
    )

@app.get("/d/<task_id>/stream/<path:relpath>")
@login_required
def stream_video(task_id, relpath):
    """Stream video with Range request support"""
    base = safe_task_base(task_id)
    full = (base / relpath).resolve()
    if not str(full).startswith(str(base)):
        abort(400, "Invalid path")
    if not full.exists() or not full.is_file():
        abort(404)
    
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
            resp.headers["Cache-Control"] = "public, max-age=3600"
            return resp
        
        # For larger ranges, use chunked streaming
        def generate():
            with open(full, 'rb') as f:
                f.seek(start)
                remaining = length
                chunk_size = 256 * 1024  # Increased to 256KB for better throughput
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
        resp.headers["Cache-Control"] = "public, max-age=3600"
        
        return resp
    except (ValueError, IndexError):
        abort(416, "Invalid Range header")

# ------------------------------------------------------------------------------
# Dev server entrypoint
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=True)
