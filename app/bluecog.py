"""
BlueCog view — scraper integration endpoints.

Responsibilities:
  - List/search .torrent files from the scraper downloads directory
  - Trigger RSS refresh (signals the worker via Redis)
  - Trigger a single-URL fetch (queues in worker, polls for result)
  - Submit selected .torrent files as normal AllDebrid tasks
"""

import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse as _urlparse

import redis
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select as sa_select

from app.auth import verify_worker_key
from app.config import settings
from app.constants import EventType, SourceType, TaskStatus
from app.db import SessionLocal
from app.exceptions import ValidationError
from app.models import Task, UserStats
from app.task_naming import generate_task_name
from app.utils import (
    append_log,
    ensure_task_dirs,
    parse_source_identifier,
    torrent_to_magnet,
    write_metadata,
)
from app.validation import validate_label, validate_torrent_file_data

router = APIRouter(prefix="/api/bluecog", tags=["bluecog"])

_r = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)

# Compile a host-specific URL regex from the configured BLUECOGURL
_bluecog_host = re.escape(_urlparse(settings.BLUECOGURL).netloc)
_BLUECOG_URL_RE = re.compile(rf'^https?://{_bluecog_host}/')

# Redis keys used by this module and the worker
RSS_STATUS_KEY = "bluecog:rss:status"
RSS_REFRESH_KEY = "bluecog:rss:refresh_requested"
FETCH_QUEUE_KEY = "bluecog:fetch:queue"
FETCH_RES_PREFIX = "bluecog:fetch:res:"
FETCH_TIMEOUT_SEC = 120  # seconds to wait for a Playwright-driven fetch


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _downloads_dir() -> Path:
    d = Path(settings.BLUECOG_SCRAPER_DIR) / "downloads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _scraper_log() -> dict:
    p = Path(settings.BLUECOG_SCRAPER_DIR) / "downloaded.json"
    try:
        return json.loads(p.read_text()) if p.exists() else {}
    except Exception:
        return {}


def _safe_torrent_path(filename: str) -> Path:
    """Resolve a filename to an absolute path and guard against traversal."""
    if not re.match(r'^[\w\-. ]+\.torrent$', filename, re.IGNORECASE):
        raise HTTPException(status_code=400, detail="Invalid filename")
    base = _downloads_dir().resolve()
    candidate = (base / filename).resolve()
    # Ensure the resolved path is still inside the downloads directory
    try:
        candidate.relative_to(base)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")
    if not candidate.exists():
        raise HTTPException(status_code=404, detail=f"Torrent not found: {filename}")
    return candidate


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class SubmitRequest(BaseModel):
    filenames: List[str]
    mode: str = "auto"
    label: Optional[str] = None
    user_id: Optional[int] = None


class FetchUrlRequest(BaseModel):
    url: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/torrents", dependencies=[Depends(verify_worker_key)])
def list_torrents(q: str = ""):
    """Return .torrent files in the scraper downloads dir, optionally filtered."""
    downloads = _downloads_dir()
    log = _scraper_log()

    # Build reverse map: filename -> scraped metadata
    by_filename: dict[str, dict] = {}
    for link, meta in log.items():
        fn = meta.get("filename")
        if fn:
            by_filename[fn] = {
                "title": meta.get("title", fn),
                "link": link,
                "downloadedAt": meta.get("downloaded_at"),
            }

    ql = q.lower().strip()
    results = []
    for p in sorted(
        downloads.glob("*.torrent"),
        key=lambda x: x.stat().st_mtime,
        reverse=True,
    ):
        fn = p.name
        meta = by_filename.get(fn, {})
        title = meta.get("title") or fn
        if ql and ql not in fn.lower() and ql not in title.lower():
            continue
        results.append({
            "filename": fn,
            "title": title,
            "link": meta.get("link"),
            "downloadedAt": meta.get("downloadedAt"),
            "sizeBytes": p.stat().st_size,
        })

    return {"torrents": results, "total": len(results)}


@router.get("/rss/status", dependencies=[Depends(verify_worker_key)])
def rss_status():
    """Return the last RSS refresh status stored by the worker in Redis."""
    raw = _r.get(RSS_STATUS_KEY)
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            pass
    return {"status": "idle", "lastRun": None, "count": 0, "errors": []}


@router.post("/rss/refresh", dependencies=[Depends(verify_worker_key)])
def rss_refresh():
    """Signal the worker to run an RSS refresh immediately."""
    _r.set(RSS_REFRESH_KEY, "1")
    return {"queued": True}


@router.post("/fetch-url", dependencies=[Depends(verify_worker_key)])
def fetch_url(req: FetchUrlRequest):
    """Queue a single BlueCog source URL for torrent download in the worker.

    Blocks until the worker completes the Playwright fetch or times out.
    Returns the filename of the downloaded torrent on success.
    """
    if not _BLUECOG_URL_RE.match(req.url):
        raise HTTPException(status_code=400, detail="Invalid URL: must be a BlueCog source URL")

    request_id = str(uuid.uuid4())
    _r.rpush(FETCH_QUEUE_KEY, json.dumps({"id": request_id, "url": req.url}))

    res_key = f"{FETCH_RES_PREFIX}{request_id}"
    deadline = time.time() + FETCH_TIMEOUT_SEC
    while time.time() < deadline:
        raw = _r.get(res_key)
        if raw:
            _r.delete(res_key)
            result = json.loads(raw)
            if result.get("error"):
                raise HTTPException(status_code=400, detail=result["error"])
            return result
        time.sleep(1)

    raise HTTPException(
        status_code=504,
        detail="Torrent fetch timed out — verify the worker is running and Playwright is installed",
    )


@router.post("/submit", dependencies=[Depends(verify_worker_key)])
def submit_torrents(req: SubmitRequest):
    """Create AllDebrid tasks from one or more selected .torrent files."""
    if not req.filenames:
        raise HTTPException(status_code=400, detail="filenames must be a non-empty list")
    if req.mode not in ("auto", "select"):
        raise HTTPException(status_code=400, detail="mode must be 'auto' or 'select'")

    if req.label:
        try:
            req.label = validate_label(req.label)
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    log = _scraper_log()
    title_by_file: dict[str, str] = {
        meta["filename"]: meta.get("title", "")
        for meta in log.values()
        if meta.get("filename")
    }

    reusable_statuses = (
        TaskStatus.COMPLETED_STATUSES
        + TaskStatus.ACTIVE_STATUSES
        + [TaskStatus.QUEUED, TaskStatus.RESOLVING]
    )

    submitted: list = []
    errors: list = []

    for filename in req.filenames:
        try:
            torrent_path = _safe_torrent_path(filename)
            torrent_data = torrent_path.read_bytes()
            validate_torrent_file_data(torrent_data, filename)
            magnet = torrent_to_magnet(torrent_data)
            identifier = parse_source_identifier(magnet, SourceType.MAGNET)
            label = (
                req.label
                or title_by_file.get(filename)
                or filename.removesuffix(".torrent")
            )

            with SessionLocal() as s:
                existing = s.execute(
                    sa_select(Task)
                    .where(Task.infohash == identifier)
                    .where(Task.status.in_(reusable_statuses))
                    .order_by(Task.created_at.desc())
                ).scalars().first()

                if existing:
                    submitted.append({
                        "filename": filename,
                        "taskId": existing.id,
                        "status": existing.status,
                        "reused": True,
                    })
                    continue

                task_id = str(uuid.uuid4())
                base, _ = ensure_task_dirs(settings.STORAGE_ROOT, task_id)

                t = Task(
                    id=task_id,
                    mode=req.mode,
                    source=magnet,
                    source_type=SourceType.MAGNET,
                    infohash=identifier,
                    provider="alldebrid",
                    status=TaskStatus.QUEUED,
                    label=label,
                    user_id=req.user_id,
                )
                s.add(t)
                s.commit()

                if req.user_id:
                    stats = (
                        s.query(UserStats)
                        .filter(UserStats.user_id == req.user_id)
                        .first()
                    )
                    if stats:
                        stats.total_magnets_processed += 1
                        s.commit()

                append_log(base, {
                    "level": "info",
                    "event": "task_created",
                    "taskId": task_id,
                    "source": "bluecog",
                    "filename": filename,
                })
                write_metadata(base, {
                    "taskId": task_id,
                    "mode": req.mode,
                    "label": label,
                    "infohash": identifier,
                    "sourceType": SourceType.MAGNET,
                    "status": TaskStatus.QUEUED,
                })

                _r.lpush("queue:tasks", task_id)
                _r.publish(f"task:{task_id}", json.dumps({
                    "type": EventType.HELLO,
                    "taskId": task_id,
                    "mode": req.mode,
                    "status": TaskStatus.QUEUED,
                }))

                submitted.append({
                    "filename": filename,
                    "taskId": task_id,
                    "status": TaskStatus.QUEUED,
                    "reused": False,
                })

        except HTTPException as exc:
            errors.append({"filename": filename, "error": exc.detail})
        except Exception as exc:
            errors.append({"filename": filename, "error": str(exc)})

    return {"submitted": submitted, "errors": errors}
