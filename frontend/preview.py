from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from flask import Flask, flash, jsonify, redirect, render_template, request, url_for


def human_bytes(n):
    try:
        n = int(n)
    except Exception:
        return "-"
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
        a = float(a)
        b = float(b)
        if b <= 0:
            return 0
        p = (a / b) * 100.0
        if p < 0:
            p = 0
        if p > 100:
            p = 100
        return int(round(p))
    except Exception:
        return 0


def _fake_user(is_admin=True):
    return SimpleNamespace(
        id=1,
        username="preview-admin" if is_admin else "preview-user",
        is_authenticated=True,
        is_admin=is_admin,
    )


def _build_user(username, user_id, is_admin, processed, downloads, bytes_downloaded):
    stats = SimpleNamespace(
        total_magnets_processed=processed,
        total_downloads=downloads,
        total_bytes_downloaded=bytes_downloaded,
    )
    return SimpleNamespace(
        id=user_id,
        username=username,
        is_admin=is_admin,
        created_at=datetime.utcnow(),
        last_login=datetime.utcnow(),
        stats=stats,
    )


def _task_context(variant):
    waiting = {
        "id": "preview-task",
        "status": "waiting_selection",
        "mode": "select",
        "label": "Preview Task",
        "source_type": "magnet",
        "source": "magnet:?xt=urn:btih:preview",
        "created_at": datetime.utcnow().isoformat(),
        "files": [
            {
                "fileId": "1",
                "name": "video/episode-01.mkv",
                "size": 734003200,
                "bytesDownloaded": 0,
                "speedBps": 0,
                "etaSeconds": None,
                "state": "waiting",
            },
            {
                "fileId": "2",
                "name": "subs/episode-01.srt",
                "size": 91234,
                "bytesDownloaded": 0,
                "speedBps": 0,
                "etaSeconds": None,
                "state": "waiting",
            },
        ],
    }

    downloading = {
        **waiting,
        "status": "downloading",
        "mode": "auto",
        "files": [
            {
                "fileId": "1",
                "name": "video/episode-01.mkv",
                "size": 734003200,
                "bytesDownloaded": 321126400,
                "speedBps": 5242880,
                "etaSeconds": 80,
                "state": "downloading",
            },
            {
                "fileId": "2",
                "name": "subs/episode-01.srt",
                "size": 91234,
                "bytesDownloaded": 91234,
                "speedBps": 0,
                "etaSeconds": 0,
                "state": "done",
            },
        ],
    }

    ready = {
        **waiting,
        "status": "ready",
        "mode": "auto",
        "files": [
            {
                "fileId": "1",
                "name": "video/episode-01.mkv",
                "size": 734003200,
                "bytesDownloaded": 734003200,
                "speedBps": 0,
                "etaSeconds": 0,
                "state": "done",
            },
            {
                "fileId": "2",
                "name": "subs/episode-01.srt",
                "size": 91234,
                "bytesDownloaded": 91234,
                "speedBps": 0,
                "etaSeconds": 0,
                "state": "done",
            },
        ],
    }

    task_by_variant = {
        "waiting": waiting,
        "downloading": downloading,
        "ready": ready,
    }

    task = task_by_variant.get(variant, waiting)
    return {
        "task_id": "preview-task",
        "mode": task.get("mode", "auto"),
        "sse_token": "preview-token",
        "t": task,
    }


def _template_context(template_name, variant):
    if template_name == "index.html":
        return {}

    if template_name == "login.html":
        return {"is_first_time": variant == "first-time"}

    if template_name == "admin.html":
        return {}

    if template_name == "admin_users.html":
        users = [
            _build_user("admin", 1, True, 18, 27, 12884901888),
            _build_user("viewer", 2, False, 2, 3, 1572864000),
        ]
        return {"users": users}

    if template_name == "task.html":
        return _task_context(variant)

    if template_name == "folder.html":
        return {
            "task_id": "preview-task",
            "entries": [
                {
                    "rel": "video/episode-01.mkv",
                    "size": 734003200,
                    "is_video": True,
                    "is_downloading": variant == "downloading",
                },
                {
                    "rel": "subs/episode-01.srt",
                    "size": 91234,
                    "is_video": False,
                    "is_downloading": False,
                },
            ],
        }

    if template_name == "player.html":
        return {
            "task_id": "preview-task",
            "relpath": "video/episode-01.mkv",
            "filename": "episode-01.mkv",
            "size": 734003200,
            "mime_type": "video/mp4",
            "video_url": "/mock/video.mp4",
            "download_url": "/d/preview-task/raw/video/episode-01.mkv",
            "back_url": "/preview/folder",
        }

    if template_name == "access_denied.html":
        return {}

    if template_name == "base.html":
        return {}

    return {}


def create_preview_app():
    templates_dir = Path(__file__).parent / "templates"
    app = Flask(__name__, template_folder=str(templates_dir))
    app.secret_key = "preview-only-secret"
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.jinja_env.auto_reload = True
    app.add_template_filter(human_bytes, "hbytes")
    app.add_template_filter(percent, "percent")

    @app.context_processor
    def inject_preview_defaults():
        as_user = request.args.get("as", "admin").lower()
        return {"current_user": _fake_user(is_admin=(as_user != "user"))}

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/preview")
    def preview_index():
        items = [
            "index",
            "login",
            "admin",
            "admin_users",
            "task",
            "folder",
            "player",
            "access_denied",
        ]
        links = [
            {
                "name": name,
                "url": url_for("preview_template", template_key=name),
            }
            for name in items
        ]
        return jsonify({
            "message": "Template preview endpoints",
            "example": "/preview/task?variant=downloading",
            "as_user_help": "Use ?as=admin or ?as=user",
            "templates": links,
        })

    @app.get("/preview/<template_key>")
    def preview_template(template_key):
        template_map = {
            "index": "index.html",
            "login": "login.html",
            "admin": "admin.html",
            "admin_users": "admin_users.html",
            "task": "task.html",
            "folder": "folder.html",
            "player": "player.html",
            "access_denied": "access_denied.html",
            "base": "base.html",
        }

        template_name = template_map.get(template_key, template_key)
        if not template_name.endswith(".html"):
            template_name = f"{template_name}.html"

        if not (Path(app.template_folder) / template_name).exists():
            return jsonify({"error": f"Template not found: {template_name}"}), 404

        variant = request.args.get("variant", "waiting").lower()
        context = _template_context(template_name, variant)
        return render_template(template_name, **context)

    @app.get("/login")
    def login():
        return redirect(url_for("preview_template", template_key="login", **request.args))

    @app.get("/logout")
    def logout():
        flash("Preview logout", "ok")
        return redirect(url_for("preview_template", template_key="index", **request.args))

    @app.get("/admin")
    def admin_page():
        return redirect(url_for("preview_template", template_key="admin", **request.args))

    @app.get("/admin/users")
    def admin_users_page():
        return redirect(url_for("preview_template", template_key="admin_users", **request.args))

    @app.post("/admin/users/create")
    def create_user_route():
        flash("Preview: create user action", "success")
        return redirect(url_for("admin_users_page", **request.args))

    @app.post("/admin/users/<int:user_id>/toggle-admin")
    def toggle_admin_route(user_id):
        flash(f"Preview: toggled admin for user {user_id}", "success")
        return redirect(url_for("admin_users_page", **request.args))

    @app.post("/admin/users/<int:user_id>/delete")
    def delete_user_route(user_id):
        flash(f"Preview: deleted user {user_id}", "warning")
        return redirect(url_for("admin_users_page", **request.args))

    @app.post("/tasks/new")
    def create_task():
        flash("Preview: task created", "ok")
        return redirect(url_for("preview_template", template_key="task", variant="downloading"))

    @app.get("/tasks/<task_id>")
    def task_view(task_id):
        _ = task_id
        return redirect(url_for("preview_template", template_key="task", **request.args))

    @app.post("/tasks/<task_id>/select")
    def task_select(task_id):
        _ = task_id
        flash("Preview: files selected", "ok")
        return redirect(url_for("preview_template", template_key="task", variant="downloading"))

    @app.post("/tasks/<task_id>/cancel")
    def task_cancel(task_id):
        _ = task_id
        flash("Preview: task canceled", "warning")
        return redirect(url_for("preview_template", template_key="task", variant="ready"))

    @app.post("/tasks/<task_id>/delete")
    def task_delete(task_id):
        _ = task_id
        flash("Preview: task deleted", "error")
        return redirect(url_for("preview_template", template_key="index", **request.args))

    @app.get("/d/<task_id>/")
    def list_folder(task_id):
        _ = task_id
        return redirect(url_for("preview_template", template_key="folder", **request.args))

    @app.get("/d/<task_id>/raw/<path:relpath>")
    def raw_file(task_id, relpath):
        _ = (task_id, relpath)
        return ("Preview only: no real file stream", 200, {"Content-Type": "text/plain; charset=utf-8"})

    @app.get("/d/<task_id>/play/<path:relpath>")
    def play_video(task_id, relpath):
        _ = (task_id, relpath)
        return redirect(url_for("preview_template", template_key="player", **request.args))

    @app.get("/mock/video.mp4")
    def mock_video():
        return ("", 204)

    return app


app = create_preview_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5055, debug=True)
