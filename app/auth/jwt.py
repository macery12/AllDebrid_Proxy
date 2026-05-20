import jwt
import uuid
from datetime import datetime, timedelta, timezone
from fastapi import Response
from app.config import settings

ALGORITHM = "HS256"
COOKIE_NAME = "access_token"
# Download tokens are short-lived and task-scoped (for download managers / ?token= auth)
DL_TOKEN_TTL_HOURS = 8


def create_access_token(user, remember_me: bool = False) -> str:
    # Build a signed JWT for the given user.
    # remember_me=True uses the longer JWT_REMEMBER_ME_HOURS TTL.
    ttl_hours = settings.JWT_REMEMBER_ME_HOURS if remember_me else settings.JWT_EXPIRY_HOURS
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "username": user.username,
        "role": user.role,
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + timedelta(hours=ttl_hours),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    # Raises jwt.InvalidTokenError on any failure.
    # Skip aud verification (session tokens carry no aud claim), but explicitly
    # reject download tokens that are misused as session tokens.
    payload = jwt.decode(
        token, settings.JWT_SECRET, algorithms=[ALGORITHM],
        options={"verify_aud": False},
    )
    if payload.get("aud") == "download":
        raise jwt.InvalidTokenError("Cannot use a download token as a session token")
    return payload


def create_download_token(user_id: int, task_id: str) -> str:
    """Issue a short-lived, task-scoped JWT for ?token= download auth.

    This token ONLY grants access to files belonging to task_id; it cannot be
    used to authenticate any other API endpoint.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "aud": "download",
        "task": task_id,
        "iat": now,
        "exp": now + timedelta(hours=DL_TOKEN_TTL_HOURS),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=ALGORITHM)


def decode_download_token(token: str, task_id: str) -> dict:
    """Validate a download token scoped to task_id.

    Raises jwt.InvalidTokenError (or subclass) on any validation failure.
    """
    payload = jwt.decode(
        token, settings.JWT_SECRET, algorithms=[ALGORITHM],
        audience="download",
    )
    if payload.get("task") != task_id:
        raise jwt.InvalidTokenError("Token is not valid for this task")
    return payload


def set_auth_cookie(response: Response, token: str, remember_me: bool = False) -> None:
    max_age = (
        settings.JWT_REMEMBER_ME_HOURS * 3600
        if remember_me
        else settings.JWT_EXPIRY_HOURS * 3600
    )
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=max_age,
        path="/",
    )


def clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(key=COOKIE_NAME, path="/")
