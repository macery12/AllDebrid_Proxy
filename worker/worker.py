
import os, time, uuid, threading, logging, traceback, urllib.error, json, shutil
from datetime import datetime, timezone, timedelta
from sqlalchemy import select
from app.config import settings
from app.db import SessionLocal
from app.models import Task, TaskFile, UserStats
from app.utils import ensure_task_dirs, append_log, write_metadata
from app.constants import TaskStatus, FileState, EventType, Limits, LogLevel, SourceType
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
MIN_SPEED_WINDOW_SEC = 0.2
EMA_WEIGHT_PREV = 0.65
EMA_WEIGHT_CURRENT = 0.35
STALL_DETECTION_MULTIPLIER = 3

def _collect_aria2_metrics_by_path() -> dict[str, dict]:
    """
    Fetch active/waiting aria2 transfer metrics keyed by resolved local file path.
    """
    if not get_aria2:
        return {}

    try:
        rpc = get_aria2()
        keys = ["status", "completedLength", "totalLength", "downloadSpeed", "files"]
        entries = []
        entries.extend(rpc.tellActive(keys) or [])
        entries.extend(rpc.tellWaiting(0, 1000, keys) or [])

        by_path: dict[str, dict] = {}
        for item in entries:
            completed = int(item.get("completedLength") or 0)
            total = int(item.get("totalLength") or 0)
            speed = int(item.get("downloadSpeed") or 0)
            status = item.get("status") or ""

            for file_item in (item.get("files") or []):
                path = file_item.get("path")
                if not path:
                    continue
                rp = os.path.realpath(path)
                payload = {
                    "completed": max(completed, 0),
                    "total": max(total, 0),
                    "speed": max(speed, 0),
                    "status": status,
                }
                by_path[rp] = payload
                if rp.endswith(".aria2"):
                    by_path[rp[:-6]] = payload
        return by_path
    except Exception as e:
        if DEBUG:
            _log("", LogLevel.WARNING, "aria2_metrics_fetch_failed", err=str(e))
        return {}

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
                aria2_metrics = _collect_aria2_metrics_by_path()
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
                    rp_out = os.path.realpath(out_path)
                    rp_tmp = os.path.realpath(tmp_path)
                    aria2 = aria2_metrics.get(rp_out) or aria2_metrics.get(rp_tmp)
                    size_path = out_path if os.path.exists(out_path) else tmp_path
                    total = f.size_bytes or 0
                    cur = 0
                    aria2_speed = None
                    if aria2:
                        cur = aria2.get("completed", 0)
                        total = aria2.get("total", 0) or total
                        aria2_speed = aria2.get("speed", 0)
                    else:
                        cur = os.path.getsize(size_path) if os.path.exists(size_path) else 0

                    prev_bytes = f.bytes_downloaded or 0
                    prev_speed = f.speed_bps or 0
                    prev_eta = f.eta_seconds
                    prev_progress = f.progress_pct or 0
                    now_dt = datetime.now(timezone.utc)
                    elapsed = None
                    if f.last_progress_at:
                        try:
                            elapsed = max((now_dt - f.last_progress_at).total_seconds(), 0)
                        except Exception:
                            elapsed = None

                    if aria2_speed is not None:
                        progress_pct = int((cur / total) * 100) if total > 0 else 0
                        if progress_pct > 100:
                            progress_pct = 100
                        if progress_pct < 0:
                            progress_pct = 0
                        if total > 0 and cur < total and aria2_speed > 0:
                            eta_seconds = int((total - cur) / aria2_speed)
                        elif total > 0 and cur >= total:
                            eta_seconds = 0
                        else:
                            eta_seconds = None

                        changed = (
                            cur != prev_bytes
                            or int(aria2_speed) != prev_speed
                            or eta_seconds != prev_eta
                            or progress_pct != prev_progress
                        )

                        if changed:
                            f.bytes_downloaded = cur
                            f.progress_pct = progress_pct
                            f.speed_bps = max(int(aria2_speed), 0)
                            f.eta_seconds = eta_seconds
                            f.last_progress_at = now_dt
                            s.commit()
                            publish(f.task_id, {
                                "type": EventType.FILE_PROGRESS,
                                "fileId": f.id,
                                "state": f.state,
                                "bytesDownloaded": cur,
                                "total": total,
                                "progressPct": f.progress_pct,
                                "speedBps": f.speed_bps,
                                "etaSeconds": f.eta_seconds
                            })
                            if DEBUG:
                                _log(f.task_id, LogLevel.DEBUG, "file_progress_aria2",
                                     fileId=f.id, downloaded=cur, total=total, speed=f.speed_bps,
                                     eta=f.eta_seconds, path=size_path, aria2_status=aria2.get("status"))
                    elif cur != prev_bytes:
                        delta_bytes = max(cur - prev_bytes, 0)
                        inst_speed = 0.0
                        if elapsed and elapsed > MIN_SPEED_WINDOW_SEC and delta_bytes > 0:
                            inst_speed = float(delta_bytes) / float(elapsed)
                        smoothed_speed = float(prev_speed)
                        if inst_speed > 0:
                            smoothed_speed = (
                                (prev_speed * EMA_WEIGHT_PREV) + (inst_speed * EMA_WEIGHT_CURRENT)
                            ) if prev_speed > 0 else inst_speed

                        f.bytes_downloaded = cur
                        f.progress_pct = int((cur / total) * 100) if total > 0 else 0
                        if f.progress_pct > 100:
                            f.progress_pct = 100
                        f.speed_bps = max(int(smoothed_speed), 0)
                        if total > 0 and cur < total and f.speed_bps > 0:
                            f.eta_seconds = int((total - cur) / f.speed_bps)
                        else:
                            f.eta_seconds = None
                        f.last_progress_at = now_dt
                        s.commit()
                        publish(f.task_id, {
                            "type": EventType.FILE_PROGRESS,
                            "fileId": f.id,
                            "state": f.state,
                            "bytesDownloaded": cur,
                            "total": total,
                            "progressPct": f.progress_pct,
                            "speedBps": f.speed_bps,
                            "etaSeconds": f.eta_seconds
                        })
                        if DEBUG:
                            _log(f.task_id, LogLevel.DEBUG, "file_progress", 
                                 fileId=f.id, downloaded=cur, total=total, speed=f.speed_bps,
                                 eta=f.eta_seconds, path=size_path)
                    elif elapsed and elapsed > (Limits.PROGRESS_MONITOR_INTERVAL * STALL_DETECTION_MULTIPLIER) and prev_speed > 0:
                        # If progress stalls, decay transfer metrics to reflect no active transfer.
                        f.speed_bps = 0
                        f.eta_seconds = None
                        f.last_progress_at = now_dt
                        s.commit()

                    # done = final file exists AND aria2 control file does NOT exist AND (unknown size OR size >= expected)
                    if os.path.exists(out_path) and not os.path.exists(tmp_path) and ((total == 0) or (cur >= total)):
                        if f.state != FileState.DONE:
                            f.state = FileState.DONE
                            f.local_path = out_path
                            f.progress_pct = 100 if total > 0 else f.progress_pct
                            f.speed_bps = 0
                            f.eta_seconds = 0
                            f.last_progress_at = now_dt
                            
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
                                "state": f.state,
                                "localPath": f.local_path,
                                "bytesDownloaded": f.bytes_downloaded or cur,
                                "total": total,
                                "progressPct": f.progress_pct,
                                "speedBps": f.speed_bps,
                                "etaSeconds": f.eta_seconds
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

    # Handle based on source type
    if task.source_type == SourceType.MAGNET:
        # Upload magnet if not already done
        if not task.provider_ref:
            _log(task.id, LogLevel.INFO, "ad_upload_magnet_begin")
            try:
                magnet_id = client.upload_magnets([task.source])
                if isinstance(magnet_id, (list, tuple)):
                    magnet_id = magnet_id[0]
                task.provider_ref = str(magnet_id)
                session.commit()
                _log(task.id, LogLevel.INFO, "ad_upload_magnet_ok", provider_ref=task.provider_ref)
            except Exception as e:
                task.status = TaskStatus.FAILED
                session.commit()
                publish(task.id, {"type": EventType.STATE, "status": TaskStatus.FAILED, "reason": f"magnet_upload_failed: {str(e)}"})
                _log(task.id, LogLevel.ERROR, "ad_upload_magnet_failed", error=str(e), tb=traceback.format_exc())
                return

        # Mark task as resolving
        task.status = TaskStatus.RESOLVING
        session.commit()
        publish(task.id, {"type": EventType.STATE, "status": TaskStatus.RESOLVING})
        _log(task.id, LogLevel.INFO, "task_resolving_magnet")

        # Poll AllDebrid for files (up to ~20 minutes)
        for _ in range(Limits.MAX_RESOLVE_ATTEMPTS):
            try:
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
            except Exception as e:
                _log(task.id, LogLevel.WARNING, "ad_status_check_error", error=str(e))
                # Continue polling despite errors

            time.sleep(Limits.RESOLVE_POLL_DELAY)
        else:
            # Timeout: no files found after max attempts
            task.status = TaskStatus.FAILED
            session.commit()
            publish(task.id, {"type": EventType.STATE, "status": TaskStatus.FAILED, "reason": "timeout_no_files"})
            _log(task.id, LogLevel.ERROR, "resolve_timeout_no_files")
            return

    elif task.source_type == SourceType.LINK:
        # For links, get link info and unlock immediately
        task.status = TaskStatus.RESOLVING
        session.commit()
        publish(task.id, {"type": EventType.STATE, "status": TaskStatus.RESOLVING})
        _log(task.id, LogLevel.INFO, "task_resolving_link")

        try:
            # Get link info to extract filename and filesize
            link_info = client.get_link_info(task.source)
            filename = link_info.get("filename") or link_info.get("name") or "download"
            filesize = int(link_info.get("filesize") or link_info.get("size") or 0)
            
            # Validate filename for security
            try:
                validate_file_name(filename)
            except Exception as e:
                # Use a safe default filename if validation fails
                _log(task.id, LogLevel.WARNING, "invalid_filename_using_default", 
                     original=filename, error=str(e))
                filename = f"download_{task.id[:8]}"
            
            # Create a single file entry for the link
            existing = session.execute(
                select(TaskFile).where(TaskFile.task_id == task.id)
            ).scalars().first()
            
            if not existing:
                tf = TaskFile(
                    id=str(uuid.uuid4()), task_id=task.id,
                    index=0, name=filename, size_bytes=filesize, state=FileState.LISTED
                )
                session.add(tf)
                session.commit()
                
                listed_payload = [{"fileId": tf.id, "index": 0, "name": filename, "size": filesize, "state": FileState.LISTED}]
                publish(task.id, {"type": EventType.FILES_LISTED, "files": listed_payload})
                _log(task.id, LogLevel.INFO, "link_file_listed", filename=filename, size=filesize)
            
            # Store the original link as provider_ref for later unlocking
            # Note: For links, provider_ref stores the original URL (not an AllDebrid ID like magnets)
            # This is because links are unlocked directly without persistent server-side tracking
            task.provider_ref = task.source
            session.commit()
            
        except Exception as e:
            task.status = TaskStatus.FAILED
            session.commit()
            publish(task.id, {"type": EventType.STATE, "status": TaskStatus.FAILED, 
                           "reason": f"link_info_failed: {str(e)}"})
            _log(task.id, LogLevel.ERROR, "link_info_failed", error=str(e), tb=traceback.format_exc())
            return
    else:
        # Unknown source type
        task.status = TaskStatus.FAILED
        session.commit()
        publish(task.id, {"type": EventType.STATE, "status": TaskStatus.FAILED, 
                       "reason": f"unknown_source_type: {task.source_type}"})
        _log(task.id, LogLevel.ERROR, "unknown_source_type", source_type=task.source_type)
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
            if task.source_type == SourceType.MAGNET:
                # For magnets, use the magnet ID and file index
                url = client.download_link(task.provider_ref, f.index)
            elif task.source_type == SourceType.LINK:
                # For direct links, unlock the link directly
                url = client.unlock_link(task.provider_ref)
            else:
                raise RuntimeError(f"Unknown source type: {task.source_type}")
            
            if not url or not url.startswith("http"):
                raise RuntimeError("unlock returned no http(s) link")
            if DEBUG:
                _log(task.id, LogLevel.INFO, "unlock_ok", fileId=f.id, index=f.index, source_type=task.source_type)
        except Exception as e:
            f.state = FileState.FAILED
            session.commit()
            publish(task.id, {"type": EventType.FILE_FAILED, "fileId": f.id, "state": f.state, "reason": f"unlock_failed: {e}"})
            _log(task.id, LogLevel.ERROR, "unlock_failed", fileId=f.id, index=f.index, err=str(e), tb=traceback.format_exc())
            continue

        # 2) Flip to downloading BEFORE enqueue
        f.unlocked_url = url
        f.state = FileState.DOWNLOADING
        f.speed_bps = 0
        f.eta_seconds = None
        f.progress_pct = 0
        f.last_progress_at = datetime.now(timezone.utc)
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
            publish(task.id, {"type": EventType.FILE_FAILED, "fileId": f.id, "state": f.state, "reason": reason})
            _log(task.id, LogLevel.ERROR, "enqueue_failed_http", fileId=f.id, code=e.code, reason=e.reason, url=os.getenv("ARIA2_RPC_URL"))
            continue
        except Exception as e:
            f.state = FileState.FAILED
            session.commit()
            publish(task.id, {"type": EventType.FILE_FAILED, "fileId": f.id, "state": f.state, "reason": f"enqueue_failed: {e}"})
            _log(task.id, LogLevel.ERROR, "enqueue_failed", fileId=f.id, err=str(e), tb=traceback.format_exc(), url=os.getenv("ARIA2_RPC_URL"))
            continue

    # Only mark ready if ALL files are done
    files = session.execute(select(TaskFile).where(TaskFile.task_id == task.id)).scalars().all()
    if files and all(x.state == FileState.DONE for x in files):
        task.status = TaskStatus.READY
        session.commit()
        publish(task.id, {"type": EventType.STATE, "status": TaskStatus.READY})
        _log(task.id, LogLevel.INFO, "task_ready_all_done", total=len(files))

def _retention_cleanup_loop():
    """
    Background loop that purges tasks (and their files) that are older than
    RETENTION_DAYS.  Runs once per hour.  Only completed/terminal tasks are
    considered; in-progress or queued tasks are never removed.
    """
    PURGE_STATUSES = TaskStatus.COMPLETED_STATUSES + [TaskStatus.FAILED, TaskStatus.CANCELED]
    CLEANUP_INTERVAL_SEC = 3600  # run once per hour

    _log("", LogLevel.INFO, "retention_cleanup_loop_started",
         retention_days=settings.RETENTION_DAYS)

    while True:
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=settings.RETENTION_DAYS)
            with SessionLocal() as s:
                expired = s.execute(
                    select(Task)
                    .where(Task.status.in_(PURGE_STATUSES))
                    .where(Task.updated_at < cutoff)
                ).scalars().all()

                for task in expired:
                    task_dir = os.path.join(settings.STORAGE_ROOT, task.id)
                    try:
                        if os.path.isdir(task_dir):
                            shutil.rmtree(task_dir, ignore_errors=True)
                    except Exception as e:
                        _log(task.id, LogLevel.ERROR, "retention_cleanup_fs_error", err=str(e))

                    try:
                        s.delete(task)
                    except Exception as e:
                        _log(task.id, LogLevel.ERROR, "retention_cleanup_db_error", err=str(e))

                if expired:
                    try:
                        s.commit()
                    except Exception as e:
                        s.rollback()
                        _log("", LogLevel.ERROR, "retention_cleanup_commit_error", err=str(e))
                    else:
                        for task in expired:
                            _log(task.id, LogLevel.INFO, "retention_cleanup_purged",
                                 status=task.status, updated_at=str(task.updated_at))
                        _log("", LogLevel.INFO, "retention_cleanup_cycle_done",
                             purged=len(expired), retention_days=settings.RETENTION_DAYS)
        except Exception as e:
            _log("", LogLevel.ERROR, "retention_cleanup_loop_error",
                 err=str(e), tb=traceback.format_exc())

        time.sleep(CLEANUP_INTERVAL_SEC)

_cleanup_started = False

def _start_cleanup_once():
    """Start the retention cleanup thread if not already started."""
    global _cleanup_started
    if _cleanup_started:
        return
    _cleanup_started = True
    threading.Thread(target=_retention_cleanup_loop, daemon=True).start()
    _log("", LogLevel.INFO, "retention_cleanup_thread_started")


def worker_loop():
    # Main worker loop: processes queued tasks and starts downloads
    # Runs continuously, polling database for work
    _start_monitor_once()
    _start_cleanup_once()
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
