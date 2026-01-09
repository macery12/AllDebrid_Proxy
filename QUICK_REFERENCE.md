# Quick Reference Guide - New Modules

## Overview
This guide provides quick reference for the new modules added during refactoring.

---

## app/constants.py

### Purpose
Centralized constants to eliminate magic strings/numbers.

### Usage Examples

```python
from app.constants import TaskStatus, FileState, Limits

# Check if task is complete
if task.status in TaskStatus.COMPLETED_STATUSES:
    print("Task is done!")

# Set file state
file.state = FileState.DOWNLOADING

# Use configured limits
timeout = Limits.SSE_TOKEN_EXPIRY
```

### Key Classes
- `TaskStatus`: Task lifecycle states (QUEUED, DOWNLOADING, READY, etc.)
- `FileState`: File states (LISTED, SELECTED, DOWNLOADING, DONE, FAILED)
- `TaskMode`: AUTO, SELECT
- `LogLevel`: DEBUG, INFO, WARNING, ERROR
- `EventType`: Redis event types (STATE, FILE_PROGRESS, etc.)
- `Limits`: Timeouts, limits, thresholds
- `HTTPHeaders`: Standard header names
- `Provider`: ALLDEBRID
- `Patterns`: Regex patterns (MAGNET_BTIH)

---

## app/exceptions.py

### Purpose
Custom exception hierarchy for better error handling.

### Usage Examples

```python
from app.exceptions import ValidationError, ResourceNotFoundError

# Raise validation error
if not valid:
    raise ValidationError("Invalid input", details={"field": "email"})

# Catch specific exceptions
try:
    process_task()
except ResourceNotFoundError as e:
    logger.error(f"Not found: {e.message}")
except ValidationError as e:
    return {"error": e.message}
```

### Exception Types
- `AppException`: Base class
- `ValidationError`: Invalid input
- `AuthenticationError`: Auth failed
- `AuthorizationError`: Permission denied
- `ResourceNotFoundError`: Resource not found
- `StorageError`: Storage operations failed
- `ProviderError`: Provider API failed
- `TaskError`: Task operations failed
- `WorkerError`: Worker operations failed
- `RateLimitError`: Rate limit exceeded
- `ConfigurationError`: Invalid config

---

## app/validation.py

### Purpose
Input validation and sanitization functions.

### Usage Examples

```python
from app.validation import (
    validate_task_id,
    validate_magnet_link,
    validate_file_name,
    sanitize_for_log
)

# Validate task ID
task_id = validate_task_id(user_input)  # Raises ValidationError if invalid

# Validate magnet link
magnet = validate_magnet_link(req.source)

# Validate file name (security)
safe_name = validate_file_name(filename)

# Sanitize for logging
safe_value = sanitize_for_log(user_input)
logger.info(f"Processing: {safe_value}")
```

### Functions
- `validate_task_id(task_id)`: UUID format validation
- `validate_magnet_link(magnet)`: Magnet link validation
- `validate_file_path(path, base_dir)`: Path traversal prevention
- `validate_file_name(name)`: File name security check
- `validate_label(label)`: Label validation
- `validate_infohash(infohash)`: Info hash validation
- `validate_positive_int(value, name, max)`: Integer validation
- `sanitize_for_log(value)`: Log injection prevention
- `validate_url(url)`: URL format validation

---

## app/logging_config.py

### Purpose
Centralized logging configuration with structured logging support.

### Usage Examples

```python
from app.logging_config import setup_logging, get_logger

# Setup logging (do once at app start)
logger = setup_logging(
    level="INFO",
    structured=False,  # True for JSON logs
    logger_name="myapp"
)

# Get logger with context
logger = get_logger("worker", task_id="123", user_id=456)
logger.info("Processing task")  # Includes task_id and user_id

# Log with extra context
logger.info("Download complete", extra={"bytes": 1024000})
```

### Features
- JSON structured logging (set STRUCTURED_LOGS=1)
- Human-readable logging for development
- Context-aware (task_id, user_id, file_id)
- Proper log levels
- Request ID tracking

### Convenience Functions
```python
from app.logging_config import log_task_event, log_error

log_task_event(logger, "task-123", "download_started", bytes=0)
log_error(logger, exception, task_id="task-123")
```

---

## app/rate_limiter.py

### Purpose
Redis-based rate limiting using sliding window algorithm.

### Usage Examples

```python
from app.rate_limiter import RateLimiter
import redis

r = redis.Redis.from_url(settings.REDIS_URL)
limiter = RateLimiter(r)

# Check rate limit
try:
    limiter.check_rate_limit(
        key="api:create_task:192.168.1.1",
        max_requests=10,
        window_seconds=60
    )
    # Process request
except RateLimitError as e:
    # Rate limit exceeded
    return {"error": "Too many requests"}

# Get remaining requests
remaining = limiter.get_remaining(
    key="api:create_task:192.168.1.1",
    max_requests=10,
    window_seconds=60
)

# Reset rate limit
limiter.reset(key="api:create_task:192.168.1.1")
```

### Decorator (for future use)
```python
@rate_limit(max_requests=10, window_seconds=60)
def my_endpoint():
    pass
```

---

## Integration Guide

### Updating Existing Code

#### Before
```python
if task.status == "ready":
    print("Done")
```

#### After
```python
from app.constants import TaskStatus

if task.status == TaskStatus.READY:
    print("Done")
```

#### Before
```python
task_id = request.get("id")
# Hope it's valid...
```

#### After
```python
from app.validation import validate_task_id
from app.exceptions import ValidationError

try:
    task_id = validate_task_id(request.get("id"))
except ValidationError as e:
    return {"error": str(e)}
```

#### Before
```python
print(f"Processing: {user_input}")
```

#### After
```python
from app.validation import sanitize_for_log

safe_input = sanitize_for_log(user_input)
logger.info(f"Processing: {safe_input}")
```

---

## Environment Variables

### New Variables

```bash
# Logging configuration
LOG_LEVEL=INFO                    # DEBUG, INFO, WARNING, ERROR, CRITICAL
STRUCTURED_LOGS=0                 # 1=JSON, 0=human-readable

# CORS configuration
CORS_ORIGINS=*                    # Comma-separated origins

# Environment
ENVIRONMENT=production            # development, staging, production

# Debug mode
DEBUG_DOWNLOADS=0                 # 1 for verbose worker logs
```

---

## Best Practices

### 1. Always Validate Input
```python
from app.validation import validate_task_id
from app.exceptions import ValidationError

def get_task(task_id: str):
    try:
        task_id = validate_task_id(task_id)
    except ValidationError as e:
        raise HTTPException(400, detail=str(e))
    # Continue...
```

### 2. Use Constants
```python
# Good
from app.constants import TaskStatus
if task.status == TaskStatus.READY:
    pass

# Avoid
if task.status == "ready":
    pass
```

### 3. Use Proper Exceptions
```python
# Good
from app.exceptions import ResourceNotFoundError
if not task:
    raise ResourceNotFoundError("Task not found")

# Avoid
if not task:
    raise Exception("Not found")
```

### 4. Log with Context
```python
# Good
logger.info("Task created", extra={"task_id": task.id, "user_id": user.id})

# Avoid
logger.info(f"Task {task.id} created for user {user.id}")
```

### 5. Sanitize Logs
```python
# Good
from app.validation import sanitize_for_log
logger.info(f"Input: {sanitize_for_log(user_input)}")

# Avoid (log injection risk)
logger.info(f"Input: {user_input}")
```

---

## Testing Your Changes

### Validation
```python
# Test validation
from app.validation import validate_task_id, ValidationError
import pytest

def test_valid_uuid():
    result = validate_task_id("550e8400-e29b-41d4-a716-446655440000")
    assert result == "550e8400-e29b-41d4-a716-446655440000"

def test_invalid_uuid():
    with pytest.raises(ValidationError):
        validate_task_id("invalid")
```

### Rate Limiting
```python
# Test rate limiter
from app.rate_limiter import RateLimiter
from app.exceptions import RateLimitError

def test_rate_limit():
    limiter = RateLimiter(redis_client)
    
    # Should succeed first time
    limiter.check_rate_limit("test", max_requests=1, window_seconds=60)
    
    # Should fail second time
    with pytest.raises(RateLimitError):
        limiter.check_rate_limit("test", max_requests=1, window_seconds=60)
```

---

## Troubleshooting

### Issue: Validation errors on valid data
**Solution**: Check that data format matches expected format (e.g., UUID lowercase)

### Issue: Rate limiting not working
**Solution**: Ensure Redis is connected and accessible

### Issue: Logs not appearing
**Solution**: Check LOG_LEVEL environment variable

### Issue: CORS errors
**Solution**: Update CORS_ORIGINS environment variable

---

## Migration Checklist

- [ ] Update imports to use new constants
- [ ] Add validation to all user inputs
- [ ] Replace print statements with proper logging
- [ ] Use custom exceptions instead of generic Exception
- [ ] Sanitize all logged user input
- [ ] Add rate limiting to public endpoints
- [ ] Update environment variables
- [ ] Test error handling paths
- [ ] Review security with CodeQL
- [ ] Update documentation
