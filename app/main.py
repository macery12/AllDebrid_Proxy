import os
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.config import settings
from app.exceptions import AppException, ValidationError, AuthenticationError, RateLimitError
from app.logging_config import setup_logging, get_logger
from app.routers import auth, tasks, users, admin, files, bluecog

logger = setup_logging(
    level=os.getenv("LOG_LEVEL", "INFO"),
    structured=bool(int(os.getenv("STRUCTURED_LOGS", "0"))),
    logger_name="api",
)

# CORS: deny-all by default; set CORS_ORIGINS=https://... to opt in
_cors_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]


@asynccontextmanager
async def lifespan(app: FastAPI):
    if _cors_origins:
        logger.info(f"CORS enabled for origins: {_cors_origins}")
    else:
        logger.info("CORS: deny-all (set CORS_ORIGINS to allow cross-origin requests)")
    logger.info("Application started successfully")
    yield
    logger.info("Application shutting down")


app = FastAPI(
    title="AllDebrid Proxy",
    description="Secure proxy for AllDebrid downloads with task management",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = f"{time.time()}-{id(request)}"
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(ValidationError)
async def validation_error_handler(request: Request, exc: ValidationError):
    logger.warning(f"Validation error: {exc.message}", extra={"path": request.url.path})
    return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"error": "Validation failed", "detail": exc.message})


@app.exception_handler(AuthenticationError)
async def authentication_error_handler(request: Request, exc: AuthenticationError):
    logger.warning(f"Authentication error: {exc.message}", extra={"path": request.url.path})
    return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"error": "Authentication failed", "detail": exc.message})


@app.exception_handler(RateLimitError)
async def rate_limit_error_handler(request: Request, exc: RateLimitError):
    logger.warning(f"Rate limit exceeded: {exc.message}", extra={"path": request.url.path})
    return JSONResponse(status_code=status.HTTP_429_TOO_MANY_REQUESTS, content={"error": "Rate limit exceeded", "detail": exc.message}, headers={"Retry-After": "60"})


@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException):
    logger.error(f"Application error: {exc.message}", exc_info=exc, extra={"path": request.url.path})
    return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"error": "Internal server error"})


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unexpected error: {exc}", exc_info=exc, extra={"path": request.url.path})
    return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"error": "Internal server error"})


@app.get("/health")
def health():
    ok = True
    try:
        test_path = os.path.join(settings.STORAGE_ROOT, ".healthcheck")
        with open(test_path, "w") as fh:
            fh.write("ok")
        os.remove(test_path)
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        ok = False
    return JSONResponse({"ok": ok})


# Register all API and file routers
app.include_router(auth.router, prefix="/api/auth")
app.include_router(tasks.router, prefix="/api/tasks")
app.include_router(users.router, prefix="/api/users")
app.include_router(admin.router, prefix="/api/admin")
app.include_router(bluecog.router, prefix="/api/bluecog")
app.include_router(files.router, prefix="/files")

# SPA serving — assets get efficient StaticFiles, everything else gets index.html
_spa_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend", "dist"))
_spa_assets = os.path.join(_spa_dir, "assets")
if os.path.isdir(_spa_assets):
    app.mount("/assets", StaticFiles(directory=_spa_assets), name="spa-assets")


@app.get("/{full_path:path}")
async def spa_fallback(full_path: str):
    # Serve real files that exist at the root of dist (favicon.ico, manifest etc.)
    candidate = os.path.join(_spa_dir, full_path)
    if full_path and os.path.isfile(candidate):
        return FileResponse(candidate)
    # All other paths get the SPA shell
    index = os.path.join(_spa_dir, "index.html")
    if os.path.isfile(index):
        return FileResponse(index)
    return JSONResponse(status_code=404, content={"error": "Frontend not built"})
