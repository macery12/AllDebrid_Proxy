# share_routes.py
from __future__ import annotations
import os, re, time, shutil, threading, subprocess
from datetime import datetime
from typing import Tuple
from flask import Blueprint, abort, send_from_directory, render_template_string, url_for, request, Response

SHARE_ROOT = os.getenv("SHARE_ROOT", "/share").rstrip("/")
RETENTION_DAYS = int(os.getenv("SHARE_RETENTION_DAYS", "7"))
LISTING_PAGE_TITLE = os.getenv("SHARE_LISTING_TITLE", "Share")
USE_ACCEL = os.getenv("USE_ACCEL", "0") == "1"
ACCEL_PREFIX = os.getenv("ACCEL_PREFIX", "/_share").rstrip("/")
PUBLIC_BASE = os.getenv("SHARE_PUBLIC_BASE", "").rstrip("/")

share_bp = Blueprint("share", __name__)

_ALLOWED_ID = re.compile(r"^[A-Za-z0-9._-]+(?:-\d+)?(?:-\d+)?$")

def _safe_join_root(share_id: str, *parts: str) -> Tuple[str, str]:
    if not _ALLOWED_ID.match(share_id): abort(404)
    base = os.path.join(SHARE_ROOT, share_id)
    path = os.path.join(base, *(parts or ("",)))
    norm = os.path.normpath(path)
    if not norm.startswith(base): abort(404)
    rel = os.path.relpath(norm, base);  rel = "" if rel == "." else rel
    return norm, rel

def _iter_dir(path: str):
    try:
        entries = list(os.scandir(path))
    except FileNotFoundError:
        abort(404)
    dirs, files = [], []
    for e in entries:
        if e.name.startswith("."):  # hide dotfiles
            continue
        if e.is_dir(follow_symlinks=False):
            dirs.append((e.name, True, 0))
        elif e.is_file(follow_symlinks=False):
            try: sz = e.stat().st_size
            except Exception: sz = 0
            files.append((e.name, False, sz))
    dirs.sort(key=lambda x: x[0].lower())
    files.sort(key=lambda x: x[0].lower())
    return dirs + files

def _human(n: int) -> str:
    k = 1024; units = ["B","KB","MB","GB","TB"]; i=0; v=float(n)
    while v>=k and i<len(units)-1: v/=k; i+=1
    return f"{int(v) if (i==0 or v>=10) else f'{v:.1f}'} {units[i]}"

def _dir_newest_mtime(path: str) -> float:
    newest = 0.0
    try:
        for root, dirs, files in os.walk(path):
            for name in files:
                try:
                    mt = os.stat(os.path.join(root, name)).st_mtime
                    if mt > newest: newest = mt
                except Exception: pass
        if newest == 0.0: newest = os.stat(path).st_mtime
    except FileNotFoundError:
        return 0.0
    return newest

_LISTING_TMPL = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>{{ title }}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <link href="/static/styles.css" rel="stylesheet" />
  <style>
    .wrap { max-width: 980px }
    .breadcrumbs { color:#8892a6; margin-bottom:10px }
    .topbar { display:flex; justify-content:space-between; align-items:center; margin-bottom: 8px; gap: 10px;}
    .files-actions a.btn, .files-actions button.btn {
      background:#2b3753; border:1px solid #334264; color:#cfe2ff; padding:6px 10px;
      border-radius:8px; text-decoration:none; cursor:pointer;
    }
    table.files { width:100%; border-collapse: collapse; }
    .files th, .files td { padding:8px 10px; border-bottom:1px solid #232a3b; }
    .files th { text-align:left; color:#9fb0cf; font-weight:600; }
    .files td.size { width:140px; text-align:right; color:#8892a6; }
    .files td.name a { color:#cfe2ff; text-decoration:none; }
    .files td.name a:hover { text-decoration:underline; }
  </style>
</head>
<body class="theme">
  <header class="header">
    <div class="brand">{{ heading }}</div>
    <div class="badge">Local Share</div>
  </header>
  <main class="wrap">
    <div class="breadcrumbs">
      <a href="/">Home</a> / <span>{{ share_id }}</span>{% if subpath %} / <span>{{ subpath }}</span>{% endif %}
    </div>

    <div class="topbar">
      <div></div>
      <div class="files-actions">
        {% if can_zip %}
          <a class="btn" href="{{ zip_href }}">Download all (.tar.gz)</a>
          <a class="btn" href="{{ links_href }}" target="_blank">Open links.txt</a>
          <button class="btn" id="copyLinksBtn">Copy all links</button>
        {% endif %}
      </div>
    </div>

    {% if entries %}
    <table class="files">
      <thead>
        <tr><th>Name</th><th class="size">Size</th></tr>
      </thead>
      <tbody>
        {% if up_link %}
          <tr>
            <td class="name">📁 <a href="{{ up_link }}">..</a></td>
            <td class="size">—</td>
          </tr>
        {% endif %}
        {% for name, is_dir, size, href in entries %}
          <tr>
            <td class="name">{{ "📁" if is_dir else "📄" }} <a href="{{ href }}">{{ name }}</a></td>
            <td class="size">{{ "—" if is_dir else size }}</td>
          </tr>
        {% endfor %}
      </tbody>
    </table>
    {% else %}
      <p>No files.</p>
    {% endif %}
  </main>

<script>
document.addEventListener('click', async (e)=>{
  if (e.target && e.target.id === 'copyLinksBtn'){
    try{
      const res = await fetch('{{ links_href }}');
      const txt = await res.text();
      await navigator.clipboard.writeText(txt);
      e.target.textContent = 'Copied!';
      setTimeout(()=>{ e.target.textContent = 'Copy all links'; }, 1500);
    }catch(err){
      alert('Failed to copy links');
    }
  }
});
</script>
</body>
</html>
"""

@share_bp.get("/d/<share_id>/")
@share_bp.get("/d/<share_id>/<path:subpath>/")
def list_or_download(share_id: str, subpath: str | None = None):
    abs_path, rel = _safe_join_root(share_id, (subpath or ""))

    if os.path.isfile(abs_path):
        if USE_ACCEL:
            accel_target = f"{ACCEL_PREFIX}/{share_id}/{rel}".replace("//", "/")
            resp = Response("", 200)
            resp.headers["X-Accel-Redirect"] = accel_target
            return resp
        directory = os.path.dirname(abs_path)
        filename = os.path.basename(abs_path)
        return send_from_directory(directory, filename, as_attachment=False)

    if not os.path.isdir(abs_path):
        abort(404)

    entries = []
    for name, is_dir, sz in _iter_dir(abs_path):
        child = name if not rel else f"{rel}/{name}"
        href = url_for(".list_or_download", share_id=share_id, subpath=child) + ("/" if is_dir else "")
        entries.append((name, is_dir, ("" if is_dir else _human(sz)), href))

    up_link = None
    if rel:
        parent = rel.rsplit("/", 1)[0] if "/" in rel else ""
        up_link = url_for(".list_or_download", share_id=share_id, subpath=parent) + ("/" if parent else "")

    can_zip = (rel == "") and len(entries) > 0
    zip_href = url_for(".download_all_tar", share_id=share_id)
    links_href = url_for(".links_txt", share_id=share_id)

    return render_template_string(_LISTING_TMPL,
                                  title=f"{LISTING_PAGE_TITLE} – {share_id}",
                                  heading=LISTING_PAGE_TITLE,
                                  share_id=share_id,
                                  subpath=rel,
                                  entries=entries,
                                  up_link=up_link,
                                  can_zip=can_zip,
                                  zip_href=zip_href,
                                  links_href=links_href)

@share_bp.get("/d/<share_id>.tar.gz")
def download_all_tar(share_id: str):
    abs_path, rel = _safe_join_root(share_id, "")
    if not os.path.isdir(abs_path): abort(404)

    def generate():
        proc = subprocess.Popen(["tar", "-czf", "-", "-C", abs_path, "."], stdout=subprocess.PIPE)
        try:
            while True:
                chunk = proc.stdout.read(64 * 1024)
                if not chunk: break
                yield chunk
        finally:
            try: proc.stdout.close()
            except Exception: pass
            proc.wait()

    headers = {
        "Content-Disposition": f'attachment; filename="{share_id}.tar.gz"',
        "X-Accel-Buffering": "no",
        "Cache-Control": "no-cache",
    }
    return Response(generate(), headers=headers, mimetype="application/gzip")

@share_bp.get("/d/<share_id>/links.txt")
def links_txt(share_id: str):
    """Plain text list of absolute file URLs (recursive)."""
    root, rel = _safe_join_root(share_id, "")
    if not os.path.isdir(root): abort(404)

    # Build base URL
    base = PUBLIC_BASE or (request.host_url.rstrip("/"))
    out_lines = []

    for dirpath, dirnames, filenames in os.walk(root):
        # Skip dot dirs
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fn in sorted(filenames, key=str.lower):
            if fn.startswith("."): continue
            absf = os.path.join(dirpath, fn)
            relf = os.path.relpath(absf, root)
            url = f"{base}/d/{share_id}/{relf}".replace("\\", "/")
            out_lines.append(url)

    body = "\n".join(out_lines) + ("\n" if out_lines else "")
    return Response(body, mimetype="text/plain; charset=utf-8")


# ---------- (optional) cleanup loop unchanged ----------
def _dir_newest_mtime(path: str) -> float:
    newest = 0.0
    try:
        for root, dirs, files in os.walk(path):
            for name in files:
                try:
                    mt = os.stat(os.path.join(root, name)).st_mtime
                    if mt > newest: newest = mt
                except Exception: pass
        if newest == 0.0: newest = os.stat(path).st_mtime
    except FileNotFoundError:
        return 0.0
    return newest

def _cleanup_once(root: str = SHARE_ROOT, retention_days: int = RETENTION_DAYS) -> int:
    now = time.time()
    cutoff = now - retention_days * 24 * 3600
    deleted = 0
    try:
        names = os.listdir(root)
    except FileNotFoundError:
        return 0
    for name in names:
        if not _ALLOWED_ID.match(name): continue
        path = os.path.join(root, name)
        try:
            if not os.path.isdir(path): continue
            # delete if nothing touched in last N days
            newest = _dir_newest_mtime(path)
            if newest and newest < cutoff:
                if os.path.commonpath([os.path.realpath(path), os.path.realpath(root)]) != os.path.realpath(root):
                    continue
                shutil.rmtree(path); deleted += 1
        except Exception:
            pass
    return deleted

def _cleanup_loop(stop_evt: threading.Event, interval_minutes: int, root: str, retention_days: int):
    while not stop_evt.wait(timeout=interval_minutes * 60):
        _cleanup_once(root, retention_days)

_cleanup_stop_evt = None
def start_cleanup_worker(interval_minutes: int = 30):
    global _cleanup_stop_evt
    if _cleanup_stop_evt is not None: return
    _cleanup_stop_evt = threading.Event()
    t = threading.Thread(target=_cleanup_loop,
                         args=(_cleanup_stop_evt, interval_minutes, SHARE_ROOT, RETENTION_DAYS),
                         name="share-cleanup", daemon=True)
    t.start()
