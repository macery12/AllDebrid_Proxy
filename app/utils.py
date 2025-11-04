import re, os, shutil, json, time
from typing import Optional

MAGNET_RE = re.compile(
    r'btih:([0-9A-Fa-f]{40}|[A-Z2-7]{32})',
    re.IGNORECASE
)

def parse_infohash(magnet: str) -> Optional[str]:
    m = MAGNET_RE.search(magnet)
    if not m:
        return None
    return m.group(1).lower()

def ensure_task_dirs(storage_root: str, task_id: str):
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
    usage = shutil.disk_usage(path)
    return usage.free

def append_log(base: str, entry: dict):
    p = os.path.join(base, "logs.json")
    entry = dict(entry)
    entry.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")

def write_metadata(base: str, data: dict):
    p = os.path.join(base, "metadata.json")
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
