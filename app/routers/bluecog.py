import json
import re
import time
import uuid
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse as _urlparse

import redis
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.deps import require_member
from app.config import settings
from app.db import get_db
from app.providers.alldebrid import AllDebrid, ADHTTPError
from app.services.task_service import create_torrent_task
from app.utils import torrent_to_magnet
from app.validation import validate_label, validate_torrent_file_data
from app.exceptions import ValidationError

router = APIRouter(tags=["bluecog"])

_r = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)

# Compile the host regex from the configured BlueCog URL once at import
_bluecog_host = re.escape(_urlparse(settings.BLUECOGURL).netloc)
_BLUECOG_URL_RE = re.compile(rf"^https?://{_bluecog_host}/")

RSS_STATUS_KEY = "bluecog:rss:status"
RSS_REFRESH_KEY = "bluecog:rss:refresh_requested"
FETCH_QUEUE_KEY = "bluecog:fetch:queue"
FETCH_RES_PREFIX = "bluecog:fetch:res:"
FETCH_TIMEOUT_SEC = 120


def _downloads_dir() -> Path:
    d = Path(settings.SCRAPER_DATA_DIR) / "downloads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _scraper_log() -> dict:
    p = Path(settings.SCRAPER_DATA_DIR) / "downloaded.json"
    try:
        return json.loads(p.read_text()) if p.exists() else {}
    except Exception:
        return {}


def _safe_torrent_path(filename: str) -> Path:
    if not re.match(r"^[\w\-. ]+\.torrent$", filename, re.IGNORECASE):
        raise HTTPException(status_code=400, detail="Invalid filename")
    base = _downloads_dir().resolve()
    candidate = (base / filename).resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")
    if not candidate.exists():
        raise HTTPException(status_code=404, detail=f"Torrent not found: {filename}")
    return candidate


class SubmitRequest(BaseModel):
    filenames: List[str]
    mode: str = "auto"
    label: Optional[str] = None
    user_id: Optional[int] = None


class FetchUrlRequest(BaseModel):
    url: str


class CacheRequest(BaseModel):
    filename: str


@router.get("/torrents")
def list_torrents(q: str = "", user=Depends(require_member)):
    downloads = _downloads_dir()
    log = _scraper_log()

    by_filename: dict[str, dict] = {
        meta["filename"]: {"title": meta.get("title", meta["filename"]), "link": k, "downloadedAt": meta.get("downloaded_at")}
        for k, meta in log.items()
        if meta.get("filename")
    }

    ql = q.lower().strip()
    results = []
    for p in sorted(downloads.glob("*.torrent"), key=lambda x: x.stat().st_mtime, reverse=True):
        fn = p.name
        meta = by_filename.get(fn, {})
        title = meta.get("title") or fn
        if ql and ql not in fn.lower() and ql not in title.lower():
            continue
        results.append({
            "filename": fn, "title": title,
            "link": meta.get("link"), "downloadedAt": meta.get("downloadedAt"),
            "sizeBytes": p.stat().st_size,
        })
    return {"torrents": results, "total": len(results)}


@router.get("/rss/status")
def rss_status(user=Depends(require_member)):
    raw = _r.get(RSS_STATUS_KEY)
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            pass
    return {"status": "idle", "lastRun": None, "count": 0, "errors": []}


@router.post("/rss/refresh")
def rss_refresh(user=Depends(require_member)):
    _r.set(RSS_REFRESH_KEY, "1")
    return {"queued": True}


@router.post("/fetch-url")
def fetch_url(req: FetchUrlRequest, user=Depends(require_member)):
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
    raise HTTPException(status_code=504, detail="Torrent fetch timed out — verify the worker is running and Playwright is installed")


@router.post("/submit")
def submit_torrents(req: SubmitRequest, user=Depends(require_member), db: Session = Depends(get_db)):
    if not req.filenames:
        raise HTTPException(status_code=400, detail="filenames must be a non-empty list")
    if req.mode not in ("auto", "select"):
        raise HTTPException(status_code=400, detail="mode must be 'auto' or 'select'")
    if req.label:
        try:
            req.label = validate_label(req.label)
        except ValidationError as e:
            raise HTTPException(status_code=400, detail=str(e))

    log = _scraper_log()
    title_by_file: dict[str, str] = {
        meta["filename"]: meta.get("title", "")
        for meta in log.values()
        if meta.get("filename")
    }

    submitted: list = []
    errors: list = []

    for filename in req.filenames:
        try:
            torrent_path = _safe_torrent_path(filename)
            torrent_data = torrent_path.read_bytes()
            label = req.label or title_by_file.get(filename) or filename.removesuffix(".torrent")
            result = create_torrent_task(db, torrent_data, filename, req.mode, label, req.user_id)
            submitted.append({"filename": filename, **result})
        except HTTPException as e:
            errors.append({"filename": filename, "error": e.detail})
        except Exception as e:
            errors.append({"filename": filename, "error": str(e)})

    return {"submitted": submitted, "errors": errors}


@router.post("/cache")
def cache_torrent(req: CacheRequest, user=Depends(require_member)):
    torrent_path = _safe_torrent_path(req.filename)
    torrent_data = torrent_path.read_bytes()
    validate_torrent_file_data(torrent_data, req.filename)
    magnet = torrent_to_magnet(torrent_data)

    if not settings.ALLDEBRID_API_KEY:
        raise HTTPException(status_code=503, detail="AllDebrid API key not configured")

    try:
        ad = AllDebrid(api_key=settings.ALLDEBRID_API_KEY, agent=getattr(settings, "ALLDEBRID_AGENT", "alldebrid-proxy"))
        ids = ad.upload_magnets([magnet])
    except ADHTTPError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AllDebrid upload failed: {e}")

    return {"magnetId": ids[0] if ids else None, "filename": req.filename}
