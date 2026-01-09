import uuid, json, os, time, shutil, redis, asyncio
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from app.auth import verify_worker_key, verify_sse_access
from app.schemas import CreateTaskRequest, TaskResponse, FileItem, SelectRequest, StorageInfo
from app.config import settings
from app.db import SessionLocal
from app.models import Task, TaskFile, UserStats
from app.utils import parse_infohash, ensure_task_dirs, write_metadata, append_log, disk_free_bytes
from app.ws_manager import ws_manager
from app.constants import TaskStatus, FileState, EventType, Limits
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
        HTTPException: If magnet link is invalid or task creation fails
    """
    # Validate inputs
    try:
        validate_magnet_link(req.source)
        if req.label:
            req.label = validate_label(req.label)
        if req.user_id:
            validate_positive_int(req.user_id, "user_id")
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    infohash = parse_infohash(req.source)
    if not infohash:
        raise HTTPException(status_code=400, detail="Invalid magnet (infohash not found)")
    
    with SessionLocal() as s:
        # Check for existing completed tasks with the same infohash
        existing_completed = s.execute(
            select(Task)
            .where(Task.infohash == infohash)
            .where(Task.status.in_(TaskStatus.COMPLETED_STATUSES))
            .order_by(Task.created_at.desc())
        ).scalars().first()
        
        if existing_completed:
            # Reuse existing completed task
            return {
                "taskId": existing_completed.id, 
                "status": existing_completed.status,
                "reused": True,
                "message": f"Reusing existing task with matching infohash"
            }
        
        # Create new task
        task_id = str(uuid.uuid4())
        base, _ = ensure_task_dirs(settings.STORAGE_ROOT, task_id)
        t = Task(
            id=task_id, mode=req.mode, source=req.source, infohash=infohash,
            provider="alldebrid", status=TaskStatus.QUEUED, label=req.label or None,
            user_id=req.user_id
        )
        s.add(t)
        s.commit()
        
        # Update user stats if user_id provided
        if req.user_id:
            stats = s.query(UserStats).filter(UserStats.user_id == req.user_id).first()
            if stats:
                stats.total_magnets_processed += 1
                s.commit()
        
        append_log(base, {"level":"info","event":"task_created","taskId":task_id})
        write_metadata(base, {"taskId": task_id, "mode": req.mode, "label": req.label, "infohash": infohash, "status": TaskStatus.QUEUED})
        # Notify worker
        r.lpush("queue:tasks", task_id)
        r.publish(f"task:{task_id}", json.dumps({"type":EventType.HELLO,"taskId":task_id,"mode":req.mode,"status":TaskStatus.QUEUED}))
        return {"taskId": task_id, "status": TaskStatus.QUEUED, "reused": False}

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
    with SessionLocal() as s:
        t = s.get(Task, task_id)
        if not t:
            raise HTTPException(status_code=404, detail="Not found")
        t.status = "canceled"
        s.commit()
        r.publish(f"task:{task_id}", json.dumps({"type":"state","taskId":task_id,"status":"canceled"}))
        return {"status":"canceled"}

@router.delete("/tasks/{task_id}", dependencies=[Depends(verify_worker_key)])
def delete_task(task_id: str, purge_files: bool = False):
    with SessionLocal() as s:
        t = s.get(Task, task_id)
        if not t:
            return {"ok": True}
        s.delete(t)
        s.commit()
    # Delete the files and folder associated with the task
    base, _ = ensure_task_dirs(settings.STORAGE_ROOT, task_id)
    shutil.rmtree(os.path.join(base, "files"))
    return {"ok": True}

@router.get("/tasks", dependencies=[Depends(verify_worker_key)])
def list_tasks(status: str | None = None, limit: int = 100, offset: int = 0):
    """List all tasks with optional status filter for admin view"""
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
    """SSE endpoint with token-based authentication (doesn't expose worker key to frontend)"""
    with SessionLocal() as s:
        t = s.get(Task, task_id)
        if not t:
            raise HTTPException(status_code=404, detail="Not found")
        snapshot = task_to_response(t, s)

    channel = f"task:{task_id}"
    pubsub = ar.pubsub()
    await pubsub.subscribe(channel)

    HEARTBEAT_SEC = 25
    EMPTY_FILES_POLL_SEC = 0.5   # fast poll until we have files
    PERIODIC_REFRESH_SEC = 5.0   # gentle refresh even with Redis
    MAX_EMPTY_WAIT_SEC = 60.0    # stop aggressive polling after 1 min

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


