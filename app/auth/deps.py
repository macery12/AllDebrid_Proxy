import jwt
import redis
from typing import Optional
from fastapi import Request, HTTPException, status, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.auth.jwt import decode_access_token, decode_download_token, COOKIE_NAME
from app.db import get_db
from app.models import User
from app.config import settings

_redis_client: redis.Redis | None = None


def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


async def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    # Read JWT from HTTPOnly cookie
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    try:
        payload = decode_access_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    # Check logout blocklist
    jti = payload.get("jti")
    if jti and _get_redis().exists(f"jwt_block:{jti}"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token revoked")

    user = db.execute(select(User).where(User.id == int(payload["sub"]))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return user


def require_any_user(user: User = Depends(get_current_user)) -> User:
    # Any authenticated user regardless of role
    return user


def require_member(user: User = Depends(get_current_user)) -> User:
    # Member or admin; blocks 'user' role
    if user.role not in ("member", "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    # Admin only
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


async def require_file_access(
    task_id: str,
    request: Request,
    token: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
) -> int:
    """Auth guard for file download/stream endpoints.

    Accepts either:
      1. A valid session cookie (normal browser use — HTTPOnly cookie sent automatically).
      2. A ``?token=`` download JWT scoped to ``task_id`` (for download managers that
         cannot send cookies).

    Returns the authenticated user's ID as an int.
    Download tokens cannot be used on any other API endpoint (different ``aud`` claim).
    """
    if token is not None:
        try:
            payload = decode_download_token(token, task_id)
            return int(payload["sub"])
        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Download token expired — request a new one from /files/{task_id}/dl-token",
            )
        except jwt.InvalidTokenError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid download token",
            )

    # Fall back to cookie-based session auth
    user = await get_current_user(request, db)
    return user.id
