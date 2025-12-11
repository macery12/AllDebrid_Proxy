"""
AllDebrid Proxy API Server

A FastAPI-based REST API for managing AllDebrid download tasks with real-time updates.
"""

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from app.api import router as api_router, r
from app.config import settings
from app.ws_manager import ws_manager
import asyncio
import os
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create FastAPI application
app = FastAPI(
    title="AllDebrid Proxy API",
    description="REST API for managing AllDebrid downloads with real-time progress tracking",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Configure CORS for frontend access
# In production, set ALLOWED_ORIGINS environment variable
allowed_origins = os.getenv("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["X-Worker-Key", "Content-Type"],
)

@app.on_event("startup")
async def startup():
    """Initialize background tasks on application startup."""
    logger.info("Starting AllDebrid Proxy API")
    logger.info(f"Storage root: {settings.STORAGE_ROOT}")
    logger.info(f"Environment: {settings.ENVIRONMENT}")
    
    # Launch Redis pubsub listener in background for real-time updates
    loop = asyncio.get_event_loop()
    loop.create_task(ws_manager.start_pubsub_loop())
    logger.info("Background pubsub listener started")

@app.on_event("shutdown")
async def shutdown():
    """Cleanup on application shutdown."""
    logger.info("Shutting down AllDebrid Proxy API")

@app.get("/health", tags=["Health"])
def health():
    """
    Health check endpoint.
    
    Performs basic checks:
    - Storage write test
    - Redis connectivity (implicit)
    
    Returns:
        JSON with {"ok": true/false}
    """
    ok = True
    errors = []
    
    # Test storage write access
    storage = settings.STORAGE_ROOT
    try:
        test_path = os.path.join(storage, ".healthcheck")
        with open(test_path, "w") as fh:
            fh.write("ok")
        os.remove(test_path)
    except Exception as e:
        ok = False
        errors.append(f"Storage write failed: {str(e)}")
        logger.error(f"Health check failed: {e}")
    
    response = {"ok": ok}
    if errors:
        response["errors"] = errors
    
    return JSONResponse(response, status_code=200 if ok else 503)

@app.get("/", tags=["Root"])
def root():
    """
    Root endpoint with API information.
    
    Returns:
        Basic API information and links to documentation
    """
    return {
        "name": "AllDebrid Proxy API",
        "version": "1.0.0",
        "docs": "/docs",
        "redoc": "/redoc",
        "health": "/health"
    }

# Include API routes
app.include_router(api_router)
