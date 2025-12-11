"""Authentication and authorization utilities."""

from fastapi import Header, HTTPException, status
from app.config import settings
import logging

logger = logging.getLogger(__name__)

def verify_worker_key(x_worker_key: str = Header(None, alias="X-Worker-Key")) -> None:
    """
    Verify the worker API key from the request header.
    
    Args:
        x_worker_key: API key from X-Worker-Key header
        
    Raises:
        HTTPException: 401 if key is missing or invalid
        
    Security Note:
        This protects sensitive API endpoints from unauthorized access.
        Always use HTTPS in production to protect the key in transit.
    """
    if not x_worker_key:
        logger.warning("API request without X-Worker-Key header")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication header",
            headers={"WWW-Authenticate": "ApiKey"}
        )
    
    if x_worker_key != settings.WORKER_API_KEY:
        logger.warning("API request with invalid X-Worker-Key")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "ApiKey"}
        )
