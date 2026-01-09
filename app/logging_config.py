"""
Centralized logging configuration.
Provides structured logging with proper formatting and security considerations.
"""

import logging
import sys
import json
from typing import Any, Dict
from datetime import datetime


class StructuredFormatter(logging.Formatter):
    """
    JSON formatter for structured logging.
    Makes logs easier to parse and analyze.
    """
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON"""
        log_data: Dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        
        # Add extra fields if present
        if hasattr(record, "task_id"):
            log_data["task_id"] = record.task_id
        if hasattr(record, "user_id"):
            log_data["user_id"] = record.user_id
        if hasattr(record, "file_id"):
            log_data["file_id"] = record.file_id
        
        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        # Add any extra fields from the log record
        for key, value in record.__dict__.items():
            if key not in ["name", "msg", "args", "created", "filename", "funcName", 
                          "levelname", "levelno", "lineno", "module", "msecs", 
                          "message", "pathname", "process", "processName", "relativeCreated",
                          "thread", "threadName", "exc_info", "exc_text", "stack_info",
                          "task_id", "user_id", "file_id"]:
                log_data[key] = value
        
        return json.dumps(log_data, default=str)


class SimpleFormatter(logging.Formatter):
    """
    Simple human-readable formatter for development.
    """
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record as simple text"""
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        level = record.levelname
        logger = record.name
        message = record.getMessage()
        
        result = f"{timestamp} {level:8} [{logger}] {message}"
        
        # Add context if present
        context_parts = []
        if hasattr(record, "task_id"):
            context_parts.append(f"task={record.task_id}")
        if hasattr(record, "user_id"):
            context_parts.append(f"user={record.user_id}")
        if hasattr(record, "file_id"):
            context_parts.append(f"file={record.file_id}")
        
        if context_parts:
            result += f" [{', '.join(context_parts)}]"
        
        # Add exception if present
        if record.exc_info:
            result += "\n" + self.formatException(record.exc_info)
        
        return result


def setup_logging(
    level: str = "INFO",
    structured: bool = False,
    logger_name: str = None
) -> logging.Logger:
    """
    Configure logging for the application.
    
    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        structured: Use JSON structured logging if True, simple format if False
        logger_name: Name of logger to configure (None for root logger)
    
    Returns:
        Configured logger instance
    """
    # Get or create logger
    logger = logging.getLogger(logger_name)
    
    # Set level
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    
    # Remove existing handlers to avoid duplicates
    logger.handlers.clear()
    
    # Create console handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logger.level)
    
    # Set formatter
    if structured:
        formatter = StructuredFormatter()
    else:
        formatter = SimpleFormatter()
    
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    
    return logger


def get_logger(name: str, **context) -> "LoggerAdapter":
    """
    Get a logger with optional context.
    
    Args:
        name: Logger name
        **context: Additional context to include in all log messages
    
    Returns:
        Logger adapter with context
    """
    logger = logging.getLogger(name)
    return LoggerAdapter(logger, context)


class LoggerAdapter(logging.LoggerAdapter):
    """
    Logger adapter that adds context to log records.
    """
    
    def process(self, msg, kwargs):
        """Add context to log record"""
        # Merge extra context
        extra = kwargs.get("extra", {})
        extra.update(self.extra)
        kwargs["extra"] = extra
        return msg, kwargs


# Convenience functions for common logging patterns

def log_api_request(logger: logging.Logger, method: str, path: str, **extra):
    """Log API request"""
    logger.info(
        f"{method} {path}",
        extra={"event": "api_request", "method": method, "path": path, **extra}
    )


def log_api_response(logger: logging.Logger, method: str, path: str, status_code: int, **extra):
    """Log API response"""
    logger.info(
        f"{method} {path} -> {status_code}",
        extra={"event": "api_response", "method": method, "path": path, 
               "status_code": status_code, **extra}
    )


def log_task_event(logger: logging.Logger, task_id: str, event: str, **extra):
    """Log task-related event"""
    logger.info(
        f"Task {task_id}: {event}",
        extra={"event": "task_event", "task_id": task_id, "task_event": event, **extra}
    )


def log_worker_event(logger: logging.Logger, event: str, **extra):
    """Log worker-related event"""
    logger.info(
        f"Worker: {event}",
        extra={"event": "worker_event", "worker_event": event, **extra}
    )


def log_error(logger: logging.Logger, error: Exception, **extra):
    """Log error with exception details"""
    logger.error(
        f"Error: {type(error).__name__}: {str(error)}",
        exc_info=error,
        extra={"event": "error", "error_type": type(error).__name__, **extra}
    )
