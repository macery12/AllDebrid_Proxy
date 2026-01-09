from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file, abort, make_response
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required
from werkzeug.security import check_password_hash, generate_password_hash
from pathlib import Path
from dotenv import load_dotenv
import os, io, tarfile, logging, requests, mimetypes, hashlib

# ------------------------------------------------------------------------------
# Bootstrapping / App setup
# ------------------------------------------------------------------------------
load_dotenv()

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

login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.init_app(app)

# ------------------------------------------------------------------------------
# Auth / Users
# ------------------------------------------------------------------------------
def _load_users_from_env():
    users = {}
    multi = os.environ.get("LOGIN_USERS", "test:test;").strip()
    if multi:
        for chunk in [c.strip() for c in multi.split(";") if c.strip()]:
            if ":" not in chunk:
                continue
            username, pw = chunk.split(":", 1)
            username = username.strip()
            pw = pw.strip()
            if not username or not pw:
                continue
            if pw.startswith(("pbkdf2:", "scrypt:", "argon2:")):
                password_hash = pw
            else:
                password_hash = generate_password_hash(pw)
            users[username] = {"password_hash": password_hash}
    return users

_USERS = _load_users_from_env()

class User(UserMixin):
    def __init__(self, username: str):
        self.id = username  # Flask-Login uses .id
    @property
    def is_active(self):
        return True
    def verify_password(self, candidate: str) -> bool:
        info = _USERS.get(self.id)
        if not info:
            return False
        stored_hash = info["password_hash"]
        ok = check_password_hash(stored_hash, candidate)
        return bool(ok)

@login_manager.user_loader
def load_user(user_id):
    if user_id in _USERS:
        return User(user_id)
    return None

@login_manager.unauthorized_handler
def _unauth():
    flash("Please log in to continue.", "error")
    return redirect(url_for("login"))

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
    return h

def w_url(path: str) -> str:
    if not path.startswith("/"):
        path = "/" + path
    return app.config["WORKER_BASE_URL"] + path

def w_request(method: str, path: str, *, params=None, json_body=None):
    url = w_url(path)
    log.info(f"→ WORKER {method} {url}")
    try:
        r = requests.request(method, url, headers=w_headers(), params=params, json=json_body, timeout=30)
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
# Pages / Routes
# ------------------------------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        user = User(username)
        if user.verify_password(password):
            login_user(user)
            flash("Logged in successfully!", "success")
            return redirect(url_for("index"))
        else:
            flash("Invalid username or password.", "error")
    return render_template("login.html")

@app.route("/logout")
def logout():
    logout_user()
    flash("Logged out successfully!", "success")
    return redirect(url_for("index"))

@app.route('/test-task')
@login_required
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
@login_required
def index():
    hb, err = w_request("GET", "/health")
    health = {"ok": False, "error": err[0]} if err else hb
    return render_template("index.html", health=health)

@app.post("/tasks/new")
@login_required
def create_task():
    mode = request.form.get("mode", "auto")
    source = request.form.get("source", "").strip()
    label = request.form.get("label", "").strip() or None
    if not source:
        flash("Enter a magnet/link", "error")
        return redirect(url_for("index"))
    payload = {"mode": mode, "source": source}
    if label:
        payload["label"] = label
    body, err = w_request("POST", "/api/tasks", json_body=payload)
    if err:
        flash(f"Create failed: {err[0]}", "error")
        return redirect(url_for("index"))
    task_id = body.get("taskId") or body.get("id")
    if not task_id:
        flash("Task created but no taskId returned", "error")
        return redirect(url_for("index"))
    
    # Check if task was reused
    if body.get("reused"):
        flash(f"♻️ Task reused: {task_id} (files already downloaded)", "success")
    else:
        flash(f"Task created: {task_id}", "ok")
    
    return redirect(url_for("task_view", mode=mode, task_id=task_id, refresh=request.args.get("refresh", 3)))

@app.get("/admin")
@login_required
def admin_page():
    """Admin dashboard to view and manage all tasks"""
    return render_template("admin.html")

def get_task(task_id: str):
    body, err = w_request("GET", f"/api/tasks/{task_id}")
    if err:
        return None, err
    return body, None

@app.get("/tasks/<task_id>")
@login_required
def task_view(task_id):
    t, err = get_task(task_id)
    if err:
        flash(f"Load failed: {err[0]}", "error")
        t = None
    mode = (t or {}).get("mode") or request.args.get("mode", "auto")
    return render_template("task.html", task_id=task_id, t=t, mode=mode)

@app.post("/tasks/<task_id>/select")
@login_required
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
@login_required
def task_cancel(task_id):
    _, err = w_request("POST", f"/api/tasks/{task_id}/cancel")
    if err:
        flash(f"Cancel failed: {err[0]}", "error")
    else:
        flash("Canceled", "ok")
    return redirect(url_for("task_view", task_id=task_id))

@app.post("/tasks/<task_id>/delete")
@login_required
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
@login_required
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
