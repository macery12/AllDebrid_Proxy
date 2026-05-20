import json
import asyncio
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import select
import redis.asyncio as aioredis

from app.db import get_db, SessionLocal
from app.auth.deps import require_any_user, require_member
from app.schemas import CreateTaskRequest, SelectRequest
from app.services import task_service
from app.models import Task
from app.config import settings
from app.constants import Limits
from app.validation import validate_task_id
from app.exceptions import ValidationError

router = APIRouter(tags=["tasks"])


@router.get("")
def list_tasks(
    status: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user=Depends(require_member),
    db: Session = Depends(get_db),
):
    return task_service.list_tasks(db, status, limit, offset)


@router.post("", status_code=201)
def create_task(
    req: CreateTaskRequest,
    user=Depends(require_member),
    db: Session = Depends(get_db),
):
    return task_service.create_task(db, req.source, req.mode, req.label, user.id)


@router.post("/upload", status_code=201)
async def upload_file(
    file: UploadFile = File(...),
    label: str = Form(default=None),
    user=Depends(require_member),
    db: Session = Depends(get_db),
):
    return await task_service.create_upload_task(db, file, label, user.id)


@router.post("/from-torrent", status_code=201)
async def create_from_torrent(
    torrent_file: UploadFile = File(...),
    mode: str = Form(default="auto"),
    label: str = Form(default=None),
    user=Depends(require_member),
    db: Session = Depends(get_db),
):
    data = await torrent_file.read()
    return task_service.create_torrent_task(db, data, torrent_file.filename or "upload.torrent", mode, label, user.id)


@router.get("/{task_id}")
def get_task(
    task_id: str,
    user=Depends(require_any_user),
    db: Session = Depends(get_db),
):
    task = task_service.get_task(db, task_id)
    return task_service.task_to_response(task, db)


@router.post("/{task_id}/cancel")
def cancel_task(
    task_id: str,
    user=Depends(require_member),
    db: Session = Depends(get_db),
):
    return task_service.cancel_task(db, task_id)


@router.delete("/{task_id}")
def delete_task(
    task_id: str,
    purge: bool = Query(default=False),
    user=Depends(require_member),
    db: Session = Depends(get_db),
):
    return task_service.delete_task(db, task_id, purge)


@router.post("/{task_id}/select")
def select_files(
    task_id: str,
    req: SelectRequest,
    user=Depends(require_member),
    db: Session = Depends(get_db),
):
    return task_service.select_files(db, task_id, req.fileIds)


@router.get("/{task_id}/files")
def list_task_files(
    task_id: str,
    user=Depends(require_any_user),
):
    return task_service.list_task_files(task_id)


# --- SSE endpoint ---

def _sse_event(payload: dict) -> bytes:
    body = json.dumps(payload, default=str)
    lines = [f"data: {line}" for line in body.splitlines()]
    return ("\n".join(lines) + "\n\n").encode()


def _sse_snap(snap: dict) -> bytes:
    """Tag a full task snapshot as type='state' so the frontend merges files correctly."""
    return _sse_event({**snap, "type": "state"})


@router.get("/{task_id}/events")
async def task_events(
    task_id: str,
    user=Depends(require_any_user),
    db: Session = Depends(get_db),
):
    try:
        task_id = validate_task_id(task_id)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Load initial snapshot using a fresh session (SSE runs async; can't share the dep session)
    with SessionLocal() as s:
        t = s.get(Task, task_id)
        if not t:
            raise HTTPException(status_code=404, detail="Not found")
        snapshot = task_service.task_to_response(t, s)

    channel = f"task:{task_id}"

    HEARTBEAT_SEC = Limits.SSE_HEARTBEAT_INTERVAL
    EMPTY_FILES_POLL_SEC = Limits.SSE_EMPTY_FILES_POLL
    PERIODIC_REFRESH_SEC = Limits.SSE_REFRESH_INTERVAL
    MAX_EMPTY_WAIT_SEC = Limits.SSE_MAX_EMPTY_WAIT

    last_sent_json = json.dumps(snapshot.model_dump(), sort_keys=True, default=str)
    last_full_refresh = asyncio.get_event_loop().time()
    first_connect_time = last_full_refresh

    def _fresh_snapshot() -> dict | None:
        with SessionLocal() as s:
            t2 = s.get(Task, task_id)
            if not t2:
                return None
            return task_service.task_to_response(t2, s).model_dump()

    async def sse_gen():
        nonlocal last_sent_json, last_full_refresh, first_connect_time
        # Each SSE connection gets its own aioredis connection
        ar = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        pubsub = ar.pubsub()
        try:
            await pubsub.subscribe(channel)
            yield b": hello\n\n"
            yield _sse_snap(snapshot.model_dump())

            while True:
                have_files = bool(snapshot.files)
                timeout = HEARTBEAT_SEC if have_files else EMPTY_FILES_POLL_SEC
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=timeout)
                now = asyncio.get_event_loop().time()

                if msg is None:
                    # Poll quickly when files haven't arrived yet
                    if not have_files and (now - first_connect_time) <= MAX_EMPTY_WAIT_SEC:
                        snap = _fresh_snapshot()
                        if snap is not None:
                            new_json = json.dumps(snap, sort_keys=True, default=str)
                            if new_json != last_sent_json:
                                yield _sse_snap(snap)
                                last_sent_json = new_json
                                snapshot.files = snap.get("files", [])
                        continue

                    # Periodic full refresh to catch missed events
                    if have_files and (now - last_full_refresh) >= PERIODIC_REFRESH_SEC:
                        snap = _fresh_snapshot()
                        if snap is not None:
                            new_json = json.dumps(snap, sort_keys=True, default=str)
                            if new_json != last_sent_json:
                                yield _sse_snap(snap)
                                last_sent_json = new_json
                        last_full_refresh = now

                    yield f": keep-alive {int(now)}\n\n".encode()
                    continue

                data_raw = msg.get("data")
                try:
                    data = json.loads(data_raw) if isinstance(data_raw, str) else data_raw
                except Exception:
                    data = {"raw": data_raw}

                # Full files array in the message → tag as state and forward
                if isinstance(data, dict) and isinstance(data.get("files"), list):
                    new_json = json.dumps(data, sort_keys=True, default=str)
                    if new_json != last_sent_json:
                        yield _sse_snap(data)
                        last_sent_json = new_json
                    snapshot.files = data["files"]
                    continue

                # State or file delta → pull fresh snapshot
                if isinstance(data, dict) and (
                    data.get("type") in ("state", "file") or "status" in data or "fileId" in data
                ):
                    snap = _fresh_snapshot()
                    if snap is not None:
                        new_json = json.dumps(snap, sort_keys=True, default=str)
                        if new_json != last_sent_json:
                            yield _sse_snap(snap)
                            last_sent_json = new_json
                            snapshot.files = snap.get("files", [])
                    else:
                        yield _sse_event(data)
                    last_full_refresh = now
                    continue

                yield _sse_event(data)

        except asyncio.CancelledError:
            pass
        finally:
            try:
                await pubsub.unsubscribe(channel)
            except Exception:
                pass
            try:
                await pubsub.aclose()
            except Exception:
                pass

    return StreamingResponse(
        sse_gen(),
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Content-Type": "text/event-stream",
        },
    )
