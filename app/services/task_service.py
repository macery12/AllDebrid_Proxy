import uuid
import json
import os
import shutil
import hashlib
import time
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from fastapi import HTTPException, UploadFile
from app.models import Task, TaskFile, UserStats
from app.schemas import TaskResponse, FileItem, StorageInfo
from app.config import settings
from app.constants import TaskStatus, FileState, EventType, SourceType, Limits
from app.validation import validate_label, validate_task_id, validate_source, validate_torrent_file_data
from app.exceptions import ValidationError
from app.utils import ensure_task_dirs, write_metadata, append_log, disk_free_bytes, parse_source_identifier, torrent_to_magnet
from app.task_naming import generate_task_name
import redis

_r = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)


def task_to_response(task: Task, db: Session) -> TaskResponse:
    files = db.execute(
        select(TaskFile).where(TaskFile.task_id == task.id).order_by(TaskFile.index)
    ).scalars().all()

    fitems = [
        FileItem(
            fileId=f.id, index=f.index, name=f.name, size=f.size_bytes, state=f.state,
            bytesDownloaded=f.bytes_downloaded, speedBps=f.speed_bps or 0,
            etaSeconds=f.eta_seconds, progressPct=f.progress_pct or 0,
        )
        for f in files
    ]

    free = disk_free_bytes(settings.STORAGE_ROOT)
    storage = StorageInfo(
        freeBytes=free,
        taskTotalSize=sum(f.size_bytes or 0 for f in files),
        taskReservedBytes=sum(
            (f.size_bytes or 0) - (f.bytes_downloaded or 0)
            for f in files if f.state in ("selected", "downloading")
        ),
        globalReservedBytes=0,
        lowSpaceFloorBytes=int(settings.LOW_SPACE_FLOOR_GB) * 1024 * 1024 * 1024,
        willStartWhenFreeBytesAtLeast=None,
    )

    return TaskResponse(
        taskId=task.id, mode=task.mode, status=task.status, label=task.label,
        infohash=task.infohash, files=fitems, storage=storage,
    )


def _queue_new_task(task_id: str, mode: str, status: str = TaskStatus.QUEUED) -> None:
    _r.lpush("queue:tasks", task_id)
    _r.publish(f"task:{task_id}", json.dumps({"type": EventType.HELLO, "taskId": task_id, "mode": mode, "status": status}))


def _bump_user_stats(db: Session, user_id: int) -> None:
    stats = db.execute(select(UserStats).where(UserStats.user_id == user_id)).scalar_one_or_none()
    if stats:
        stats.total_magnets_processed += 1
        db.commit()


def create_task(db: Session, source: str, mode: str, label: str | None, user_id: int | None) -> dict:
    # Validate inputs
    try:
        from app.validation import validate_source
        validated_source, source_type = validate_source(source)
        identifier = parse_source_identifier(validated_source, source_type)
        if label:
            label = validate_label(label)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Reuse existing task with same identifier if still active/complete
    reusable = TaskStatus.COMPLETED_STATUSES + TaskStatus.ACTIVE_STATUSES + [TaskStatus.QUEUED, TaskStatus.RESOLVING]
    existing = db.execute(
        select(Task)
        .where(Task.infohash == identifier)
        .where(Task.source_type == source_type)
        .where(Task.status.in_(reusable))
        .order_by(Task.created_at.desc())
    ).scalars().first()

    if existing:
        return {"taskId": existing.id, "status": existing.status, "reused": True}

    task_id = str(uuid.uuid4())
    base, _ = ensure_task_dirs(settings.STORAGE_ROOT, task_id)

    if not label:
        label = generate_task_name(validated_source, source_type=source_type, task_id=task_id)

    task = Task(
        id=task_id, mode=mode, source=validated_source, source_type=source_type,
        infohash=identifier, provider="alldebrid", status=TaskStatus.QUEUED,
        label=label, user_id=user_id,
    )
    db.add(task)
    db.commit()

    if user_id:
        _bump_user_stats(db, user_id)

    append_log(base, {"level": "info", "event": "task_created", "taskId": task_id, "sourceType": source_type})
    write_metadata(base, {"taskId": task_id, "mode": mode, "label": label, "infohash": identifier, "sourceType": source_type, "status": TaskStatus.QUEUED})
    _queue_new_task(task_id, mode)

    return {"taskId": task_id, "status": TaskStatus.QUEUED, "reused": False}


async def create_upload_task(db: Session, file: UploadFile, label: str | None, user_id: int | None) -> dict:
    import re
    from pathlib import Path

    if not file or not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    original_filename = file.filename
    file_base = Path(original_filename).stem
    file_ext = Path(original_filename).suffix
    safe_base = re.sub(r"[^\w\-]", "_", file_base).strip("._-")[:200]
    safe_ext = re.sub(r"[^\w\.]", "", file_ext)[:50]
    if safe_ext and not safe_ext.startswith("."):
        safe_ext = "." + safe_ext
    safe_filename = safe_base + safe_ext if safe_base else f"uploaded_file_{int(time.time())}{safe_ext}"

    if label:
        try:
            label = validate_label(label)
        except ValidationError as e:
            raise HTTPException(status_code=400, detail=str(e))

    task_id = str(uuid.uuid4())
    base, files_dir = ensure_task_dirs(settings.STORAGE_ROOT, task_id)
    file_path = os.path.join(files_dir, safe_filename)
    temp_path = file_path + ".tmp"
    file_size = 0

    try:
        with open(temp_path, "wb") as f:
            while True:
                chunk = await file.read(65536)
                if not chunk:
                    break
                file_size += len(chunk)
                if file_size > Limits.MAX_UPLOAD_FILE_SIZE:
                    os.remove(temp_path)
                    raise HTTPException(status_code=413, detail=f"File too large (max {Limits.MAX_UPLOAD_FILE_SIZE // (1024 ** 3)}GB)")
                f.write(chunk)
        os.rename(temp_path, file_path)
    except HTTPException:
        shutil.rmtree(base, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(base, ignore_errors=True)
        raise HTTPException(status_code=400, detail=f"Failed to save file: {e}")

    identifier = hashlib.sha256(f"{original_filename}:{time.time()}".encode()).hexdigest()

    task = Task(
        id=task_id, mode="auto", source=f"upload://{original_filename}",
        source_type=SourceType.UPLOAD, infohash=identifier, provider="upload",
        status=TaskStatus.COMPLETED, label=label or original_filename, user_id=user_id,
    )
    db.add(task)
    db.add(TaskFile(
        id=str(uuid.uuid4()), task_id=task_id, index=0, name=safe_filename,
        size_bytes=file_size, state=FileState.DONE, bytes_downloaded=file_size,
        local_path=safe_filename,
    ))
    db.commit()

    if user_id:
        _bump_user_stats(db, user_id)

    append_log(base, {"level": "info", "event": "upload_completed", "taskId": task_id, "filename": safe_filename})
    write_metadata(base, {"taskId": task_id, "mode": "auto", "label": label or original_filename, "infohash": identifier, "sourceType": SourceType.UPLOAD, "status": TaskStatus.COMPLETED})
    _r.publish(f"task:{task_id}", json.dumps({"type": EventType.STATE, "taskId": task_id, "status": TaskStatus.COMPLETED}))

    return {"taskId": task_id, "status": TaskStatus.COMPLETED, "filename": safe_filename, "size": file_size, "reused": False}


def create_torrent_task(db: Session, torrent_data: bytes, filename: str, mode: str, label: str | None, user_id: int | None) -> dict:
    # Convert torrent bytes to magnet then create a normal task
    try:
        from app.validation import validate_torrent_file_data
        validate_torrent_file_data(torrent_data, filename)
        magnet = torrent_to_magnet(torrent_data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid torrent file: {e}")
    return create_task(db, magnet, mode, label, user_id)


def list_tasks(db: Session, status: str | None, limit: int, offset: int) -> dict:
    from app.validation import validate_positive_int
    try:
        limit = validate_positive_int(limit, "limit", max_value=Limits.DEFAULT_TASK_LIMIT)
        offset = validate_positive_int(offset, "offset") if offset else 0
        if status and status not in TaskStatus.ALL_STATUSES:
            raise ValidationError(f"Invalid status: {status}")
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    query = select(Task).order_by(Task.created_at.desc())
    count_q = select(func.count(Task.id))
    if status:
        query = query.where(Task.status == status)
        count_q = count_q.where(Task.status == status)
    tasks = db.execute(query.limit(limit).offset(offset)).scalars().all()
    total = db.execute(count_q).scalar()

    return {
        "tasks": [
            {
                "taskId": t.id, "id": t.id, "label": t.label, "mode": t.mode,
                "source": t.source, "infohash": t.infohash, "status": t.status,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "updated_at": t.updated_at.isoformat() if t.updated_at else None,
            }
            for t in tasks
        ],
        "total": total,
    }


def get_task(db: Session, task_id: str) -> Task:
    try:
        task_id = validate_task_id(task_id)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Not found")
    return task


def cancel_task(db: Session, task_id: str) -> dict:
    task = get_task(db, task_id)
    task.status = TaskStatus.CANCELED
    db.commit()
    _r.publish(f"task:{task_id}", json.dumps({"type": EventType.STATE, "taskId": task_id, "status": TaskStatus.CANCELED}))
    return {"status": TaskStatus.CANCELED}


def delete_task(db: Session, task_id: str, purge_files: bool) -> dict:
    try:
        task_id = validate_task_id(task_id)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    task = db.get(Task, task_id)
    if task:
        db.delete(task)
        db.commit()
    if purge_files:
        try:
            base, _ = ensure_task_dirs(settings.STORAGE_ROOT, task_id)
            files_dir = os.path.join(base, "files")
            if os.path.exists(files_dir):
                shutil.rmtree(files_dir)
        except Exception:
            pass
    return {"ok": True}


def select_files(db: Session, task_id: str, file_ids: list[str]) -> dict:
    task = get_task(db, task_id)
    if task.mode != "select" or task.status != TaskStatus.WAITING_SELECTION:
        raise HTTPException(status_code=400, detail="Task is not waiting for selection")
    ids = set(file_ids or [])
    for f in db.execute(select(TaskFile).where(TaskFile.task_id == task_id)).scalars():
        if f.id in ids:
            f.state = FileState.SELECTED
    task.status = TaskStatus.DOWNLOADING
    db.commit()
    base, _ = ensure_task_dirs(settings.STORAGE_ROOT, task_id)
    append_log(base, {"level": "info", "event": "selection_made", "count": len(ids)})
    _r.publish(f"task:{task_id}", json.dumps({"type": EventType.STATE, "taskId": task_id, "status": TaskStatus.DOWNLOADING}))
    return {"status": TaskStatus.DOWNLOADING}


def list_task_files(task_id: str) -> dict:
    # Return filesystem file listing for a task (used by FilesPage)
    from pathlib import Path
    import mimetypes

    try:
        task_id = validate_task_id(task_id)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    base = (Path(settings.STORAGE_ROOT) / task_id / "files").resolve()
    if not base.exists():
        return {"entries": []}

    VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".mpg", ".mpeg"}
    entries = []
    for p in sorted(base.rglob("*")):
        if p.is_symlink() and not p.resolve().is_relative_to(base):
            continue
        if p.is_file() and not p.name.endswith(".aria2"):
            rel = p.relative_to(base).as_posix()
            entries.append({
                "rel": rel,
                "size": p.stat().st_size,
                "is_video": p.suffix.lower() in VIDEO_EXTS,
                "is_downloading": Path(str(p) + ".aria2").exists(),
            })
    return {"entries": entries}
