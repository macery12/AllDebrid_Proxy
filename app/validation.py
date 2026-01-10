# Input validation and sanitization functions
# Provides security against common attacks like path traversal, SQL injection, etc

import re
import os
from typing import Optional
from pathlib import Path
from app.constants import Patterns, Limits
from app.exceptions import ValidationError


def validate_task_id(task_id: str) -> str:
    # Validate task ID format (UUID)
    # Args: task_id - Task identifier to validate
    # Returns: Validated task ID
    # Raises: ValidationError if task ID is invalid
    if not task_id:
        raise ValidationError("Task ID is required")
    
    # UUID format: 8-4-4-4-12 hex digits
    if not re.match(Patterns.UUID_PATTERN, task_id, re.IGNORECASE):
        raise ValidationError("Invalid task ID format")
    
    return task_id.lower()


def validate_magnet_link(magnet: str) -> str:
    # Validate magnet link format
    # Args: magnet - Magnet link to validate
    # Returns: Validated magnet link
    # Raises: ValidationError if magnet link is invalid
    if not magnet:
        raise ValidationError("Magnet link is required")
    
    if not isinstance(magnet, str):
        raise ValidationError("Magnet link must be a string")
    
    # Check length
    if len(magnet) > Limits.MAX_MAGNET_LENGTH:
        raise ValidationError("Magnet link is too long")
    
    # Must start with magnet:
    if not magnet.startswith("magnet:"):
        raise ValidationError("Invalid magnet link format")
    
    # Must contain xt parameter with btih
    if "xt=urn:btih:" not in magnet.lower():
        raise ValidationError("Magnet link missing info hash")
    
    return magnet


def validate_file_path(file_path: str, base_dir: str) -> str:
    # Validate and sanitize file path to prevent directory traversal attacks
    # Args: file_path - File path to validate, base_dir - Base directory that file must be within
    # Returns: Validated absolute file path
    # Raises: ValidationError if path is invalid or attempts traversal
    if not file_path:
        raise ValidationError("File path is required")
    
    # Check length
    if len(file_path) > Limits.MAX_PATH_LENGTH:
        raise ValidationError("File path is too long")
    
    # Resolve to absolute path
    try:
        abs_path = os.path.abspath(os.path.join(base_dir, file_path))
        abs_base = os.path.abspath(base_dir)
    except Exception as e:
        raise ValidationError(f"Invalid file path: {e}")
    
    # Ensure the resolved path is within base_dir (prevent traversal)
    if not abs_path.startswith(abs_base):
        raise ValidationError("Path traversal detected")
    
    # Check for null bytes
    if '\x00' in file_path:
        raise ValidationError("Null byte in file path")
    
    return abs_path


def validate_file_name(file_name: str) -> str:
    # Validate and sanitize file name
    # Args: file_name - File name to validate
    # Returns: Validated file name
    # Raises: ValidationError if file name is invalid
    if not file_name:
        raise ValidationError("File name is required")
    
    # Check length
    if len(file_name) > Limits.MAX_FILENAME_LENGTH:
        raise ValidationError("File name is too long")
    
    # Check for path separators (security)
    if '/' in file_name or '\\' in file_name:
        raise ValidationError("File name cannot contain path separators")
    
    # Check for null bytes
    if '\x00' in file_name:
        raise ValidationError("Null byte in file name")
    
    # Check for control characters
    if any(ord(c) < 32 for c in file_name):
        raise ValidationError("File name contains control characters")
    
    # Reject dangerous names
    dangerous = ['.', '..', 'CON', 'PRN', 'AUX', 'NUL', 'COM1', 'COM2', 'COM3', 
                 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9', 'LPT1', 'LPT2', 
                 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9']
    if file_name.upper() in dangerous:
        raise ValidationError("Reserved file name")
    
    return file_name


def validate_label(label: Optional[str]) -> Optional[str]:
    # Validate task label
    # Args: label - Label to validate
    # Returns: Validated label or None
    # Raises: ValidationError if label is invalid
    if label is None:
        return None
    
    if not isinstance(label, str):
        raise ValidationError("Label must be a string")
    
    # Check length
    if len(label) > Limits.MAX_LABEL_LENGTH:
        raise ValidationError(f"Label exceeds maximum length of {Limits.MAX_LABEL_LENGTH}")
    
    # Remove control characters
    label = ''.join(c for c in label if ord(c) >= 32)
    
    return label.strip() if label.strip() else None


def validate_infohash(infohash: str) -> str:
    # Validate BitTorrent info hash
    # Args: infohash - Info hash to validate
    # Returns: Validated lowercase info hash
    # Raises: ValidationError if info hash is invalid
    if not infohash:
        raise ValidationError("Info hash is required")
    
    # SHA-1 hash (40 hex chars) or base32 (32 chars)
    if len(infohash) == 40:
        if not re.match(r'^[0-9a-fA-F]{40}$', infohash):
            raise ValidationError("Invalid SHA-1 info hash format")
    elif len(infohash) == 32:
        if not re.match(r'^[A-Z2-7]{32}$', infohash, re.IGNORECASE):
            raise ValidationError("Invalid base32 info hash format")
    else:
        raise ValidationError("Info hash must be 40 hex or 32 base32 characters")
    
    return infohash.lower()


def validate_positive_int(value: int, name: str = "value", max_value: Optional[int] = None) -> int:
    # Validate positive integer
    # Args: value - Integer to validate, name - Name of the value (for error messages), max_value - Optional maximum value
    # Returns: Validated integer
    # Raises: ValidationError if value is invalid
    if not isinstance(value, int):
        raise ValidationError(f"{name} must be an integer")
    
    if value < 0:
        raise ValidationError(f"{name} must be non-negative")
    
    if max_value is not None and value > max_value:
        raise ValidationError(f"{name} exceeds maximum value of {max_value}")
    
    return value


def sanitize_for_log(value: str, max_length: int = 200) -> str:
    # Sanitize string for safe logging (prevent log injection)
    # Args: value - String to sanitize, max_length - Maximum length for logged value
    # Returns: Sanitized string
    if not isinstance(value, str):
        value = str(value)
    
    # Remove newlines and control characters
    sanitized = ''.join(c if ord(c) >= 32 else ' ' for c in value)
    
    # Truncate if too long
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length] + "..."
    
    return sanitized


def validate_url(url: str) -> str:
    # Validate URL format
    # Args: url - URL to validate
    # Returns: Validated URL
    # Raises: ValidationError if URL is invalid
    if not url:
        raise ValidationError("URL is required")
    
    # Must start with http:// or https://
    if not url.startswith(('http://', 'https://')):
        raise ValidationError("URL must start with http:// or https://")
    
    # Check length
    if len(url) > Limits.MAX_URL_LENGTH:
        raise ValidationError("URL is too long")
    
    # Check for dangerous characters
    if any(c in url for c in ['\r', '\n', '\x00']):
        raise ValidationError("URL contains invalid characters")
    
    return url


def validate_source(source: str) -> tuple[str, str]:
    """
    Validate source (either magnet link or HTTP/HTTPS URL).
    
    Args:
        source - Source string to validate (magnet or URL)
        
    Returns:
        Tuple of (validated_source, source_type) where source_type is 'magnet' or 'link'
        
    Raises:
        ValidationError if source is invalid
    """
    from app.constants import SourceType
    
    if not source:
        raise ValidationError("Source is required")
    
    if not isinstance(source, str):
        raise ValidationError("Source must be a string")
    
    source = source.strip()
    
    # Check if it's a magnet link
    if source.startswith("magnet:"):
        validated = validate_magnet_link(source)
        return (validated, SourceType.MAGNET)
    
    # Check if it's a URL
    if source.startswith(('http://', 'https://')):
        validated = validate_url(source)
        return (validated, SourceType.LINK)
    
    # Neither magnet nor URL
    raise ValidationError("Source must be a magnet link (magnet:) or HTTP/HTTPS URL")


def validate_sources(sources: str) -> list[tuple[str, str]]:
    """
    Validate multiple sources (magnets or URLs), one per line.
    
    Args:
        sources - Multi-line string with sources (magnets or URLs)
        
    Returns:
        List of tuples (validated_source, source_type) where source_type is 'magnet' or 'link'
        
    Raises:
        ValidationError if any source is invalid
    """
    if not sources:
        raise ValidationError("At least one source is required")
    
    # Split by newlines and filter empty lines
    lines = [line.strip() for line in sources.split('\n') if line.strip()]
    
    if not lines:
        raise ValidationError("At least one source is required")
    
    # Limit number of sources
    if len(lines) > Limits.MAX_SOURCES_PER_SUBMISSION:
        raise ValidationError(f"Too many sources (maximum {Limits.MAX_SOURCES_PER_SUBMISSION})")
    
    validated_sources = []
    errors = []
    
    for i, line in enumerate(lines, 1):
        try:
            validated_source, source_type = validate_source(line)
            validated_sources.append((validated_source, source_type))
        except ValidationError as e:
            errors.append(f"Line {i}: {str(e)}")
    
    if errors:
        raise ValidationError("Invalid sources:\n" + "\n".join(errors))
    
    return validated_sources


def validate_torrent_file_data(file_data: bytes, filename: str) -> None:
    """
    Validate torrent file data.
    
    Args:
        file_data - Raw bytes of torrent file
        filename - Name of the uploaded file
        
    Raises:
        ValidationError if torrent file is invalid
    """
    if not file_data:
        raise ValidationError("Torrent file is empty")
    
    # Check file size
    if len(file_data) > Limits.MAX_TORRENT_FILE_SIZE:
        raise ValidationError(f"Torrent file is too large (maximum {Limits.MAX_TORRENT_FILE_SIZE // 1024 // 1024}MB)")
    
    # Check file extension
    if not filename.lower().endswith('.torrent'):
        raise ValidationError("File must have .torrent extension")
    
    # Basic check for bencode format (should start with 'd')
    if not file_data.startswith(b'd'):
        raise ValidationError("Invalid torrent file format (not bencoded)")
    
    # Try to decode it
    try:
        import bencodepy
        torrent_dict = bencodepy.decode(file_data)
        
        # Verify it has the required 'info' key
        if b'info' not in torrent_dict:
            raise ValidationError("Invalid torrent file: missing 'info' dictionary")
    except ImportError:
        raise ValidationError("Torrent parsing library not available")
    except ValidationError:
        raise
    except Exception as e:
        raise ValidationError(f"Invalid torrent file: {str(e)}")
