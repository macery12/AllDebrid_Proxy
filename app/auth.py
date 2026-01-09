from fastapi import Header, HTTPException, status, Query, Request
from app.config import settings
import secrets
import time

# Store valid SSE tokens with expiration (task_id -> {token, expires})
_sse_tokens = {}
_TOKEN_EXPIRY = 3600  # 1 hour

def generate_sse_token(task_id: str) -> str:
    """Generate a secure, time-limited token for SSE connections"""
    token = secrets.token_urlsafe(32)
    _sse_tokens[f"{task_id}:{token}"] = time.time() + _TOKEN_EXPIRY
    # Clean up expired tokens
    _cleanup_expired_tokens()
    return token

def _cleanup_expired_tokens():
    """Remove expired tokens"""
    now = time.time()
    expired = [k for k, v in _sse_tokens.items() if v < now]
    for k in expired:
        del _sse_tokens[k]

def verify_sse_token(task_id: str, token: str) -> bool:
    """Verify an SSE token is valid and not expired"""
    _cleanup_expired_tokens()
    key = f"{task_id}:{token}"
    if key in _sse_tokens:
        return _sse_tokens[key] > time.time()
    return False

def verify_worker_key(
    x_worker_key: str = Header(None, alias="X-Worker-Key"),
    key: str = Query(None)
):
    """Verify worker API key from header or query parameter (for non-SSE endpoints)"""
    provided_key = x_worker_key or key
    if not provided_key or provided_key != settings.WORKER_API_KEY:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid key")

def verify_sse_access(task_id: str, sse_token: str = Query(None, alias="token")):
    """Verify SSE access using a time-limited token (instead of exposing worker key)"""
    if not sse_token or not verify_sse_token(task_id, sse_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
