import uuid, json, os, time, shutil, redis, asyncio, hashlib
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, UploadFile, File, Form
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from app.auth import verify_worker_key, verify_sse_access
from app.schemas import CreateTaskRequest, TaskResponse, FileItem, SelectRequest, StorageInfo
from app.config import settings
from app.db import SessionLocal
from app.models import Task, TaskFile, UserStats
from app.utils import parse_infohash, ensure_task_dirs, write_metadata, append_log, disk_free_bytes
from app.ws_manager import ws_manager
from app.constants import TaskStatus, FileState, EventType, Limits, SourceType
from app.validation import validate_magnet_link, validate_task_id, validate_label, validate_positive_int
from app.exceptions import ValidationError, ResourceNotFoundError
from starlette.responses import StreamingResponse
import redis.asyncio as aioredis


router = APIRouter(prefix="/api", tags=["api"])
r = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
ar = aioredis.from_url(settings.REDIS_URL, decode_responses=True)

def _sse_event(payload: dict, event: str | None = None, eid: str | None = None) -> bytes:
    lines = []
    if event:
        lines.append(f"event: {event}")
    if eid:
        lines.append(f"id: {eid}")
    body = json.dumps(payload, default=str)
    for line in body.splitlines():
        lines.append(f"data: {line}")
    lines.append("")  # terminator
    return ("\n".join(lines) + "\n").encode()


def task_to_response(task: Task, session) -> TaskResponse:
    files = session.execute(select(TaskFile).where(TaskFile.task_id == task.id).order_by(TaskFile.index)).scalars().all()
    fitems = [FileItem(
        fileId=f.id, index=f.index, name=f.name, size=f.size_bytes, state=f.state,
        bytesDownloaded=f.bytes_downloaded, localPath=f.local_path
    ) for f in files]

    # Basic storage info
    free = disk_free_bytes(settings.STORAGE_ROOT)
    storage = StorageInfo(
        freeBytes=free,
        taskTotalSize=sum([f.size_bytes or 0 for f in files]),
        taskReservedBytes=sum([(f.size_bytes or 0) - (f.bytes_downloaded or 0) for f in files if f.state in ("selected","downloading")]),
        globalReservedBytes=0,  # computed by worker; simplified here
        lowSpaceFloorBytes=int(settings.LOW_SPACE_FLOOR_GB) * 1024 * 1024 * 1024,
        willStartWhenFreeBytesAtLeast=None
    )

    return TaskResponse(
        taskId=task.id, mode=task.mode, status=task.status, label=task.label,
        infohash=task.infohash, files=fitems, storage=storage
    )

@router.post("/tasks", dependencies=[Depends(verify_worker_key)])
def create_task(req: CreateTaskRequest):
    """
    Create a new download task.
    
    Args:
        req: Task creation request
        
    Returns:
        Task creation response with ID and status
        
    Raises:
        HTTPException: If source is invalid or task creation fails
    """
    # Validate inputs
    try:
        # Validate source (magnet or link)
        from app.validation import validate_source
        from app.utils import parse_source_identifier
        
        validated_source, source_type = validate_source(req.source)
        identifier = parse_source_identifier(validated_source, source_type)
        
        if req.label:
            req.label = validate_label(req.label)
        if req.user_id:
            validate_positive_int(req.user_id, "user_id")
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    with SessionLocal() as s:
        # Check for existing tasks with the same identifier (completed or in-progress)
        # This prevents duplicate downloads of the same magnet/link
        reusable_statuses = (
            TaskStatus.COMPLETED_STATUSES + 
            TaskStatus.ACTIVE_STATUSES + 
            [TaskStatus.QUEUED, TaskStatus.RESOLVING]
        )
        
        existing_task = s.execute(
            select(Task)
            .where(Task.infohash == identifier)
            .where(Task.source_type == source_type)
            .where(Task.status.in_(reusable_statuses))
            .order_by(Task.created_at.desc())
        ).scalars().first()
        
        if existing_task:
            # Reuse existing task (completed or in-progress)
            return {
                "taskId": existing_task.id, 
                "status": existing_task.status,
                "reused": True,
                "message": f"Reusing existing task with matching {'infohash' if source_type == 'magnet' else 'link'}"
            }
        
        # Create new task
        task_id = str(uuid.uuid4())
        base, _ = ensure_task_dirs(settings.STORAGE_ROOT, task_id)
        t = Task(
            id=task_id, mode=req.mode, source=validated_source, source_type=source_type,
            infohash=identifier, provider="alldebrid", status=TaskStatus.QUEUED, 
            label=req.label or None, user_id=req.user_id
        )
        s.add(t)
        s.commit()
        
        # Update user stats if user_id provided
        if req.user_id:
            stats = s.query(UserStats).filter(UserStats.user_id == req.user_id).first()
            if stats:
                stats.total_magnets_processed += 1
                s.commit()
        
        append_log(base, {"level":"info","event":"task_created","taskId":task_id,"sourceType":source_type})
        write_metadata(base, {"taskId": task_id, "mode": req.mode, "label": req.label, "infohash": identifier, "sourceType": source_type, "status": TaskStatus.QUEUED})
        # Notify worker
        r.lpush("queue:tasks", task_id)
        r.publish(f"task:{task_id}", json.dumps({"type":EventType.HELLO,"taskId":task_id,"mode":req.mode,"status":TaskStatus.QUEUED}))
        return {"taskId": task_id, "status": TaskStatus.QUEUED, "reused": False}

@router.post("/tasks/upload", dependencies=[Depends(verify_worker_key)])
async def upload_file_task(
    file: UploadFile = File(...),
    label: str = Form(None),
    user_id: int = Form(None)
):
    """
    Create a new task by uploading a file directly.
    Admin-only feature for uploading files without using AllDebrid.
    
    Args:
        file: File to upload
        label: Optional task label
        user_id: User ID for tracking
        
    Returns:
        Task creation response with ID and status
        
    Raises:
        HTTPException: If file is invalid or upload fails
    """
    from pathlib import Path
    import re
    
    # Validate file is present
    if not file or not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")
    
    # Sanitize filename first
    original_filename = file.filename
    # Extract the base name and extension separately for better control
    file_base = Path(original_filename).stem
    file_ext = Path(original_filename).suffix
    
    # Sanitize base name: only allow alphanumeric, underscore, and hyphen
    safe_base = re.sub(r'[^\w\-]', '_', file_base)
    safe_base = safe_base.strip('._-')[:200]  # Leave room for extension
    
    # Sanitize extension: only allow alphanumeric and single dot
    safe_ext = re.sub(r'[^\w\.]', '', file_ext)[:50]
    if safe_ext and not safe_ext.startswith('.'):
        safe_ext = '.' + safe_ext
    
    # Combine base and extension
    safe_filename = safe_base + safe_ext if safe_base else ""
    
    # Final validation - if filename is empty or invalid, generate a safe one
    if not safe_filename or safe_filename in ('.', '..', '') or not safe_base:
        # Use timestamp + extension to preserve file type
        safe_filename = f"uploaded_file_{int(time.time())}{safe_ext}"
    
    # Validate file size by streaming to temporary file
    file_size = 0
    chunk_size = 1024 * 1024  # 1MB chunks
    
    # Create task ID early to set up storage location
    task_id = str(uuid.uuid4())
    base, files_dir = ensure_task_dirs(settings.STORAGE_ROOT, task_id)
    file_path = os.path.join(files_dir, safe_filename)
    temp_file_path = file_path + ".tmp"
    
    try:
        # Stream file to disk with size validation
        with open(temp_file_path, 'wb') as f:
            while True:
                chunk = await file.read(chunk_size)
                if not chunk:
                    break
                file_size += len(chunk)
                
                # Check size limit
                if file_size > Limits.MAX_UPLOAD_FILE_SIZE:
                    # Clean up temp file
                    if os.path.exists(temp_file_path):
                        os.remove(temp_file_path)
                    raise HTTPException(
                        status_code=413, 
                        detail=f"File too large (max {Limits.MAX_UPLOAD_FILE_SIZE // (1024*1024*1024)}GB)"
                    )
                
                f.write(chunk)
        
        # Rename temp file to final name
        os.rename(temp_file_path, file_path)
        
    except HTTPException:
        # Clean up on validation error
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        if os.path.exists(base):
            shutil.rmtree(base)
        raise
    except Exception as e:
        # Clean up on error
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        if os.path.exists(base):
            shutil.rmtree(base)
        raise HTTPException(status_code=400, detail=f"Failed to save file: {str(e)}")
    
    # Validate label
    if label:
        try:
            label = validate_label(label)
        except ValidationError as e:
            # Clean up
            if os.path.exists(file_path):
                os.remove(file_path)
            if os.path.exists(base):
                shutil.rmtree(base)
            raise HTTPException(status_code=400, detail=str(e))
    
    # Validate user_id
    if user_id:
        try:
            validate_positive_int(user_id, "user_id")
        except ValidationError as e:
            # Clean up
            if os.path.exists(file_path):
                os.remove(file_path)
            if os.path.exists(base):
                shutil.rmtree(base)
            raise HTTPException(status_code=400, detail=str(e))
    
    # Create identifier (hash of filename + timestamp for uniqueness)
    identifier = hashlib.sha256(f"{original_filename}:{time.time()}".encode()).hexdigest()
    
    with SessionLocal() as s:
        # Create task
        t = Task(
            id=task_id,
            mode="auto",  # Uploaded files are always auto mode
            source=f"upload://{original_filename}",
            source_type=SourceType.UPLOAD,
            infohash=identifier,
            provider="upload",  # Special provider for uploads
            status=TaskStatus.COMPLETED,  # Mark as completed immediately
            label=label or original_filename,
            user_id=user_id
        )
        s.add(t)
        
        # Create file entry
        file_id = str(uuid.uuid4())
        task_file = TaskFile(
            id=file_id,
            task_id=task_id,
            index=0,
            name=safe_filename,
            size_bytes=file_size,
            state=FileState.DONE,  # Mark as done immediately
            bytes_downloaded=file_size,
            local_path=safe_filename
        )
        s.add(task_file)
        s.commit()
        
        # Update user stats if user_id provided
        # Note: We use total_magnets_processed for backward compatibility, but it tracks all sources
        if user_id:
            stats = s.query(UserStats).filter(UserStats.user_id == user_id).first()
            if stats:
                stats.total_magnets_processed += 1  # Tracks all tasks (magnets, links, uploads)
                s.commit()
        
        # Log and publish events
        append_log(base, {
            "level": "info",
            "event": "upload_completed",
            "taskId": task_id,
            "filename": safe_filename,
            "size": file_size
        })
        
        write_metadata(base, {
            "taskId": task_id,
            "mode": "auto",
            "label": label or original_filename,
            "infohash": identifier,
            "sourceType": SourceType.UPLOAD,
            "status": TaskStatus.COMPLETED,
            "originalFilename": original_filename,
            "savedFilename": safe_filename
        })
        
        # Publish completion event
        r.publish(f"task:{task_id}", json.dumps({
            "type": EventType.STATE,
            "taskId": task_id,
            "status": TaskStatus.COMPLETED
        }))
    
    return {
        "taskId": task_id,
        "status": TaskStatus.COMPLETED,
        "filename": safe_filename,
        "size": file_size,
        "reused": False
    }

@router.get("/tasks/{task_id}", dependencies=[Depends(verify_worker_key)])
def get_task(task_id: str):
    """
    Get task details by ID.
    
    Args:
        task_id: Task identifier
        
    Returns:
        Task response with all details
        
    Raises:
        HTTPException: If task not found or task_id invalid
    """
    # Validate task_id
    try:
        task_id = validate_task_id(task_id)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    with SessionLocal() as s:
        t = s.get(Task, task_id)
        if not t:
            raise HTTPException(status_code=404, detail="Not found")
        return task_to_response(t, s)

@router.post("/tasks/{task_id}/sse-token", dependencies=[Depends(verify_worker_key)])
def create_sse_token(task_id: str):
    """
    Generate a secure, time-limited token for SSE access.
    Prevents exposing worker key to frontend.
    
    Args:
        task_id: Task identifier
        
    Returns:
        Token and expiry information
        
    Raises:
        HTTPException: If task not found or task_id invalid
    """
    # Validate task_id
    try:
        task_id = validate_task_id(task_id)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    from app.auth import generate_sse_token
    with SessionLocal() as s:
        t = s.get(Task, task_id)
        if not t:
            raise HTTPException(status_code=404, detail="Not found")
    token = generate_sse_token(task_id)
    return {"token": token, "expiresIn": Limits.SSE_TOKEN_EXPIRY}

@router.post("/tasks/{task_id}/select", dependencies=[Depends(verify_worker_key)])
def select_files(task_id: str, req: SelectRequest):
    """
    Select files to download for a task in select mode.
    
    Args:
        task_id: Task identifier
        req: File selection request
        
    Returns:
        Updated task status
        
    Raises:
        HTTPException: If task not found, not in selection mode, or task_id invalid
    """
    # Validate task_id
    try:
        task_id = validate_task_id(task_id)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    with SessionLocal() as s:
        t = s.get(Task, task_id)
        if not t:
            raise HTTPException(status_code=404, detail="Not found")
        if t.mode != "select" or t.status != TaskStatus.WAITING_SELECTION:
            raise HTTPException(status_code=400, detail="Task is not waiting for selection")
        ids = set(req.fileIds or [])
        files = s.execute(select(TaskFile).where(TaskFile.task_id == task_id)).scalars().all()
        for f in files:
            if f.id in ids:
                f.state = FileState.SELECTED
        t.status = TaskStatus.DOWNLOADING
        s.commit()
        base, _ = ensure_task_dirs(settings.STORAGE_ROOT, task_id)
        append_log(base, {"level":"info","event":"selection_made","count":len(ids)})
        r.publish(f"task:{task_id}", json.dumps({"type":EventType.STATE,"taskId":task_id,"status":TaskStatus.DOWNLOADING}))
        return {"status": TaskStatus.DOWNLOADING}

@router.post("/tasks/{task_id}/cancel", dependencies=[Depends(verify_worker_key)])
def cancel_task(task_id: str):
    """
    Cancel a running task.
    
    Args:
        task_id: Task identifier
        
    Returns:
        Updated task status
        
    Raises:
        HTTPException: If task not found or task_id invalid
    """
    # Validate task_id
    try:
        task_id = validate_task_id(task_id)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    with SessionLocal() as s:
        t = s.get(Task, task_id)
        if not t:
            raise HTTPException(status_code=404, detail="Not found")
        t.status = TaskStatus.CANCELED
        s.commit()
        r.publish(f"task:{task_id}", json.dumps({"type":EventType.STATE,"taskId":task_id,"status":TaskStatus.CANCELED}))
        return {"status": TaskStatus.CANCELED}

@router.delete("/tasks/{task_id}", dependencies=[Depends(verify_worker_key)])
def delete_task(task_id: str, purge_files: bool = False):
    """
    Delete a task and optionally its files.
    
    Args:
        task_id: Task identifier
        purge_files: Whether to delete associated files
        
    Returns:
        Success confirmation
        
    Raises:
        HTTPException: If task_id invalid
    """
    # Validate task_id
    try:
        task_id = validate_task_id(task_id)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    with SessionLocal() as s:
        t = s.get(Task, task_id)
        if not t:
            return {"ok": True}
        s.delete(t)
        s.commit()
    
    # Delete the files and folder associated with the task
    if purge_files:
        try:
            base, _ = ensure_task_dirs(settings.STORAGE_ROOT, task_id)
            files_dir = os.path.join(base, "files")
            if os.path.exists(files_dir):
                shutil.rmtree(files_dir)
        except Exception:
            # Don't fail if file deletion fails
            pass
    
    return {"ok": True}

@router.get("/tasks", dependencies=[Depends(verify_worker_key)])
def list_tasks(status: str | None = None, limit: int = 100, offset: int = 0):
    """
    List all tasks with optional status filter for admin view.
    
    Args:
        status: Optional status filter
        limit: Maximum number of tasks to return
        offset: Offset for pagination
        
    Returns:
        List of tasks with total count
        
    Raises:
        HTTPException: If parameters are invalid
    """
    # Validate parameters
    try:
        if limit:
            limit = validate_positive_int(limit, "limit", max_value=Limits.DEFAULT_TASK_LIMIT)
        if offset:
            offset = validate_positive_int(offset, "offset")
        if status and status not in TaskStatus.ALL_STATUSES:
            raise ValidationError(f"Invalid status: {status}")
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    with SessionLocal() as s:
        query = select(Task).order_by(Task.created_at.desc())
        if status:
            query = query.where(Task.status == status)
        query = query.limit(limit).offset(offset)
        tasks = s.execute(query).scalars().all()
        return {
            "tasks": [
                {
                    "taskId": t.id,
                    "label": t.label,
                    "mode": t.mode,
                    "source": t.source,
                    "infohash": t.infohash,
                    "status": t.status,
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                    "updated_at": t.updated_at.isoformat() if t.updated_at else None,
                }
                for t in tasks
            ],
            "total": s.execute(select(func.count(Task.id))).scalar()
        }

@router.get("/tasks/{task_id}/events")
async def task_events(task_id: str, _auth=Depends(verify_sse_access)):
    """
    SSE endpoint with token-based authentication.
    Streams real-time task updates to clients.
    
    Args:
        task_id: Task identifier
        _auth: Authentication dependency
        
    Returns:
        Server-Sent Events stream
        
    Raises:
        HTTPException: If task not found or task_id invalid
    """
    # Validate task_id
    try:
        task_id = validate_task_id(task_id)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    with SessionLocal() as s:
        t = s.get(Task, task_id)
        if not t:
            raise HTTPException(status_code=404, detail="Not found")
        snapshot = task_to_response(t, s)

    channel = f"task:{task_id}"
    pubsub = ar.pubsub()
    await pubsub.subscribe(channel)

    # Use constants for timeouts
    HEARTBEAT_SEC = Limits.SSE_HEARTBEAT_INTERVAL
    EMPTY_FILES_POLL_SEC = Limits.SSE_EMPTY_FILES_POLL
    PERIODIC_REFRESH_SEC = Limits.SSE_REFRESH_INTERVAL
    MAX_EMPTY_WAIT_SEC = Limits.SSE_MAX_EMPTY_WAIT

    # Track what we last sent to avoid spamming
    last_sent_json = json.dumps(snapshot.dict(), sort_keys=True, default=str)
    last_full_refresh = asyncio.get_event_loop().time()
    first_connect_time = last_full_refresh

    def _fresh_snapshot_dict() -> dict | None:
        with SessionLocal() as s:
            t2 = s.get(Task, task_id)
            if not t2:
                return None
            return task_to_response(t2, s).dict()

    async def sse_gen():
        nonlocal last_sent_json, last_full_refresh, first_connect_time
        try:
            # hello + initial snapshot
            yield b": hello\n\n"
            yield _sse_event(snapshot.dict())

            while True:
                # choose a timeout based on whether we have files yet
                have_files = bool(snapshot.files)
                timeout = HEARTBEAT_SEC if have_files else EMPTY_FILES_POLL_SEC

                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=timeout)

                now = asyncio.get_event_loop().time()

                # 1) If no Redis message arrived, either send heartbeat or do a periodic refresh
                if msg is None:
                    # While files are empty and within the max wait, poll DB quickly
                    if not have_files and (now - first_connect_time) <= MAX_EMPTY_WAIT_SEC:
                        snap = _fresh_snapshot_dict()
                        if snap is not None:
                            new_json = json.dumps(snap, sort_keys=True, default=str)
                            if new_json != last_sent_json:
                                yield _sse_event(snap)
                                last_sent_json = new_json
                                snapshot.files = snap.get("files", [])
                                have_files = bool(snapshot.files)
                        continue

                    # Gentle periodic refresh to catch missed events (after files exist)
                    if have_files and (now - last_full_refresh) >= PERIODIC_REFRESH_SEC:
                        snap = _fresh_snapshot_dict()
                        if snap is not None:
                            new_json = json.dumps(snap, sort_keys=True, default=str)
                            if new_json != last_sent_json:
                                yield _sse_event(snap)
                                last_sent_json = new_json
                        last_full_refresh = now

                    # Heartbeat to keep intermediaries happy
                    yield f": keep-alive {int(now)}\n\n".encode()
                    continue

                # 2) We have a Redis message; forward structured events, or merge if needed
                data_raw = msg.get("data")
                try:
                    data = json.loads(data_raw) if isinstance(data_raw, str) else data_raw
                except Exception:
                    data = {"raw": data_raw}

                # If publisher sends a full files array, just forward and record
                if isinstance(data, dict) and isinstance(data.get("files"), list):
                    new_json = json.dumps(data, sort_keys=True, default=str)
                    if new_json != last_sent_json:
                        yield _sse_event(data)
                        last_sent_json = new_json
                    snapshot.files = data["files"]
                    continue

                # For state/file deltas: pull a fresh snapshot (cheap) and send if changed
                if isinstance(data, dict) and (data.get("type") in ("state", "file") or "status" in data or "fileId" in data):
                    snap = _fresh_snapshot_dict()
                    if snap is not None:
                        new_json = json.dumps(snap, sort_keys=True, default=str)
                        if new_json != last_sent_json:
                            yield _sse_event(snap)
                            last_sent_json = new_json
                            snapshot.files = snap.get("files", [])
                    else:
                        # Fall back to forwarding the delta as-is
                        yield _sse_event(data)
                    last_full_refresh = now
                    continue

                # Unknown message: forward as-is
                yield _sse_event(data)

        except asyncio.CancelledError:
            pass
        finally:
            try:
                await pubsub.unsubscribe(channel)
            except Exception:
                pass
            await pubsub.close()

    headers = {
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
        "Content-Type": "text/event-stream",
    }
    return StreamingResponse(sse_gen(), headers=headers)

@router.get("/stats", dependencies=[Depends(verify_worker_key)])
def get_system_stats():
    """
    Get comprehensive system statistics for dashboard.
    Returns statistics about tasks, downloads, storage, and system performance.
    
    Security: Does not expose sensitive information like API keys or tokens.
    
    Returns:
        System statistics dictionary
    """
    with SessionLocal() as s:
        # Task statistics
        total_tasks = s.execute(select(func.count(Task.id))).scalar() or 0
        
        # Count tasks by status
        queued_tasks = s.execute(
            select(func.count(Task.id)).where(Task.status == TaskStatus.QUEUED)
        ).scalar() or 0
        
        resolving_tasks = s.execute(
            select(func.count(Task.id)).where(Task.status == TaskStatus.RESOLVING)
        ).scalar() or 0
        
        downloading_tasks = s.execute(
            select(func.count(Task.id)).where(Task.status == TaskStatus.DOWNLOADING)
        ).scalar() or 0
        
        waiting_selection_tasks = s.execute(
            select(func.count(Task.id)).where(Task.status == TaskStatus.WAITING_SELECTION)
        ).scalar() or 0
        
        completed_tasks = s.execute(
            select(func.count(Task.id)).where(Task.status.in_(TaskStatus.COMPLETED_STATUSES))
        ).scalar() or 0
        
        failed_tasks = s.execute(
            select(func.count(Task.id)).where(Task.status == TaskStatus.FAILED)
        ).scalar() or 0
        
        canceled_tasks = s.execute(
            select(func.count(Task.id)).where(Task.status == TaskStatus.CANCELED)
        ).scalar() or 0
        
        # Active tasks (downloading or waiting for selection)
        active_tasks = s.execute(
            select(func.count(Task.id)).where(Task.status.in_(TaskStatus.ACTIVE_STATUSES))
        ).scalar() or 0
        
        # File statistics
        total_files = s.execute(select(func.count(TaskFile.id))).scalar() or 0
        
        downloading_files = s.execute(
            select(func.count(TaskFile.id)).where(TaskFile.state == FileState.DOWNLOADING)
        ).scalar() or 0
        
        completed_files = s.execute(
            select(func.count(TaskFile.id)).where(TaskFile.state == FileState.DONE)
        ).scalar() or 0
        
        failed_files = s.execute(
            select(func.count(TaskFile.id)).where(TaskFile.state == FileState.FAILED)
        ).scalar() or 0
        
        # Download progress statistics (only actively downloading files)
        total_bytes_to_download = s.execute(
            select(func.sum(TaskFile.size_bytes)).where(
                TaskFile.state == FileState.DOWNLOADING
            )
        ).scalar() or 0
        
        total_bytes_downloaded = s.execute(
            select(func.sum(TaskFile.bytes_downloaded)).where(
                TaskFile.state == FileState.DOWNLOADING
            )
        ).scalar() or 0
        
        # Calculate progress percentage (only for actively downloading files)
        if total_bytes_to_download > 0:
            download_progress_pct = int((total_bytes_downloaded / total_bytes_to_download) * 100)
        else:
            download_progress_pct = 0
        
        # Storage statistics
        free_bytes = disk_free_bytes(settings.STORAGE_ROOT)
        
        # Calculate reserved bytes (files queued/downloading)
        reserved_bytes = 0
        files = s.execute(
            select(TaskFile).where(TaskFile.state.in_(FileState.RESERVED_STATES))
        ).scalars().all()
        
        for f in files:
            sz = f.size_bytes or 0
            have = f.bytes_downloaded or 0
            reserved_bytes += max(sz - have, 0)
        
        # User statistics (aggregate)
        total_users = s.execute(select(func.count(UserStats.id))).scalar() or 0
        aggregate_user_downloads = s.execute(
            select(func.sum(UserStats.total_downloads))
        ).scalar() or 0
        aggregate_bytes_downloaded = s.execute(
            select(func.sum(UserStats.total_bytes_downloaded))
        ).scalar() or 0
        
        # Redis queue statistics (if available)
        queue_length = 0
        try:
            queue_length = r.llen("queue:tasks") or 0
        except Exception:
            pass
        
        # Worker health check
        worker_healthy = True
        try:
            # Check if storage is writable
            test_path = os.path.join(settings.STORAGE_ROOT, ".healthcheck_stats")
            with open(test_path, "w") as fh:
                fh.write("ok")
            os.remove(test_path)
        except Exception:
            worker_healthy = False
        
        # Get detailed active downloads (only downloading files, not ready/selected)
        # Order by bytes_downloaded/size_bytes ratio to show least complete first
        active_downloads = []
        downloading_files_detailed = s.execute(
            select(TaskFile)
            .where(TaskFile.state == FileState.DOWNLOADING)
            .order_by(TaskFile.bytes_downloaded.asc())  # Show files with least progress first
            .limit(20)
        ).scalars().all()
        
        for f in downloading_files_detailed:
            size = f.size_bytes or 0
            downloaded = f.bytes_downloaded or 0
            
            # Ensure we don't show >100% or weird values
            if downloaded > size and size > 0:
                downloaded = size
            
            progress = int((downloaded / size) * 100) if size > 0 else 0
            
            # Cap at 100%
            if progress > 100:
                progress = 100
            
            active_downloads.append({
                "file_id": f.id,  # For debugging
                "filename": f.name or "Unknown",
                "size_bytes": size,
                "downloaded_bytes": downloaded,
                "progress_pct": progress,
            })
    
    return {
        "timestamp": time.time(),
        "tasks": {
            "total": total_tasks,
            "queued": queued_tasks,
            "resolving": resolving_tasks,
            "downloading": downloading_tasks,
            "waiting_selection": waiting_selection_tasks,
            "active": active_tasks,
            "completed": completed_tasks,
            "failed": failed_tasks,
            "canceled": canceled_tasks,
        },
        "files": {
            "total": total_files,
            "downloading": downloading_files,
            "completed": completed_files,
            "failed": failed_files,
        },
        "downloads": {
            "active_count": downloading_files,
            "total_bytes": total_bytes_to_download,
            "downloaded_bytes": total_bytes_downloaded,
            "progress_pct": download_progress_pct,
            "active_files": active_downloads,
        },
        "storage": {
            "free_bytes": free_bytes,
            "reserved_bytes": reserved_bytes,
            "low_space_floor_bytes": int(settings.LOW_SPACE_FLOOR_GB) * 1024 * 1024 * 1024,
        },
        "users": {
            "total_users": total_users,
            "aggregate_downloads": aggregate_user_downloads,
            "aggregate_bytes_downloaded": aggregate_bytes_downloaded,
        },
        "queue": {
            "length": queue_length,
        },
        "health": {
            "worker_healthy": worker_healthy,
        }
    }


