import os, subprocess
from typing import Optional
from app.config import settings

# Legacy local-process download (kept for fallback/compat)
def run_aria2_download(url: str, out_dir: str, out_name: str, splits: int = 4) -> int:
    os.makedirs(out_dir, exist_ok=True)
    cmd = [
        "aria2c",
        "--continue=true",
        f"--split={splits}",
        f"--max-connection-per-server={splits}",
        "--min-split-size=1M",
        "--conditional-get=true",
        "--check-integrity=false",
        "--auto-file-renaming=false",
        f"--dir={out_dir}",
        f"--out={out_name}",
        url
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    return proc.returncode

# ===== JSON-RPC (aria2 daemon) helpers =====
from worker.aria2rpc import Aria2RPC

_rpc = None
def get_aria2():
    url = getattr(settings, "ARIA2_RPC_URL", None) or os.getenv("ARIA2_RPC_URL", "http://aria2:16800/jsonrpc")
    secret = getattr(settings, "ARIA2_RPC_SECRET", None) or os.getenv("ARIA2_RPC_SECRET")
    return Aria2RPC(url, secret)

def aria2_add_uri(url: str, out_dir: str, out_name: str, splits: int = 4) -> str:
    """Enqueue a download in the aria2 daemon and return its gid."""
    rpc = get_aria2()
    os.makedirs(out_dir, exist_ok=True)
    options = {
        "dir": out_dir,
        "out": out_name,
        "split": str(splits),
        "max-connection-per-server": str(splits),
        "min-split-size": "1M",
        "conditional-get": "true",
        "check-integrity": "false",
        "auto-file-renaming": "false",
    }
    gid = rpc.addUri([url], options)
    return gid

def aria2_tell_status(gid: str):
    rpc = get_aria2()
    return rpc.tellStatus(gid, ["status","completedLength","totalLength","downloadSpeed","errorMessage","files"])
