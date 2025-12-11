"""Utility functions for task management, storage, and logging."""

import re
import os
import shutil
import json
import time
from typing import Optional, Tuple, Dict, Any

# Regex pattern to extract BitTorrent infohash from magnet links
# Matches both hex (40 chars) and base32 (32 chars) formats
MAGNET_RE = re.compile(
    r'btih:([0-9A-Fa-f]{40}|[A-Z2-7]{32})',
    re.IGNORECASE
)

def parse_infohash(magnet: str) -> Optional[str]:
    """
    Extract the infohash from a magnet link.
    
    Args:
        magnet: A magnet link string (e.g., "magnet:?xt=urn:btih:...")
        
    Returns:
        The infohash in lowercase if found, None otherwise.
        
    Example:
        >>> parse_infohash("magnet:?xt=urn:btih:ABC123...")
        "abc123..."
    """
    m = MAGNET_RE.search(magnet)
    if not m:
        return None
    return m.group(1).lower()

def ensure_task_dirs(storage_root: str, task_id: str) -> Tuple[str, str]:
    """
    Create task directory structure and initialize metadata files.
    
    Creates:
        - {storage_root}/{task_id}/
        - {storage_root}/{task_id}/files/
        - {storage_root}/{task_id}/metadata.json (if not exists)
        - {storage_root}/{task_id}/logs.json (if not exists)
    
    Args:
        storage_root: Root directory for all task storage
        task_id: Unique task identifier (typically UUID)
        
    Returns:
        Tuple of (base_path, files_path) where:
            - base_path is {storage_root}/{task_id}
            - files_path is {storage_root}/{task_id}/files
            
    Raises:
        OSError: If directory creation fails
    """
    base = os.path.join(storage_root, task_id)
    files = os.path.join(base, "files")
    os.makedirs(files, exist_ok=True)
    
    # Initialize metadata and log files if they don't exist
    for f in ["metadata.json", "logs.json"]:
        p = os.path.join(base, f)
        if not os.path.exists(p):
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("{}\n")
    
    return base, files

def disk_free_bytes(path: str) -> int:
    """
    Get available disk space in bytes for the given path.
    
    Args:
        path: File system path to check
        
    Returns:
        Number of free bytes available
        
    Raises:
        OSError: If path doesn't exist or is inaccessible
    """
    usage = shutil.disk_usage(path)
    return usage.free

def append_log(base: str, entry: Dict[str, Any]) -> None:
    """
    Append a log entry to the task's log file.
    
    Automatically adds a timestamp if not present.
    Each entry is written as a single line of JSON.
    
    Args:
        base: Task base directory path
        entry: Dictionary containing log data (must be JSON-serializable)
        
    Example:
        >>> append_log("/srv/storage/task-123", {
        ...     "level": "info",
        ...     "event": "download_started",
        ...     "file": "movie.mkv"
        ... })
    """
    p = os.path.join(base, "logs.json")
    entry = dict(entry)
    entry.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")

def write_metadata(base: str, data: Dict[str, Any]) -> None:
    """
    Write task metadata to the metadata.json file.
    
    Overwrites existing metadata file.
    
    Args:
        base: Task base directory path
        data: Dictionary containing metadata (must be JSON-serializable)
        
    Example:
        >>> write_metadata("/srv/storage/task-123", {
        ...     "taskId": "task-123",
        ...     "mode": "auto",
        ...     "status": "downloading"
        ... })
    """
    p = os.path.join(base, "metadata.json")
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
