# app.py
from __future__ import annotations

import os  # <-- must come before dotenv uses os.path
# Load .env BEFORE importing modules that read env at import time
try:
    from dotenv import load_dotenv, find_dotenv
    load_dotenv(find_dotenv() or os.path.join(os.path.dirname(__file__), ".env"), override=False)
except Exception:
    pass

import time, json, uuid
from datetime import datetime
from flask import Flask, render_template, request, jsonify, Response, make_response, send_from_directory, redirect

from models import Base, engine, SessionLocal, Job
from alldebrid import AllDebrid as ADClient
from job_manager import JobManager
from share_routes import share_bp, start_cleanup_worker
from bus import bus  # uses env-loaded REDIS_URL if set

# --- paths ---
BASE_DIR      = os.path.abspath(os.path.dirname(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR    = os.path.join(BASE_DIR, "static")

# Flask (now with template + static dirs)
app = Flask(__name__, template_folder=TEMPLATES_DIR, static_folder=STATIC_DIR, static_url_path="/static")
app.register_blueprint(share_bp)

# ------------- Config -------------
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "9732"))
TEMP_DIR = os.getenv("TEMP_DIR", "/share/.tmp")
MAX_SIZE = int(os.getenv("MAX_SIZE", str(100 * 1024 * 1024 * 1024)))
MAX_CONC = int(os.getenv("MAX_CONC", "5"))
ENABLE_BG_CLEANUP = os.getenv("ENABLE_BG_CLEANUP", "1") == "1"

os.makedirs(TEMP_DIR, exist_ok=True)

# DB init
Base.metadata.create_all(bind=engine)

# AllDebrid
API_KEY = os.getenv("ALLDEBRID_API_KEY")
if not API_KEY:
    raise RuntimeError("ALLDEBRID_API_KEY not set")
ad = ADClient(apikey=API_KEY)  # note: 'apikey' param

# Job manager
jm = JobManager(ad=ad, temp_dir=TEMP_DIR, max_size=MAX_SIZE, max_conc=MAX_CONC)

def _purge_temp(dirpath, max_age_hours=12):
    cutoff = time.time() - max_age_hours*3600
    try:
        for n in os.listdir(dirpath):
            p = os.path.join(dirpath, n)
            try:
                if os.path.isfile(p) and os.path.getmtime(p) < cutoff:
                    os.remove(p)
            except Exception:
                pass
    except FileNotFoundError:
        pass

_purge_temp(TEMP_DIR, int(os.getenv("TEMP_MAX_AGE_H", "12")))

# Cleanup worker
if ENABLE_BG_CLEANUP:
    start_cleanup_worker(interval_minutes=30)

# ------------- Routes -------------

@app.get("/")
def index():
    return render_template("index.html")


@app.get("/jobs")
def list_jobs():
    limit = int(request.args.get("limit", 5))
    with SessionLocal() as db:
        rows = db.query(Job).order_by(Job.created_at.desc()).limit(limit).all()
        items = []
        for r in rows:
            items.append({
                "id": r.id,
                "status": r.status,
                "error": r.error,
                "created_at": str(r.created_at),
                "updated_at": str(r.updated_at),
                "public": {
                    "web": getattr(r, "sharry_public_web", None),
                    "pid": getattr(r, "sharry_share_id", None)
                } if r.status == "done" else None
            })
    return jsonify({"items": items})

@app.post("/pref")
def save_pref():
    # currently just echoes; you persist client-side
    return jsonify({"ok": True})

@app.post("/job")
def create_job():
    kind = request.form.get("kind")
    include = request.form.get("includeTrackers", "false").lower() == "true"
    cid = request.cookies.get("cid") or str(uuid.uuid4())

    if kind == "magnet":
        magnet = (request.form.get("magnet") or "").strip()
        if not magnet:
            return jsonify({"ok": False, "error": "missing magnet"}), 400
        job_id = jm.create_job("magnet", magnet, include, client_id=cid)

    elif kind == "torrent":
        f = request.files.get("torrent")
        if not f:
            return jsonify({"ok": False, "error": "missing torrent"}), 400
        path = os.path.join(TEMP_DIR, f"{uuid.uuid4()}_{f.filename}")
        f.save(path)
        job_id = jm.create_job("torrent", path, include, client_id=cid)

    elif kind == "url":
        urls = (request.form.get("urls") or "").strip()
        if not urls:
            return jsonify({"ok": False, "error": "missing urls"}), 400
        job_id = jm.create_job("url", urls, include, client_id=cid)

    else:
        return jsonify({"ok": False, "error": "invalid kind"}), 400

    resp = jsonify({"ok": True, "jobId": job_id})
    # set owner cookie if missing (scoped to this app)
    out = make_response(resp)
    out.set_cookie("cid", cid, httponly=False, samesite="Lax", max_age=60*60*24*365)
    return out

@app.post("/job/<job_id>/cancel")
def cancel_job(job_id):
    # owner gate
    with SessionLocal() as db:
        row = db.get(Job, job_id)
        if not row:
            return ("", 404)
        owner = (row.client_id or "").strip()
        if owner and request.cookies.get("cid") != owner:
            return ("", 404)
    jm.request_cancel(job_id)
    return jsonify({"ok": True})

@app.get("/events/<job_id>")
def sse(job_id):
    # owner gate
    with SessionLocal() as db:
        row = db.get(Job, job_id)
        if not row:
            return ("", 404)
        owner = (row.client_id or "").strip()
        if owner and request.cookies.get("cid") != owner:
            return ("", 404)

    def gen():
        for chunk in bus.sse(job_id):
            yield chunk

    return Response(gen(), mimetype="text/event-stream")

@app.get("/healthz")
def healthz():
    try:
        with SessionLocal() as db:
            db.execute("SELECT 1")
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    # IMPORTANT for dev: no reloader/multiprocess
    app.run(host=HOST, port=PORT, debug=False, use_reloader=False)
