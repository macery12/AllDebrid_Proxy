from fastapi import FastAPI, Depends, WebSocket, WebSocketDisconnect, Header, Request, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from app.api import router as api_router, r
from app.config import settings
from app.ws_manager import ws_manager
from app.exceptions import AppException, ValidationError, AuthenticationError, RateLimitError
from app.logging_config import setup_logging, get_logger
import asyncio, json, os, time

# Setup logging
logger = setup_logging(
    level=os.getenv("LOG_LEVEL", "INFO"),
    structured=bool(int(os.getenv("STRUCTURED_LOGS", "0"))),
    logger_name="api"
)

app = FastAPI(
    title="AllDebrid Proxy",
    description="Secure proxy for AllDebrid downloads with task management",
    version="2.0.0"
)

# Add CORS middleware - configure allowed origins in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add request ID middleware for tracking
@app.middleware("http")
async def add_request_id(request: Request, call_next):
    # Add unique request ID for logging and debugging
    request_id = f"{time.time()}-{id(request)}"
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response

# Global exception handlers
@app.exception_handler(ValidationError)
async def validation_error_handler(request: Request, exc: ValidationError):
    # Handle validation errors with 400 Bad Request
    logger.warning(f"Validation error: {exc.message}", extra={"path": request.url.path})
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"error": "Validation failed", "detail": exc.message}
    )

@app.exception_handler(AuthenticationError)
async def authentication_error_handler(request: Request, exc: AuthenticationError):
    # Handle authentication errors with 401 Unauthorized
    logger.warning(f"Authentication error: {exc.message}", extra={"path": request.url.path})
    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={"error": "Authentication failed", "detail": exc.message}
    )

@app.exception_handler(RateLimitError)
async def rate_limit_error_handler(request: Request, exc: RateLimitError):
    # Handle rate limit errors with 429 Too Many Requests
    logger.warning(f"Rate limit exceeded: {exc.message}", extra={"path": request.url.path})
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={"error": "Rate limit exceeded", "detail": exc.message},
        headers={"Retry-After": "60"}
    )

@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException):
    # Handle generic application errors with 500 Internal Server Error
    logger.error(f"Application error: {exc.message}", exc_info=exc, extra={"path": request.url.path})
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": "Internal server error", "detail": "An error occurred processing your request"}
    )

@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    # Handle unexpected errors - don't leak details to client
    logger.error(f"Unexpected error: {str(exc)}", exc_info=exc, extra={"path": request.url.path})
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": "Internal server error", "detail": "An unexpected error occurred"}
    )

@app.on_event("startup")
async def startup():
    # Launch pubsub listener in background
    logger.info("Starting application...")
    loop = asyncio.get_event_loop()
    loop.create_task(ws_manager.start_pubsub_loop())
    logger.info("Application started successfully")

@app.on_event("shutdown")
async def shutdown():
    # Graceful shutdown
    logger.info("Shutting down application...")

@app.get("/health")
def health():
    # Health check endpoint with storage write test
    # Returns: {ok: true/false} based on system health
    ok = True
    storage = settings.STORAGE_ROOT
    try:
        test_path = os.path.join(storage, ".healthcheck")
        with open(test_path, "w") as fh:
            fh.write("ok")
        os.remove(test_path)
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        ok = False
    return JSONResponse({"ok": ok})

app.include_router(api_router)
