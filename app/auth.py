from fastapi import Header, HTTPException, status
from app.config import settings

def verify_worker_key(x_worker_key: str = Header(None, alias="X-Worker-Key")):
    if not x_worker_key or x_worker_key != settings.WORKER_API_KEY:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid key")
