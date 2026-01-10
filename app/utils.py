import re, os, shutil, json, time, hashlib
from typing import Optional
from app.validation import validate_infohash
from app.constants import Patterns

def parse_infohash(magnet: str) -> Optional[str]:
    """
    Parse and validate info hash from magnet link.
    
    Args:
        magnet: Magnet link string
        
    Returns:
        Lowercase info hash or None if not found
    """
    m = re.search(Patterns.MAGNET_BTIH, magnet, re.IGNORECASE)
    if not m:
        return None
    
    infohash = m.group(1).lower()
    
    # Validate the extracted hash
    try:
        return validate_infohash(infohash)
    except Exception:
        return None


def generate_link_hash(url: str) -> str:
    """
    Generate a consistent hash for a URL to use as an identifier.
    
    Args:
        url: URL string
        
    Returns:
        SHA-1 hash (40 hex characters) of the URL
    """
    # Normalize URL for consistent hashing
    normalized_url = url.strip().lower()
    return hashlib.sha1(normalized_url.encode('utf-8')).hexdigest()


def parse_source_identifier(source: str, source_type: str) -> str:
    """
    Extract or generate a unique identifier for a source.
    
    Args:
        source: Source string (magnet or URL)
        source_type: Type of source ('magnet' or 'link')
        
    Returns:
        Unique identifier (infohash for magnets, URL hash for links)
    """
    if source_type == "magnet":
        infohash = parse_infohash(source)
        if not infohash:
            raise ValueError("Could not extract infohash from magnet link")
        return infohash
    elif source_type == "link":
        return generate_link_hash(source)
    else:
        raise ValueError(f"Unknown source type: {source_type}")

def ensure_task_dirs(storage_root: str, task_id: str):
    """
    Create task directories and initialize metadata files.
    
    Args:
        storage_root: Root storage directory
        task_id: Task identifier
        
    Returns:
        Tuple of (base_dir, files_dir)
    """
    # Validate task_id to prevent directory traversal
    from app.validation import validate_task_id
    task_id = validate_task_id(task_id)
    
    base = os.path.join(storage_root, task_id)
    files = os.path.join(base, "files")
    os.makedirs(files, exist_ok=True)
    for f in ["metadata.json", "logs.json"]:
        p = os.path.join(base, f)
        if not os.path.exists(p):
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("{}\n")
    return base, files

def disk_free_bytes(path: str) -> int:
    """
    Get free disk space in bytes.
    
    Args:
        path: Path to check
        
    Returns:
        Free space in bytes
    """
    try:
        usage = shutil.disk_usage(path)
        return usage.free
    except Exception:
        # Return 0 on error to be safe
        return 0

def append_log(base: str, entry: dict):
    """
    Append log entry to task log file.
    
    Args:
        base: Base directory for task
        entry: Log entry dictionary
    """
    p = os.path.join(base, "logs.json")
    entry = dict(entry)
    entry.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    
    # Sanitize log entry values to prevent log injection
    from app.validation import sanitize_for_log
    sanitized_entry = {}
    for key, value in entry.items():
        if isinstance(value, str):
            sanitized_entry[key] = sanitize_for_log(value)
        else:
            sanitized_entry[key] = value
    
    try:
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(sanitized_entry) + "\n")
    except Exception:
        # Don't fail if logging fails
        pass

def write_metadata(base: str, data: dict):
    """
    Write metadata to task metadata file.
    
    Args:
        base: Base directory for task
        data: Metadata dictionary
    """
    p = os.path.join(base, "metadata.json")
    try:
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
    except Exception:
        # Don't fail if metadata write fails
        pass
