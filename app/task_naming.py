"""
task_naming.py — Human-friendly task name generation.

Priority order for name generation:
  1. Explicit user-provided label
  2. Torrent/job name (from magnet dn= param or parsed .torrent metadata)
  3. Folder name derived from multi-file torrent
  4. First meaningful filename
  5. URL-derived filename (for direct link sources)
  6. Short task-ID fallback (e.g. "Task-a3f2b1c4")

Names are normalised so they are:
  - Free of local filesystem paths
  - Free of unsafe / shell-special characters
  - Collapsed so repeated separators become a single dot
  - Trimmed to MAX_TASK_NAME_LENGTH characters
"""

import re
from typing import Optional, List
from urllib.parse import unquote_plus, urlparse

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_TASK_NAME_LENGTH = 120

# Characters we keep: alphanumeric, space, dot, hyphen, underscore, parens, brackets
_ALLOWED = re.compile(r"[^\w\s.\-_()\[\]]")

# Two or more consecutive separator-like characters → collapse to a single dot
_MULTI_SEP = re.compile(r"[\s._\-]{2,}")

# Detect absolute paths (Windows drive letters or Unix root)
_ABS_PATH_PREFIX = re.compile(r"^[A-Za-z]:[/\\]|^/")

# Media-quality / edition tags to preserve during normalisation
# (kept for reference – they survive because they match \w or brackets)
_QUALITY_TAGS = re.compile(
    r"\b(1080p|720p|2160p|4K|HDR|SDR|BluRay|WEB[-.]?DL|WEBRip|HDTV|x264|x265|HEVC|AAC|AC3|DTS|"
    r"S\d{2}E\d{2}|S\d{2}|E\d{2}|[Ss]eason\s*\d+|[Ee]pisode\s*\d+)\b"
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _strip_path_prefix(name: str) -> str:
    """If *name* looks like an absolute filesystem path, return only the last component."""
    if _ABS_PATH_PREFIX.match(name):
        # Split on both POSIX and Windows separators
        parts = re.split(r"[/\\]", name.rstrip("/\\"))
        name = parts[-1] if parts else name
    return name


def _normalize(name: str) -> str:
    """
    Normalise *name* into a clean, human-friendly task name.

    Steps:
      1. Remove filesystem path prefixes.
      2. Replace path separators with spaces.
      3. Strip unsafe / shell-special characters.
      4. Collapse repeated separator characters.
      5. Strip leading / trailing separator characters.
      6. Enforce MAX_TASK_NAME_LENGTH.
    """
    if not name:
        return ""

    # 1. Drop filesystem path prefix, keeping only the last component
    name = _strip_path_prefix(name)

    # 2. Replace path separators with a space so we don't lose word boundaries
    name = name.replace("/", " ").replace("\\", " ")

    # 3. Remove characters that aren't alphanumeric, space, dot, hyphen,
    #    underscore, parentheses, or brackets.
    name = _ALLOWED.sub("", name)

    # 4. Collapse two-or-more consecutive separator chars into a single dot
    name = _MULTI_SEP.sub(".", name)

    # 5. Strip leading / trailing separators
    name = name.strip(" ._-")

    # 6. Enforce maximum length (back-off cleanly on separator)
    if len(name) > MAX_TASK_NAME_LENGTH:
        name = name[:MAX_TASK_NAME_LENGTH].rstrip(" ._-")

    return name


def _extract_magnet_dn(magnet: str) -> Optional[str]:
    """Return the decoded *dn=* display-name from a magnet URI, or *None*."""
    m = re.search(r"[?&]dn=([^&]+)", magnet, re.IGNORECASE)
    if m:
        return unquote_plus(m.group(1))
    return None


def _extract_url_filename(url: str) -> Optional[str]:
    """
    Return the last path component of *url* as a candidate filename.
    Only returned when the component looks like a real filename (has a dot).
    """
    try:
        path = urlparse(url).path
        if path:
            component = path.rstrip("/").rsplit("/", 1)[-1]
            decoded = unquote_plus(component)
            if decoded and "." in decoded:
                return decoded
    except Exception:
        pass
    return None


def _best_filename(filenames: List[str]) -> Optional[str]:
    """
    Pick the most meaningful name from a list of filenames.

    Preference:
      • Longer names (more informative) over shorter ones.
      • Ignore names that look like bare hash strings or UUIDs.
    """
    _HASH_RE = re.compile(r"^[0-9a-f]{32,}$", re.IGNORECASE)
    _UUID_RE = re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        re.IGNORECASE,
    )

    best: Optional[str] = None
    best_len = 0

    for raw in filenames:
        if not raw:
            continue
        # Get just the last path component
        parts = re.split(r"[/\\]", raw.rstrip("/\\"))
        basename = parts[-1] if parts else raw
        if not basename or len(basename) <= 3:
            continue
        # Skip hash-looking names
        stem = re.sub(r"\.[^.]+$", "", basename)  # strip extension
        if _HASH_RE.match(stem) or _UUID_RE.match(stem):
            continue
        if len(basename) > best_len:
            best = basename
            best_len = len(basename)

    return best


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_task_name(
    source: str,
    *,
    label: Optional[str] = None,
    torrent_name: Optional[str] = None,
    filenames: Optional[List[str]] = None,
    task_id: Optional[str] = None,
    source_type: str = "magnet",
) -> str:
    """
    Generate a human-friendly task name from available metadata.

    Args:
        source:       Raw source string (magnet URI or direct URL).
        label:        Explicit user-provided label (highest priority).
        torrent_name: Name extracted from .torrent *info.name* field.
        filenames:    List of file paths/names returned by the provider.
        task_id:      UUID of the task (used for the fallback name).
        source_type:  "magnet" or "link".

    Returns:
        A normalised, human-friendly string suitable for display.
        Never returns an empty string.
    """
    candidates: List[str] = []

    # 1. Explicit label (user-provided)
    if label:
        candidates.append(label)

    # 2. Torrent/job name from metadata
    if torrent_name:
        candidates.append(torrent_name)

    # 3. Display name embedded in the magnet URI  /  URL filename
    if source_type == "magnet":
        dn = _extract_magnet_dn(source)
        if dn:
            candidates.append(dn)
    elif source_type == "link":
        url_name = _extract_url_filename(source)
        if url_name:
            candidates.append(url_name)

    # 4. First meaningful filename from the file list
    if filenames:
        best = _best_filename(filenames)
        if best:
            candidates.append(best)

    # Try each candidate in priority order
    for raw in candidates:
        normalised = _normalize(raw)
        if normalised:
            return normalised

    # 5. Safe fallback: short task-ID prefix
    if task_id:
        short = task_id.replace("-", "")[:8]
        return f"Task-{short}"

    return "Unnamed-Task"
