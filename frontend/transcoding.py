"""
Transcoding pipeline for browser-incompatible media formats.

Uses ffmpeg to convert media to HLS (HTTP Live Streaming) so browsers
can seek and play formats they wouldn't normally support (e.g. MKV, AVI).

Design principles:
- Direct playback is always preferred; transcoding is opt-in/auto-fallback.
- Jobs are tracked in-memory with a stable deterministic ID so re-visits
  don't restart a transcode that is already running or done.
- Concurrency is bounded by MAX_CONCURRENT_TRANSCODES to limit CPU usage.
- A /proc/loadavg check adds a second safety gate on busy servers.
- HLS segments are written progressively by ffmpeg — the player can start
  as soon as MIN_SEGMENTS_TO_PLAY segments are ready, without waiting for
  the full transcode to complete (live/progressive streaming).
- Completed jobs and their HLS output are purged after TRANSCODE_TTL_HOURS.
"""

import hashlib
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger("ad-transcoder")

# ---------------------------------------------------------------------------
# Configuration (from environment)
# ---------------------------------------------------------------------------
FFMPEG_BIN: str = os.environ.get("FFMPEG_BIN", "ffmpeg")
TRANSCODE_ROOT: Path = Path(os.environ.get("STORAGE_ROOT", "/srv/storage")) / "transcodes"
MAX_CONCURRENT_TRANSCODES: int = max(1, int(os.environ.get("MAX_CONCURRENT_TRANSCODES", "2")))
TRANSCODE_TTL_SECONDS: int = max(300, int(os.environ.get("TRANSCODE_TTL_HOURS", "4")) * 3600)
CPU_LOAD_LIMIT: float = max(0.1, float(os.environ.get("TRANSCODE_MAX_LOAD", "3.0")))

# Number of completed .ts segments before the player may start.
# Each segment is 6 s → 2 segments = 12 s of pre-buffered content.
MIN_SEGMENTS_TO_PLAY: int = 2

# ---------------------------------------------------------------------------
# Media extension sets
# ---------------------------------------------------------------------------

# Formats that modern browsers can play without transcoding.
# Note: .mp4/.m4v needs H.264/AAC inside – we give it the benefit of the
# doubt and let the browser report an error if the codec is unsupported.
BROWSER_NATIVE_EXTENSIONS: frozenset = frozenset({
    ".mp4", ".m4v",
    ".webm",
    ".ogv",
    ".mp3",
    ".ogg",
    ".wav",
    ".m4a",
    ".flac",
})

# All extensions the player page should accept (native + can-be-transcoded).
ALL_MEDIA_EXTENSIONS: frozenset = BROWSER_NATIVE_EXTENSIONS | frozenset({
    ".mkv", ".avi", ".mov", ".wmv", ".flv",
    ".mpg", ".mpeg", ".3gp", ".ts", ".vob",
    ".divx", ".xvid",
    ".aac", ".ac3", ".dts", ".wma", ".opus",
})

# ---------------------------------------------------------------------------
# ffmpeg availability cache
# ---------------------------------------------------------------------------
_ffmpeg_cache: tuple = (None, 0.0)  # (result: Optional[bool], timestamp: float)
_FFMPEG_CACHE_TTL = 60.0  # seconds between re-checks


def _probe_ffmpeg() -> bool:
    """Run ``ffmpeg -version`` to confirm the binary works."""
    try:
        result = subprocess.run(
            [FFMPEG_BIN, "-version"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def ffmpeg_available() -> bool:
    """Return True if ffmpeg is reachable (cached for 60 s)."""
    global _ffmpeg_cache
    cached_result, ts = _ffmpeg_cache
    if cached_result is None or (time.monotonic() - ts) > _FFMPEG_CACHE_TTL:
        cached_result = _probe_ffmpeg()
        _ffmpeg_cache = (cached_result, time.monotonic())
    return cached_result


# ---------------------------------------------------------------------------
# System load
# ---------------------------------------------------------------------------

def get_system_load() -> float:
    """Return the 1-minute load average (Linux). Returns 0.0 on any error."""
    try:
        with open("/proc/loadavg") as fh:
            return float(fh.read().split()[0])
    except Exception:
        return 0.0


def is_overloaded() -> bool:
    """True if the server load is above the configured ceiling."""
    return get_system_load() > CPU_LOAD_LIMIT


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def is_browser_compatible(filename: str) -> bool:
    """True if the browser should be able to play this file without transcoding."""
    return Path(filename).suffix.lower() in BROWSER_NATIVE_EXTENSIONS


def is_media_file(filename: str) -> bool:
    """True if this file is a playable media type (native or transcodable)."""
    return Path(filename).suffix.lower() in ALL_MEDIA_EXTENSIONS


# ---------------------------------------------------------------------------
# Job registry
# ---------------------------------------------------------------------------
_jobs: Dict[str, Dict[str, Any]] = {}
_jobs_lock = threading.Lock()
_semaphore = threading.Semaphore(MAX_CONCURRENT_TRANSCODES)


def active_job_count() -> int:
    """Number of jobs currently queued or transcoding."""
    with _jobs_lock:
        return sum(
            1 for j in _jobs.values()
            if j["status"] in ("queued", "transcoding")
        )


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Return a shallow copy of the job record or None."""
    with _jobs_lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None


def job_id_for(task_id: str, relpath: str) -> str:
    """Stable deterministic job ID for a (task, file) pair."""
    key = f"{task_id}:{relpath}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Transcoding thread
# ---------------------------------------------------------------------------

def _parse_time_progress(line: str) -> Optional[float]:
    """Parse an HH:MM:SS.ss time string from an ffmpeg progress line."""
    m = re.search(r"time=(\d+):(\d+):([\d.]+)", line)
    if m:
        h, mn, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
        return h * 3600 + mn * 60 + s
    return None


def _count_segments(output_dir: Path) -> int:
    """Count completed .ts segment files in *output_dir*."""
    try:
        return sum(1 for _ in output_dir.glob("seg*.ts"))
    except OSError:
        return 0


def _run_transcode(job_id: str, source: Path, output_dir: Path) -> None:
    """
    Background thread that runs ffmpeg and updates the shared job dict.
    Acquires the semaphore to enforce MAX_CONCURRENT_TRANSCODES.

    Segments are written progressively by ffmpeg.  The job is marked
    ``playable`` as soon as MIN_SEGMENTS_TO_PLAY segments exist on disk,
    so the browser player can start without waiting for the full transcode.
    """
    with _semaphore:
        with _jobs_lock:
            if job_id not in _jobs:
                return  # job was removed before we started
            playlist = output_dir / "index.m3u8"
            _jobs[job_id]["status"] = "transcoding"
            _jobs[job_id]["started_at"] = time.time()
            # Expose the playlist path immediately so serve_hls can find it
            # before transcoding completes.
            _jobs[job_id]["playlist"] = str(playlist)

        output_dir.mkdir(parents=True, exist_ok=True)

        # Transcode to HLS with H.264/AAC for maximum browser compatibility.
        # Key flags:
        #   -hls_list_size 0          keep ALL segments in the playlist
        #   -hls_flags append_list    append new segments as they are written
        #                             (no delete_segments — we keep all for seeking)
        # Without #EXT-X-ENDLIST the HLS parser treats the playlist as a live
        # stream, re-fetching it periodically. ffmpeg only writes that tag when
        # muxing is complete, so the browser automatically switches to VOD mode.
        cmd = [
            FFMPEG_BIN,
            "-hide_banner", "-loglevel", "warning", "-stats",
            "-i", str(source),
            # Video stream
            "-c:v", "libx264",
            "-profile:v", "baseline",
            "-level", "3.1",
            "-preset", "veryfast",
            "-crf", "23",
            "-vf", "scale='min(1920,iw)':-2",
            # Audio stream
            "-c:a", "aac",
            "-b:a", "128k",
            "-ac", "2",
            # HLS muxer — keep all segments, append-only playlist
            "-f", "hls",
            "-hls_time", "6",
            "-hls_list_size", "0",
            "-hls_flags", "append_list",
            "-hls_segment_filename", str(output_dir / "seg%05d.ts"),
            str(playlist),
        ]

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )

            with _jobs_lock:
                _jobs[job_id]["pid"] = proc.pid

            stderr_tail: list = []
            for line in proc.stderr:
                stderr_tail.append(line.rstrip())
                if len(stderr_tail) > 20:
                    stderr_tail.pop(0)

                secs = _parse_time_progress(line)
                if secs is not None:
                    seg_count = _count_segments(output_dir)
                    with _jobs_lock:
                        _jobs[job_id]["transcoded_seconds"] = secs
                        _jobs[job_id]["segments_ready"] = seg_count
                        if not _jobs[job_id].get("playable", False) and seg_count >= MIN_SEGMENTS_TO_PLAY:
                            _jobs[job_id]["playable"] = True
                            log.info(
                                "Job %s is now playable (%d segments ready)", job_id, seg_count
                            )

            proc.wait()

            with _jobs_lock:
                if proc.returncode == 0:
                    _jobs[job_id]["status"] = "done"
                    # Ensure playable is set even for very short files that
                    # finish before the stderr loop emits a progress line.
                    _jobs[job_id]["playable"] = True
                    seg_count = _count_segments(output_dir)
                    _jobs[job_id]["segments_ready"] = seg_count
                else:
                    _jobs[job_id]["status"] = "error"
                    _jobs[job_id]["error"] = "\n".join(stderr_tail)
                _jobs[job_id]["finished_at"] = time.time()
                _jobs[job_id].pop("pid", None)

        except Exception as exc:
            log.exception("Transcode thread failed for job %s", job_id)
            with _jobs_lock:
                _jobs[job_id]["status"] = "error"
                _jobs[job_id]["error"] = str(exc)
                _jobs[job_id]["finished_at"] = time.time()
                _jobs[job_id].pop("pid", None)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def start_transcode(task_id: str, relpath: str, source: Path) -> Dict[str, Any]:
    """
    Queue or return an existing transcode job for *source*.

    Returns the job dict immediately (status may be 'queued', 'transcoding',
    'done', or 'error').

    Raises RuntimeError if ffmpeg is unavailable, concurrency is at the
    limit, or the server load is too high.
    """
    # Lazy cleanup so old jobs don't accumulate forever
    cleanup_old_jobs()

    if not ffmpeg_available():
        raise RuntimeError("ffmpeg is not available on this server")

    jid = job_id_for(task_id, relpath)

    with _jobs_lock:
        existing = _jobs.get(jid)
        if existing and existing["status"] in ("queued", "transcoding", "done"):
            return dict(existing)

    # Check load gates only when we'd actually start a new job
    if active_job_count() >= MAX_CONCURRENT_TRANSCODES:
        raise RuntimeError(
            f"Server is busy: {MAX_CONCURRENT_TRANSCODES} transcode(s) already running"
        )
    if is_overloaded():
        raise RuntimeError(
            f"Server load is too high ({get_system_load():.1f} > {CPU_LOAD_LIMIT}). "
            "Please try again in a few moments."
        )

    output_dir = TRANSCODE_ROOT / jid
    job: Dict[str, Any] = {
        "job_id": jid,
        "task_id": task_id,
        "relpath": relpath,
        "status": "queued",
        "queued_at": time.time(),
        "started_at": None,
        "finished_at": None,
        "transcoded_seconds": 0.0,
        "segments_ready": 0,
        "playable": False,
        "output_dir": str(output_dir),
        "playlist": None,
        "error": None,
        "pid": None,
    }

    with _jobs_lock:
        _jobs[jid] = job

    t = threading.Thread(
        target=_run_transcode,
        args=(jid, source, output_dir),
        daemon=True,
        name=f"transcode-{jid}",
    )
    t.start()

    with _jobs_lock:
        return dict(_jobs[jid])


def cleanup_old_jobs() -> int:
    """
    Remove jobs that finished more than TRANSCODE_TTL_SECONDS ago.
    Deletes their HLS output directories.  Returns the number removed.
    """
    now = time.time()
    to_remove = []

    with _jobs_lock:
        for jid, job in _jobs.items():
            if job["status"] in ("done", "error"):
                finished = job.get("finished_at") or 0
                if now - finished > TRANSCODE_TTL_SECONDS:
                    to_remove.append(jid)

    removed = 0
    for jid in to_remove:
        with _jobs_lock:
            job = _jobs.pop(jid, None)
        if not job:
            continue
        out_dir = Path(job.get("output_dir", ""))
        if out_dir.exists():
            try:
                shutil.rmtree(out_dir)
            except OSError as exc:
                log.warning("Could not remove transcode dir %s: %s", out_dir, exc)
        removed += 1

    if removed:
        log.info("Cleaned up %d expired transcode job(s)", removed)
    return removed


# ---------------------------------------------------------------------------
# Test helpers (not for production use)
# ---------------------------------------------------------------------------

def _reset_for_testing() -> None:
    """Clear all state for a clean test environment. Do not call in production."""
    global _ffmpeg_cache, _semaphore
    with _jobs_lock:
        _jobs.clear()
    _ffmpeg_cache = (None, 0.0)
    _semaphore = threading.Semaphore(MAX_CONCURRENT_TRANSCODES)
