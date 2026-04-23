import re, os, shutil, json, time, hashlib, io
from typing import Optional
from app.validation import validate_infohash
from app.constants import Patterns

try:
    import torf as _torf
    HAS_TORF = True
except ImportError:
    HAS_TORF = False

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
    # Only strip whitespace - preserve case for path and query parameters
    normalized_url = url.strip()
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
    from app.constants import SourceType
    
    if source_type == SourceType.MAGNET:
        infohash = parse_infohash(source)
        if not infohash:
            raise ValueError("Could not extract infohash from magnet link")
        return infohash
    elif source_type == SourceType.LINK:
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


def torrent_to_magnet(torrent_data: bytes) -> str:
    """
    Convert torrent file data to magnet link.
    
    Args:
        torrent_data: Raw bytes of a .torrent file
        
    Returns:
        Magnet link string with info hash and trackers
        
    Raises:
        ValueError: If torrent data is invalid or cannot be parsed
    """
    if not HAS_TORF:
        raise ValueError("torf library is required to parse torrent files")
    
    try:
        torrent = _torf.Torrent.read_stream(io.BytesIO(torrent_data), validate=False)
    except Exception as e:
        raise ValueError(f"Failed to decode torrent file: {e}")
    
    if not torrent.infohash:
        raise ValueError("Invalid torrent file: could not compute infohash")
    
    return str(torrent.magnet())
