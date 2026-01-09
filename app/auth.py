from fastapi import Header, HTTPException, status, Query, Request
from app.config import settings
from app.constants import Limits
import secrets
import redis

# Redis client for SSE token storage (more secure and scalable than in-memory)
_redis_client = None

def _get_redis():
    """Get or create Redis client for token storage"""
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client

def generate_sse_token(task_id: str) -> str:
    """
    Generate a secure, time-limited token for SSE connections.
    Uses Redis for storage to support distributed deployments.
    
    Args:
        task_id: Task identifier
        
    Returns:
        Generated token string
    """
    token = secrets.token_urlsafe(32)
    key = f"sse_token:{task_id}:{token}"
    
    # Store in Redis with automatic expiration
    r = _get_redis()
    r.setex(key, Limits.SSE_TOKEN_EXPIRY, "1")
    
    return token

def verify_sse_token(task_id: str, token: str) -> bool:
    """
    Verify an SSE token is valid and not expired.
    
    Args:
        task_id: Task identifier
        token: Token to verify
        
    Returns:
        True if token is valid, False otherwise
    """
    if not token:
        return False
    
    key = f"sse_token:{task_id}:{token}"
    r = _get_redis()
    
    # Check if token exists in Redis
    return r.exists(key) > 0

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
