from fastapi import Header, HTTPException, status, Query
from app.config import settings

def verify_worker_key(
    x_worker_key: str = Header(None, alias="X-Worker-Key"),
    key: str = Query(None)
):
    """Verify worker API key from header or query parameter (for SSE compatibility)"""
    provided_key = x_worker_key or key
    if not provided_key or provided_key != settings.WORKER_API_KEY:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid key")
