import os
import time
import redis
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from app.db import get_db
from app.auth.deps import require_admin
from app.models import Task, TaskFile, UserStats
from app.constants import TaskStatus, FileState
from app.utils import disk_free_bytes
from app.config import settings

router = APIRouter(tags=["admin"])

_r = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)


@router.get("/stats")
def get_stats(user=Depends(require_admin), db: Session = Depends(get_db)):
    total_tasks = db.execute(select(func.count(Task.id))).scalar() or 0
    queued = db.execute(select(func.count(Task.id)).where(Task.status == TaskStatus.QUEUED)).scalar() or 0
    resolving = db.execute(select(func.count(Task.id)).where(Task.status == TaskStatus.RESOLVING)).scalar() or 0
    downloading = db.execute(select(func.count(Task.id)).where(Task.status == TaskStatus.DOWNLOADING)).scalar() or 0
    waiting_sel = db.execute(select(func.count(Task.id)).where(Task.status == TaskStatus.WAITING_SELECTION)).scalar() or 0
    completed = db.execute(select(func.count(Task.id)).where(Task.status.in_(TaskStatus.COMPLETED_STATUSES))).scalar() or 0
    failed = db.execute(select(func.count(Task.id)).where(Task.status == TaskStatus.FAILED)).scalar() or 0
    canceled = db.execute(select(func.count(Task.id)).where(Task.status == TaskStatus.CANCELED)).scalar() or 0
    active = db.execute(select(func.count(Task.id)).where(Task.status.in_(TaskStatus.ACTIVE_STATUSES))).scalar() or 0

    total_files = db.execute(select(func.count(TaskFile.id))).scalar() or 0
    downloading_files = db.execute(select(func.count(TaskFile.id)).where(TaskFile.state == FileState.DOWNLOADING)).scalar() or 0
    completed_files = db.execute(select(func.count(TaskFile.id)).where(TaskFile.state == FileState.DONE)).scalar() or 0
    failed_files = db.execute(select(func.count(TaskFile.id)).where(TaskFile.state == FileState.FAILED)).scalar() or 0

    total_bytes_to_dl = db.execute(select(func.sum(TaskFile.size_bytes)).where(TaskFile.state == FileState.DOWNLOADING)).scalar() or 0
    total_bytes_dl = db.execute(select(func.sum(TaskFile.bytes_downloaded)).where(TaskFile.state == FileState.DOWNLOADING)).scalar() or 0
    dl_pct = int((total_bytes_dl / total_bytes_to_dl) * 100) if total_bytes_to_dl > 0 else 0

    free_bytes = disk_free_bytes(settings.STORAGE_ROOT)
    reserved_bytes = sum(
        max((f.size_bytes or 0) - (f.bytes_downloaded or 0), 0)
        for f in db.execute(select(TaskFile).where(TaskFile.state.in_(FileState.RESERVED_STATES))).scalars()
    )

    total_users = db.execute(select(func.count(UserStats.id))).scalar() or 0
    agg_downloads = db.execute(select(func.sum(UserStats.total_downloads))).scalar() or 0
    agg_bytes = db.execute(select(func.sum(UserStats.total_bytes_downloaded))).scalar() or 0

    queue_length = 0
    try:
        queue_length = _r.llen("queue:tasks") or 0
    except Exception:
        pass

    worker_healthy = True
    try:
        test_path = os.path.join(settings.STORAGE_ROOT, ".healthcheck_stats")
        with open(test_path, "w") as fh:
            fh.write("ok")
        os.remove(test_path)
    except Exception:
        worker_healthy = False

    active_dl_files = []
    for f in db.execute(
        select(TaskFile).where(TaskFile.state == FileState.DOWNLOADING).order_by(TaskFile.bytes_downloaded.asc()).limit(20)
    ).scalars():
        size = f.size_bytes or 0
        dl = min(f.bytes_downloaded or 0, size)
        active_dl_files.append({
            "file_id": f.id, "filename": f.name or "Unknown", "size_bytes": size,
            "downloaded_bytes": dl, "progress_pct": int((dl / size) * 100) if size > 0 else 0,
            "speed_bps": f.speed_bps or 0, "eta_seconds": f.eta_seconds,
        })

    return {
        "timestamp": time.time(),
        "tasks": {
            "total": total_tasks, "queued": queued, "resolving": resolving,
            "downloading": downloading, "waiting_selection": waiting_sel,
            "active": active, "completed": completed, "failed": failed, "canceled": canceled,
        },
        "files": {
            "total": total_files, "downloading": downloading_files,
            "completed": completed_files, "failed": failed_files,
        },
        "downloads": {
            "active_count": downloading_files, "total_bytes": total_bytes_to_dl,
            "downloaded_bytes": total_bytes_dl, "progress_pct": dl_pct,
            "active_files": active_dl_files,
        },
        "storage": {
            "free_bytes": free_bytes, "reserved_bytes": reserved_bytes,
            "low_space_floor_bytes": int(settings.LOW_SPACE_FLOOR_GB) * 1024 * 1024 * 1024,
        },
        "users": {
            "total_users": total_users,
            "aggregate_downloads": agg_downloads,
            "aggregate_bytes_downloaded": agg_bytes,
        },
        "queue": {"length": queue_length},
        "health": {"worker_healthy": worker_healthy},
    }
