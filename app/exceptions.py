# Custom exception hierarchy for better error handling and security

from typing import Optional, Dict, Any


class AppException(Exception):
    # Base exception for all application errors
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        self.message = message
        self.details = details or {}
        super().__init__(self.message)


class ValidationError(AppException):
    # Raised when input validation fails
    pass


class AuthenticationError(AppException):
    # Raised when authentication fails
    pass


class AuthorizationError(AppException):
    # Raised when user lacks required permissions
    pass


class ResourceNotFoundError(AppException):
    # Raised when a requested resource is not found
    pass


class StorageError(AppException):
    # Raised when storage operations fail
    pass


class ProviderError(AppException):
    # Raised when debrid provider operations fail
    pass


class TaskError(AppException):
    # Raised when task operations fail
    pass


class WorkerError(AppException):
    # Raised when worker operations fail
    pass


class RateLimitError(AppException):
    # Raised when rate limit is exceeded
    pass


class ConfigurationError(AppException):
    # Raised when configuration is invalid
    pass
