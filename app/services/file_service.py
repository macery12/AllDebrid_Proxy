import os
import tarfile
import io
from pathlib import Path
from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse, FileResponse
from app.config import settings
from app.validation import validate_task_id
from app.exceptions import ValidationError

# 4 MB streaming chunk size
_CHUNK_SIZE = 4 * 1024 * 1024
VIDEO_MIME: dict[str, str] = {
    ".mp4": "video/mp4", ".mkv": "video/x-matroska", ".avi": "video/x-msvideo",
    ".mov": "video/quicktime", ".wmv": "video/x-ms-wmv", ".flv": "video/x-flv",
    ".webm": "video/webm", ".m4v": "video/mp4", ".mpg": "video/mpeg", ".mpeg": "video/mpeg",
}


def _resolve_task_path(task_id: str, relpath: str) -> Path:
    try:
        task_id = validate_task_id(task_id)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    base = (Path(settings.STORAGE_ROOT) / task_id / "files").resolve()
    if not base.exists():
        raise HTTPException(status_code=404, detail="Task storage not found")

    # Prevent path traversal
    target = (base / relpath).resolve()
    if not str(target).startswith(str(base)):
        raise HTTPException(status_code=400, detail="Path traversal not allowed")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return target


def _serve_range(file_path: Path, request: Request, media_type: str) -> StreamingResponse:
    file_size = file_path.stat().st_size
    range_header = request.headers.get("range")

    start, end = 0, file_size - 1
    status_code = 200
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(file_size),
    }

    if range_header and range_header.startswith("bytes="):
        try:
            parts = range_header[6:].split("-")
            start = int(parts[0]) if parts[0] else 0
            end = int(parts[1]) if len(parts) > 1 and parts[1] else file_size - 1
        except ValueError:
            raise HTTPException(status_code=416, detail="Invalid range header")

        if start > end or end >= file_size:
            raise HTTPException(
                status_code=416,
                detail="Range Not Satisfiable",
                headers={"Content-Range": f"bytes */{file_size}"},
            )

        status_code = 206
        headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
        headers["Content-Length"] = str(end - start + 1)

    def generator():
        with open(file_path, "rb") as f:
            f.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                chunk = f.read(min(_CHUNK_SIZE, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    return StreamingResponse(generator(), status_code=status_code, media_type=media_type, headers=headers)


def stream_file(task_id: str, relpath: str, request: Request) -> StreamingResponse:
    target = _resolve_task_path(task_id, relpath)
    ext = target.suffix.lower()
    media_type = VIDEO_MIME.get(ext, "application/octet-stream")
    return _serve_range(target, request, media_type)


def download_file(task_id: str, relpath: str) -> FileResponse:
    target = _resolve_task_path(task_id, relpath)
    return FileResponse(target, filename=target.name, media_type="application/octet-stream")


def stream_archive(task_id: str) -> StreamingResponse:
    try:
        task_id = validate_task_id(task_id)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    base = (Path(settings.STORAGE_ROOT) / task_id / "files").resolve()
    if not base.exists():
        raise HTTPException(status_code=404, detail="Task storage not found")

    def generator():
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            for entry in base.rglob("*"):
                if entry.is_file() and not entry.name.endswith(".aria2"):
                    tar.add(entry, arcname=entry.relative_to(base).as_posix())
        buf.seek(0)
        while True:
            chunk = buf.read(_CHUNK_SIZE)
            if not chunk:
                break
            yield chunk

    return StreamingResponse(
        generator(),
        media_type="application/x-tar",
        headers={"Content-Disposition": f'attachment; filename="{task_id}.tar.gz"'},
    )


def generate_links_txt(task_id: str, base_url: str, dl_token: str | None = None) -> StreamingResponse:
    try:
        task_id = validate_task_id(task_id)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    base = (Path(settings.STORAGE_ROOT) / task_id / "files").resolve()
    if not base.exists():
        raise HTTPException(status_code=404, detail="Task storage not found")

    lines = []
    for entry in sorted(base.rglob("*")):
        if entry.is_file() and not entry.name.endswith(".aria2"):
            rel = entry.relative_to(base).as_posix()
            from urllib.parse import quote
            url = f"{base_url}/files/{task_id}/raw/{quote(rel)}"
            if dl_token:
                url += f"?token={quote(dl_token, safe='')}"
            lines.append(url + "\n")

    content = "".join(lines)
    return StreamingResponse(
        iter([content.encode()]),
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{task_id}_links.txt"'},
    )
