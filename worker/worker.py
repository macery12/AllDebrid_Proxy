
import os, time, uuid, threading, logging, traceback, urllib.error, json
from sqlalchemy import select
from app.config import settings
from app.db import SessionLocal
from app.models import Task, TaskFile, UserStats
from app.utils import ensure_task_dirs, append_log, write_metadata
from app.constants import TaskStatus, FileState, EventType, Limits, LogLevel
from app.logging_config import setup_logging, get_logger, log_task_event, log_worker_event, log_error
from app.validation import validate_file_name
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
logger = setup_logging(
    level="DEBUG" if DEBUG else "INFO",
    structured=bool(int(os.getenv("STRUCTURED_LOGS", "0"))),
    logger_name="worker"
)

def _jdump(obj):
    """Safely dump object to JSON string"""
    try:
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return str(obj)

def _log(task_id: str, level: str, event: str, **fields):
    """
    Log event to both file and stdout.
    
    Args:
        task_id: Task identifier (empty string for worker-level events)
        level: Log level
        event: Event name
        **fields: Additional fields to log
    """
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
    
    # Use proper logging levels
    if level == LogLevel.DEBUG:
        logger.debug(_jdump(msg), extra={"task_id": task_id})
    elif level == LogLevel.WARNING:
        logger.warning(_jdump(msg), extra={"task_id": task_id})
    elif level == LogLevel.ERROR:
        logger.error(_jdump(msg), extra={"task_id": task_id})
    else:
        logger.info(_jdump(msg), extra={"task_id": task_id})

# -------------------- AllDebrid client --------------------
def get_client():
    """
    Get AllDebrid client instance.
    
    Returns:
        AllDebrid client
        
    Raises:
        RuntimeError: If AllDebrid client not available
    """
    if AllDebrid is None:
        raise RuntimeError("AllDebrid client not found. Ensure app/providers/alldebrid.py exists.")
    return AllDebrid(api_key=settings.ALLDEBRID_API_KEY, agent=settings.ALLDEBRID_AGENT)

# -------------------- Filesystem-based progress monitor --------------------
_monitor_started = False

def _start_monitor_once():
    """Start the progress monitor thread if not already started"""
    global _monitor_started
    if _monitor_started:
        return
    _monitor_started = True
    threading.Thread(target=_progress_monitor_loop, daemon=True).start()
    _log("", LogLevel.INFO, "progress_monitor_started")

def _progress_monitor_loop():
    """
    Monitor download progress by checking file sizes.
    Updates database and publishes progress events.
    """
    while True:
        try:
            with SessionLocal() as s:
                q = select(TaskFile).where(TaskFile.state == FileState.DOWNLOADING)
                files = s.execute(q).scalars().all()
                for f in files:
                    # Validate file name to prevent path traversal
                    try:
                        validate_file_name(f.name)
                    except Exception as e:
                        _log(f.task_id, LogLevel.ERROR, "invalid_file_name", 
                             fileId=f.id, name=f.name, error=str(e))
                        continue
                    
                    out_path = os.path.join(settings.STORAGE_ROOT, f.task_id, "files", f.name)
                    tmp_path = f"{out_path}.aria2"
                    size_path = out_path if os.path.exists(out_path) else tmp_path
                    cur = os.path.getsize(size_path) if os.path.exists(size_path) else 0
                    total = f.size_bytes or 0

                    if cur != (f.bytes_downloaded or 0):
                        f.bytes_downloaded = cur
                        s.commit()
                        publish(f.task_id, {
                            "type": EventType.FILE_PROGRESS,
                            "fileId": f.id,
                            "bytesDownloaded": cur,
                            "total": total
                        })
                        if DEBUG:
                            _log(f.task_id, LogLevel.DEBUG, "file_progress", 
                                 fileId=f.id, downloaded=cur, total=total, path=size_path)

                    # done = final file exists AND aria2 control file does NOT exist AND (unknown size OR size >= expected)
                    if os.path.exists(out_path) and not os.path.exists(tmp_path) and ((total == 0) or (cur >= total)):
                        if f.state != FileState.DONE:
                            f.state = FileState.DONE
                            f.local_path = out_path
                            
                            # Update user stats when file completes
                            task = s.get(Task, f.task_id)
                            if task and task.user_id:
                                stats = s.query(UserStats).filter(UserStats.user_id == task.user_id).first()
                                if stats:
                                    stats.total_downloads += 1
                                    stats.total_bytes_downloaded += (f.bytes_downloaded or 0)
                            
                            s.commit()
                            publish(f.task_id, {
                                "type": EventType.FILE_DONE,
                                "fileId": f.id,
                                "localPath": f.local_path
                            })
                            _log(f.task_id, LogLevel.INFO, "file_done", fileId=f.id, path=f.local_path)
                    else:
                        if DEBUG and not os.path.exists(out_path) and not os.path.exists(tmp_path):
                            _log(f.task_id, LogLevel.DEBUG, "no_progress_file_missing", 
                                 fileId=f.id, expected=out_path, tmp=tmp_path)
        except Exception as e:
            _log("", LogLevel.ERROR, "progress_monitor_error", err=str(e), tb=traceback.format_exc())
        
        time.sleep(Limits.PROGRESS_MONITOR_INTERVAL)

# -------------------- Resolve + start logic (matches your old flow) --------------------
def resolve_task(session, task: Task, client):
    # Create task directories and initialize metadata files
    # Args: session - DB session, task - Task model, client - AllDebrid client
    base, files_dir = ensure_task_dirs(settings.STORAGE_ROOT, task.id)

    if not task.provider_ref:
        _log(task.id, LogLevel.INFO, "ad_upload_begin")
        magnet_id = client.upload_magnets([task.source])
        if isinstance(magnet_id, (list, tuple)):
            magnet_id = magnet_id[0]
        task.provider_ref = str(magnet_id)
        session.commit()
        _log(task.id, LogLevel.INFO, "ad_upload_ok", provider_ref=task.provider_ref)

    # Mark task as resolving
    task.status = TaskStatus.RESOLVING
    session.commit()
    publish(task.id, {"type": EventType.STATE, "status": TaskStatus.RESOLVING})
    _log(task.id, LogLevel.INFO, "task_resolving")

    # Poll AllDebrid for files (up to ~20 minutes)
    for _ in range(Limits.MAX_RESOLVE_ATTEMPTS):
        status = client.get_magnet_status(task.provider_ref)
        if DEBUG:
            _log(task.id, LogLevel.DEBUG, "ad_status_raw", payload=status.get("raw"))

        files = status.get("files") or []
        if files:
            existing = {f.index: f for f in session.execute(
                select(TaskFile).where(TaskFile.task_id == task.id)
            ).scalars().all()}

            listed_payload = []
            for i, fi in enumerate(files):
                name = fi.get("name") or f"file_{i}"
                # Validate file name for security
                try:
                    validate_file_name(name)
                except Exception as e:
                    _log(task.id, LogLevel.WARNING, "invalid_file_name_skipped", 
                         index=i, name=name, error=str(e))
                    continue
                
                size = int(fi.get("size") or 0)
                tf = existing.get(i)
                if not tf:
                    tf = TaskFile(
                        id=str(uuid.uuid4()), task_id=task.id,
                        index=i, name=name, size_bytes=size, state=FileState.LISTED
                    )
                    session.add(tf)
                    session.commit()
                listed_payload.append({"fileId": tf.id, "index": i, "name": name, "size": size, "state": FileState.LISTED})

            publish(task.id, {"type": EventType.FILES_LISTED, "files": listed_payload})
            _log(task.id, LogLevel.INFO, "files_listed", count=len(listed_payload))
            break

        time.sleep(Limits.RESOLVE_POLL_DELAY)
    else:
        # Timeout: no files found after max attempts
        task.status = TaskStatus.FAILED
        session.commit()
        publish(task.id, {"type": EventType.STATE, "status": TaskStatus.FAILED, "reason": "timeout_no_files"})
        _log(task.id, LogLevel.ERROR, "resolve_timeout_no_files")
        return

    if task.mode == "select":
        # Wait for user to select files
        task.status = TaskStatus.WAITING_SELECTION
        session.commit()
        publish(task.id, {"type": EventType.STATE, "status": TaskStatus.WAITING_SELECTION, "timeoutMinutes": 15})
        _log(task.id, LogLevel.INFO, "task_waiting_selection")
        return

    # Auto mode: mark all listed files as selected
    session.execute(TaskFile.__table__.update()
                    .where(TaskFile.task_id == task.id)
                    .values(state=FileState.SELECTED))
    task.status = TaskStatus.DOWNLOADING
    session.commit()
    publish(task.id, {"type": EventType.STATE, "status": TaskStatus.DOWNLOADING})
    _log(task.id, LogLevel.INFO, "task_downloading")

def _dir_writable(path: str) -> bool:
    # Check if directory is writable by attempting to create and write a test file
    # Args: path - directory path to check
    # Returns: True if writable, False otherwise
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
    # Start downloading next batch of selected files for a task
    # Respects per-task concurrency limits and storage space
    # Args: session - DB session, task - Task model, client - AllDebrid client
    _start_monitor_once()

    active, queued = count_active_and_queued(session, task)
    to_start = min(max(settings.PER_TASK_MAX_ACTIVE - active, 0), settings.PER_TASK_MAX_QUEUED)
    if to_start <= 0:
        if DEBUG:
            _log(task.id, LogLevel.DEBUG, "no_slots", active=active, queued=queued, per_task=settings.PER_TASK_MAX_ACTIVE)
        return

    # Only start 'selected' files (auto path already selected everything)
    candidates = session.execute(select(TaskFile).where(
        TaskFile.task_id == task.id,
        TaskFile.state == FileState.SELECTED
    ).order_by(TaskFile.index)).scalars().all()

    out_dir = os.path.join(settings.STORAGE_ROOT, task.id, "files")
    if not _dir_writable(out_dir):
        publish(task.id, {"type": EventType.STATE, "status": TaskStatus.FAILED, "reason": "storage_not_writable"})
        task.status = TaskStatus.FAILED
        session.commit()
        _log(task.id, LogLevel.ERROR, "storage_not_writable", dir=out_dir)
        return

    started = 0
    for f in candidates:
        if started >= to_start:
            break

        # 1) Unlock HTTPS link from provider
        try:
            url = client.download_link(task.provider_ref, f.index)
            if not url or not url.startswith("http"):
                raise RuntimeError("unlock returned no http(s) link")
            if DEBUG:
                _log(task.id, LogLevel.INFO, "unlock_ok", fileId=f.id, index=f.index)
        except Exception as e:
            f.state = FileState.FAILED
            session.commit()
            publish(task.id, {"type": EventType.FILE_FAILED, "fileId": f.id, "reason": f"unlock_failed: {e}"})
            _log(task.id, LogLevel.ERROR, "unlock_failed", fileId=f.id, index=f.index, err=str(e), tb=traceback.format_exc())
            continue

        # 2) Flip to downloading BEFORE enqueue
        f.unlocked_url = url
        f.state = FileState.DOWNLOADING
        session.commit()
        publish(task.id, {"type": EventType.FILE_STATE, "fileId": f.id, "state": FileState.DOWNLOADING})
        if DEBUG:
            _log(task.id, LogLevel.DEBUG, "enqueue_pre", fileId=f.id, dir=out_dir, name=f.name, rpc=os.getenv("ARIA2_RPC_URL"))

        # 3) Enqueue in aria2 RPC
        try:
            aria2_add_uri(url, out_dir, f.name, splits=settings.ARIA2_SPLITS)
            started += 1
            if DEBUG:
                _log(task.id, LogLevel.INFO, "enqueue_ok", fileId=f.id)
        except urllib.error.HTTPError as e:
            f.state = FileState.FAILED
            session.commit()
            reason = f"enqueue_failed_http: {e.code} {e.reason}"
            publish(task.id, {"type": EventType.FILE_FAILED, "fileId": f.id, "reason": reason})
            _log(task.id, LogLevel.ERROR, "enqueue_failed_http", fileId=f.id, code=e.code, reason=e.reason, url=os.getenv("ARIA2_RPC_URL"))
            continue
        except Exception as e:
            f.state = FileState.FAILED
            session.commit()
            publish(task.id, {"type": EventType.FILE_FAILED, "fileId": f.id, "reason": f"enqueue_failed: {e}"})
            _log(task.id, LogLevel.ERROR, "enqueue_failed", fileId=f.id, err=str(e), tb=traceback.format_exc(), url=os.getenv("ARIA2_RPC_URL"))
            continue

    # Only mark ready if ALL files are done
    files = session.execute(select(TaskFile).where(TaskFile.task_id == task.id)).scalars().all()
    if files and all(x.state == FileState.DONE for x in files):
        task.status = TaskStatus.READY
        session.commit()
        publish(task.id, {"type": EventType.STATE, "status": TaskStatus.READY})
        _log(task.id, LogLevel.INFO, "task_ready_all_done", total=len(files))

def worker_loop():
    # Main worker loop: processes queued tasks and starts downloads
    # Runs continuously, polling database for work
    _start_monitor_once()
    client = get_client()

    # One-time aria2 RPC version check
    if get_aria2:
        try:
            rpc = get_aria2()
            ver = rpc._call("getVersion", [])
            _log("", LogLevel.INFO, "aria2_rpc_ok", url=os.getenv("ARIA2_RPC_URL"), version=ver)
        except Exception as e:
            _log("", LogLevel.ERROR, "aria2_rpc_fail", url=os.getenv("ARIA2_RPC_URL"), error=str(e), tb=traceback.format_exc())

    while True:
        with SessionLocal() as s:
            # 1) Resolve new queued tasks
            queued = s.execute(select(Task).where(Task.status == TaskStatus.QUEUED)).scalars().all()
            for t in queued:
                try:
                    resolve_task(s, t, client)
                except Exception as e:
                    _log(t.id, LogLevel.ERROR, "resolve_exception", err=str(e), tb=traceback.format_exc())

            # 2) Start downloads for active tasks
            active = s.execute(select(Task).where(Task.status.in_(TaskStatus.ACTIVE_STATUSES))).scalars().all()
            for t in active:
                if t.status == TaskStatus.WAITING_SELECTION:
                    continue
                if can_start_task(s, t):
                    try:
                        start_next_files(s, t, client)
                    except Exception as e:
                        _log(t.id, LogLevel.ERROR, "start_next_exception", err=str(e), tb=traceback.format_exc())
        
        time.sleep(Limits.WORKER_LOOP_INTERVAL)

if __name__ == "__main__":
    worker_loop()
