from fastapi import APIRouter, Depends, Request
from app.auth.deps import require_any_user, require_file_access
from app.auth.jwt import create_download_token, DL_TOKEN_TTL_HOURS
from app.services.file_service import stream_file, download_file, stream_archive, generate_links_txt

router = APIRouter(tags=["files"])


@router.post("/{task_id}/dl-token")
def get_download_token(task_id: str, user=Depends(require_any_user)):
    """Issue a short-lived download token for a task.

    The returned ``token`` can be appended to any file endpoint as ``?token=<value>``
    so that download managers (which cannot send cookies) can authenticate.
    Tokens are task-scoped and expire after the configured TTL.
    """
    token = create_download_token(user.id, task_id)
    return {"token": token, "expires_in": DL_TOKEN_TTL_HOURS * 3600}


@router.get("/{task_id}/raw/{filepath:path}")
def raw_download(task_id: str, filepath: str, _: int = Depends(require_file_access)):
    return download_file(task_id, filepath)


@router.get("/{task_id}/stream/{filepath:path}")
def stream_video(task_id: str, filepath: str, request: Request, _: int = Depends(require_file_access)):
    return stream_file(task_id, filepath, request)


@router.get("/{task_id}/archive")
def download_archive(task_id: str, _: int = Depends(require_file_access)):
    return stream_archive(task_id)


@router.get("/{task_id}/links.txt")
def links_txt(task_id: str, request: Request, user_id: int = Depends(require_file_access)):
    base = str(request.base_url).rstrip("/")
    # Generate a fresh download token so every URL in the file works in
    # download managers without any further authentication.
    dl_token = create_download_token(user_id, task_id)
    return generate_links_txt(task_id, base, dl_token=dl_token)
