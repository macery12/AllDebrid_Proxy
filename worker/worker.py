
import os, time, uuid, threading, logging, traceback, urllib.error, json
from sqlalchemy import select
from app.config import settings
from app.db import SessionLocal
from app.models import Task, TaskFile, UserStats
from app.utils import ensure_task_dirs, append_log, write_metadata
from worker.scheduler import publish, can_start_task, count_active_and_queued
from worker.downloader import aria2_add_uri  # RPC enqueue (non-blocking)

# Optional RPC accessor for startup handshake (if present in your downloader.py)
try:
    from worker.downloader import get_aria2
except Exception:
    get_aria2 = None

try:
    from app.providers.alldebrid import AllDebrid
except Exception:
    AllDebrid = None

# -------------------- Logging --------------------
DEBUG = bool(int(os.getenv("DEBUG_DOWNLOADS", "0")))
LOG_LEVEL = logging.DEBUG if DEBUG else logging.INFO
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("worker")

def _jdump(obj):
    try:
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return str(obj)

def _log(task_id: str, level: str, event: str, **fields):
    # to file (existing) + to STDOUT (docker logs)
    try:
        base, _ = ensure_task_dirs(settings.STORAGE_ROOT, task_id if task_id else "no-task")
        payload = {"level": level, "event": event}
        payload.update(fields)
        append_log(base, payload)
    except Exception:
        pass
    msg = {"task": task_id, "event": event}
    msg.update(fields)
    if level == "debug":
        log.debug(_jdump(msg))
    elif level == "warning":
        log.warning(_jdump(msg))
    elif level == "error":
        log.error(_jdump(msg))
    else:
        log.info(_jdump(msg))

# -------------------- AllDebrid client --------------------
def get_client():
    if AllDebrid is None:
        raise RuntimeError("AllDebrid client not found. Ensure app/providers/alldebrid.py exists.")
    return AllDebrid(api_key=settings.ALLDEBRID_API_KEY, agent=settings.ALLDEBRID_AGENT)

# -------------------- Filesystem-based progress monitor --------------------
_monitor_started = False
def _start_monitor_once():
    global _monitor_started
    if _monitor_started:
        return
    _monitor_started = True
    threading.Thread(target=_progress_monitor_loop, daemon=True).start()
    _log("", "info", "progress_monitor_started")

def _progress_monitor_loop():
    while True:
        try:
            with SessionLocal() as s:
                q = select(TaskFile).where(TaskFile.state == "downloading")
                files = s.execute(q).scalars().all()
                for f in files:
                    out_path = os.path.join(settings.STORAGE_ROOT, f.task_id, "files", f.name)
                    tmp_path = f"{out_path}.aria2"
                    size_path = out_path if os.path.exists(out_path) else tmp_path
                    cur = os.path.getsize(size_path) if os.path.exists(size_path) else 0
                    total = f.size_bytes or 0

                    if cur != (f.bytes_downloaded or 0):
                        f.bytes_downloaded = cur
                        s.commit()
                        publish(f.task_id, {"type":"file.progress","fileId":f.id,"bytesDownloaded":cur,"total":total})
                        if DEBUG:
                            _log(f.task_id, "debug", "file_progress", fileId=f.id, downloaded=cur, total=total, path=size_path)

                    # done = final file exists AND aria2 control file does NOT exist AND (unknown size OR size >= expected)
                    if os.path.exists(out_path) and not os.path.exists(tmp_path) and ((total == 0) or (cur >= total)):
                        if f.state != "done":
                            f.state = "done"
                            f.local_path = out_path
                            
                            # Update user stats when file completes
                            task = s.get(Task, f.task_id)
                            if task and task.user_id:
                                stats = s.query(UserStats).filter(UserStats.user_id == task.user_id).first()
                                if stats:
                                    stats.total_downloads += 1
                                    stats.total_bytes_downloaded += (f.bytes_downloaded or 0)
                            
                            s.commit()
                            publish(f.task_id, {"type":"file.done","fileId":f.id,"localPath":f.local_path})
                            _log(f.task_id, "info", "file_done", fileId=f.id, path=f.local_path)
                    else:
                        if DEBUG and not os.path.exists(out_path) and not os.path.exists(tmp_path):
                            _log(f.task_id, "debug", "no_progress_file_missing", fileId=f.id, expected=out_path, tmp=tmp_path)
        except Exception as e:
            _log("", "error", "progress_monitor_error", err=str(e), tb=traceback.format_exc())
        time.sleep(1)

# -------------------- Resolve + start logic (matches your old flow) --------------------
def resolve_task(session, task: Task, client):
    base, files_dir = ensure_task_dirs(settings.STORAGE_ROOT, task.id)

    if not task.provider_ref:
        _log(task.id, "info", "ad_upload_begin")
        magnet_id = client.upload_magnets([task.source])
        if isinstance(magnet_id, (list, tuple)):
            magnet_id = magnet_id[0]
        task.provider_ref = str(magnet_id)
        session.commit()
        _log(task.id, "info", "ad_upload_ok", provider_ref=task.provider_ref)

    # Mark 'resolving'
    task.status = "resolving"
    session.commit()
    publish(task.id, {"type":"state","status":"resolving"})
    _log(task.id, "info", "task_resolving")

    # Poll AllDebrid for files
    for _ in range(240):  # ~20 minutes at 5s
        status = client.get_magnet_status(task.provider_ref)
        if DEBUG:
            _log(task.id, "debug", "ad_status_raw", payload=status.get("raw"))

        files = status.get("files") or []
        if files:
            existing = {f.index: f for f in session.execute(
                select(TaskFile).where(TaskFile.task_id == task.id)
            ).scalars().all()}

            listed_payload = []
            for i, fi in enumerate(files):
                name = fi.get("name") or f"file_{i}"
                size = int(fi.get("size") or 0)
                tf = existing.get(i)
                if not tf:
                    tf = TaskFile(
                        id=str(uuid.uuid4()), task_id=task.id,
                        index=i, name=name, size_bytes=size, state="listed"
                    )
                    session.add(tf)
                    session.commit()
                listed_payload.append({"fileId": tf.id, "index": i, "name": name, "size": size, "state":"listed"})

            publish(task.id, {"type":"files.listed", "files": listed_payload})
            _log(task.id, "info", "files_listed", count=len(listed_payload))
            break

        time.sleep(5)
    else:
        task.status = "failed"
        session.commit()
        publish(task.id, {"type":"state","status":"failed","reason":"timeout_no_files"})
        _log(task.id, "error", "resolve_timeout_no_files")
        return

    if task.mode == "select":
        task.status = "waiting_selection"
        session.commit()
        publish(task.id, {"type":"state","status":"waiting_selection","timeoutMinutes":15})
        _log(task.id, "info", "task_waiting_selection")
        return

    # auto mode → mark listed as selected
    session.execute(TaskFile.__table__.update()
                    .where(TaskFile.task_id == task.id)
                    .values(state="selected"))
    task.status = "downloading"
    session.commit()
    publish(task.id, {"type":"state","status":"downloading"})
    _log(task.id, "info", "task_downloading")

def _dir_writable(path: str) -> bool:
    try:
        os.makedirs(path, exist_ok=True)
        test = os.path.join(path, ".write_test")
        with open(test, "wb") as f:
            f.write(b"x")
        os.remove(test)
        return True
    except Exception:
        return False

def start_next_files(session, task: Task, client):
    _start_monitor_once()

    active, queued = count_active_and_queued(session, task)
    to_start = min(max(settings.PER_TASK_MAX_ACTIVE - active, 0), settings.PER_TASK_MAX_QUEUED)
    if to_start <= 0:
        if DEBUG:
            _log(task.id, "debug", "no_slots", active=active, queued=queued, per_task=settings.PER_TASK_MAX_ACTIVE)
        return

    # Only start 'selected' files (auto path already selected everything)
    candidates = session.execute(select(TaskFile).where(
        TaskFile.task_id == task.id,
        TaskFile.state == "selected"
    ).order_by(TaskFile.index)).scalars().all()

    out_dir = os.path.join(settings.STORAGE_ROOT, task.id, "files")
    if not _dir_writable(out_dir):
        publish(task.id, {"type":"state","status":"failed","reason":"storage_not_writable"})
        task.status = "failed"
        session.commit()
        _log(task.id, "error", "storage_not_writable", dir=out_dir)
        return

    started = 0
    for f in candidates:
        if started >= to_start:
            break

        # 1) Unlock HTTPS link
        try:
            url = client.download_link(task.provider_ref, f.index)
            if not url or not url.startswith("http"):
                raise RuntimeError("unlock returned no http(s) link")
            if DEBUG:
                _log(task.id, "info", "unlock_ok", fileId=f.id, index=f.index)
        except Exception as e:
            f.state = "failed"
            session.commit()
            publish(task.id, {"type":"file.failed","fileId":f.id,"reason":f"unlock_failed: {e}"})
            _log(task.id, "error", "unlock_failed", fileId=f.id, index=f.index, err=str(e), tb=traceback.format_exc())
            continue

        # 2) Flip to downloading BEFORE enqueue
        f.unlocked_url = url
        f.state = "downloading"
        session.commit()
        publish(task.id, {"type":"file.state","fileId":f.id,"state":"downloading"})
        if DEBUG:
            _log(task.id, "debug", "enqueue_pre", fileId=f.id, dir=out_dir, name=f.name, rpc=os.getenv("ARIA2_RPC_URL"))

        # 3) Enqueue in aria2 RPC
        try:
            aria2_add_uri(url, out_dir, f.name, splits=settings.ARIA2_SPLITS)
            started += 1
            if DEBUG:
                _log(task.id, "info", "enqueue_ok", fileId=f.id)
        except urllib.error.HTTPError as e:
            f.state = "failed"
            session.commit()
            reason = f"enqueue_failed_http: {e.code} {e.reason}"
            publish(task.id, {"type":"file.failed","fileId":f.id,"reason":reason})
            _log(task.id, "error", "enqueue_failed_http", fileId=f.id, code=e.code, reason=e.reason, url=os.getenv("ARIA2_RPC_URL"))
            continue
        except Exception as e:
            f.state = "failed"
            session.commit()
            publish(task.id, {"type":"file.failed","fileId":f.id,"reason":f"enqueue_failed: {e}"})
            _log(task.id, "error", "enqueue_failed", fileId=f.id, err=str(e), tb=traceback.format_exc(), url=os.getenv("ARIA2_RPC_URL"))
            continue

    # Only mark ready if ALL files are done
    files = session.execute(select(TaskFile).where(TaskFile.task_id == task.id)).scalars().all()
    if files and all((x.state or "").lower() == "done" for x in files):
        task.status = "ready"
        session.commit()
        publish(task.id, {"type":"state","status":"ready"})
        _log(task.id, "info", "task_ready_all_done", total=len(files))

def worker_loop():
    _start_monitor_once()
    client = get_client()

    # One-time aria2 RPC version check
    if get_aria2:
        try:
            rpc = get_aria2()
            ver = rpc._call("getVersion", [])
            _log("", "info", "aria2_rpc_ok", url=os.getenv("ARIA2_RPC_URL"), version=ver)
        except Exception as e:
            _log("", "error", "aria2_rpc_fail", url=os.getenv("ARIA2_RPC_URL"), error=str(e), tb=traceback.format_exc())

    while True:
        with SessionLocal() as s:
            # 1) Resolve new queued tasks
            queued = s.execute(select(Task).where(Task.status == "queued")).scalars().all()
            for t in queued:
                try:
                    resolve_task(s, t, client)
                except Exception as e:
                    _log(t.id, "error", "resolve_exception", err=str(e), tb=traceback.format_exc())

            # 2) Start downloads for active tasks
            active = s.execute(select(Task).where(Task.status.in_(("downloading","waiting_selection")))).scalars().all()
            for t in active:
                if t.status == "waiting_selection":
                    continue
                if can_start_task(s, t):
                    try:
                        start_next_files(s, t, client)
                    except Exception as e:
                        _log(t.id, "error", "start_next_exception", err=str(e), tb=traceback.format_exc())
        time.sleep(2)

if __name__ == "__main__":
    worker_loop()
