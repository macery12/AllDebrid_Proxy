import time, os, json, uuid, threading
from datetime import datetime, timedelta
from sqlalchemy import select
from app.config import settings
from app.db import SessionLocal
from app.models import Task, TaskFile
from app.utils import ensure_task_dirs, append_log, write_metadata, disk_free_bytes
import redis

r = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)

def publish(task_id: str, payload: dict):
    payload = dict(payload)
    payload.setdefault("taskId", task_id)
    r.publish(f"task:{task_id}", json.dumps(payload))

def task_total_size(session, task: Task) -> int:
    rows = session.execute(
        select(TaskFile.size_bytes).where(TaskFile.task_id == task.id)
    ).scalars().all()
    return sum([x or 0 for x in rows])

def reserved_bytes_for_task(session, task: Task) -> int:
    files = session.execute(select(TaskFile).where(TaskFile.task_id == task.id)).scalars().all()
    # reserve remaining for listed/selected/downloading
    reserved = 0
    for f in files:
        if f.state in ("listed","selected","downloading"):
            sz = f.size_bytes or 0
            have = f.bytes_downloaded or 0
            reserved += max(sz - have, 0)
    return reserved

def global_reserved_bytes(session) -> int:
    total = 0
    tasks = session.execute(select(Task)).scalars().all()
    for t in tasks:
        total += reserved_bytes_for_task(session, t)
    return total

def can_start_task(session, task: Task):
    free = disk_free_bytes(settings.STORAGE_ROOT)
    low_floor = int(getattr(settings, "LOW_SPACE_FLOOR_GB", 5)) * 1024 * 1024 * 1024
    need = task_total_size(session, task) - reserved_bytes_for_task(session, task)
    global_rsv = global_reserved_bytes(session)
    return (free - global_rsv >= need) and (free >= low_floor)

def count_active_and_queued(session, task: Task):
    files = session.execute(select(TaskFile).where(TaskFile.task_id == task.id)).scalars().all()
    active = len([f for f in files if f.state == "downloading"])
    queued = len([f for f in files if f.state in ("listed","selected")])
    return active, queued
