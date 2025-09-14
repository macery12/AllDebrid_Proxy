# job_manager.py
from __future__ import annotations

import os
import re
import time
import uuid
import math
import shutil
import threading
import typing as t
import requests
import traceback
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from alldebrid import AllDebrid
from models import SessionLocal, Job
from bus import bus  # multi-worker safe SSE + cancel

# Optional: magnet conversion for .torrent
try:
    from magnet import torrent_to_magnet
except Exception:
    torrent_to_magnet = None  # guarded


# =================== Config ===================
SHARE_ROOT  = os.getenv("SHARE_ROOT", "/share").rstrip("/")
PUBLIC_BASE = os.getenv("SHARE_PUBLIC_BASE", "").rstrip("/")

# downloader tuning
CHUNK               = int(os.getenv("DL_CHUNK_BYTES", str(16 * 1024 * 1024)))     # 16MB
SEGMENT_MIN_BYTES   = int(os.getenv("SEGMENT_MIN_BYTES", str(512 * 1024 * 1024))) # 512MB
DL_SEGMENTS         = int(os.getenv("DL_SEGMENTS", "4"))
DL_MAX_POOL         = int(os.getenv("DL_MAX_POOL", "64"))
DL_RETRIES          = int(os.getenv("DL_RETRIES", "2"))

# disk guard
MIN_FREE_BYTES      = int(os.getenv("MIN_FREE_BYTES", str(5 * 1024 * 1024 * 1024)))  # 5 GB floor

# AllDebrid unlock parallelism + rate limit
AD_UNLOCK_CONC      = int(os.getenv("AD_UNLOCK_CONC", "8"))
AD_RATE             = int(os.getenv("AD_RATE", "10"))   # requests/sec
AD_BURST            = int(os.getenv("AD_BURST", "10"))  # tokens in 1s window

# HEAD sizing parallelism/timeouts
HEAD_CONC           = int(os.getenv("HEAD_CONC", "16"))
HEAD_TIMEOUT        = float(os.getenv("HEAD_TIMEOUT", "5"))  # seconds per HEAD


# =================== Helpers ===================
def _walk_ids(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                yield from _walk_ids(v)
            if k.lower() == 'id':
                try: yield int(v)
                except Exception: pass
    elif isinstance(obj, list):
        for it in obj:
            yield from _walk_ids(it)

def _first_file_entries(m: dict) -> list[dict]:
    files = m.get('files') or []
    if isinstance(files, list) and files:
        return files
    links = m.get('links') or []
    if isinstance(links, list) and links:
        out = []
        for it in links:
            if isinstance(it, dict):
                name = it.get('n') or it.get('name') or it.get('filename')
                page = it.get('l') or it.get('link') or it.get('url')
                if page: out.append({'n': name or '', 'l': page})
            elif isinstance(it, str):
                out.append({'n': os.path.basename(it), 'l': it})
        return out
    return []

def _human(n: int) -> str:
    k = 1024.0
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    v = float(n)
    while v >= k and i < len(units) - 1:
        v /= k
        i += 1
    return f"{int(v) if (i == 0 or v >= 10) else f'{v:.1f}'} {units[i]}"


# -------- Fixed rate limiter (no sleeping under lock) --------
class RateLimiter:
    def __init__(self, rate_per_sec=10, burst=10):
        self.rate = rate_per_sec
        self.burst = burst
        self.ts = []                 # timestamps in last 1s
        self.lk = threading.Lock()

    def acquire(self):
        while True:
            now = time.time()
            wait = 0.0
            with self.lk:
                # keep only events from the last 1s window
                self.ts = [t for t in self.ts if now - t < 1.0]
                if len(self.ts) < self.burst:
                    self.ts.append(now)
                    return
                wait = max(0.0, 1.0 - (now - self.ts[0]))
            if wait > 0:
                time.sleep(wait)


# =================== Job Manager ===================
class JobManager:
    def __init__(self, ad: AllDebrid, temp_dir: str, max_size: int, max_conc: int = 5):
        self.ad = ad
        self.temp = temp_dir
        os.makedirs(self.temp, exist_ok=True)
        os.makedirs(SHARE_ROOT, exist_ok=True)
        self.max_size = max_size
        self.pool = ThreadPoolExecutor(max_workers=max_conc)

        self.http = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=DL_MAX_POOL, pool_maxsize=DL_MAX_POOL, max_retries=DL_RETRIES
        )
        self.http.mount("http://", adapter)
        self.http.mount("https://", adapter)
        self.http.headers.update({"Connection": "keep-alive"})

        self._ad_rate = RateLimiter(rate_per_sec=AD_RATE, burst=AD_BURST)

    # ---------- DB / SSE ----------
    def create_job(self, input_type: str, source_input: str, include_trackers: bool, client_id: str | None) -> str:
        job_id = str(uuid.uuid4())
        with SessionLocal() as db:
            j = Job(
                id=job_id,
                client_id=client_id,
                input_type=input_type,
                source_input=source_input,
                include_trackers=include_trackers,
                status='queued',
            )
            db.add(j); db.commit()
        threading.Thread(target=self._run_job, args=(job_id,), daemon=True).start()
        return job_id

    def _update(self, job_id: str, **fields):
        with SessionLocal() as db:
            j = db.get(Job, job_id)
            if not j: return
            for k, v in fields.items():
                setattr(j, k, v)
            j.updated_at = datetime.utcnow()
            db.commit()

    def _emit(self, job_id: str, **payload):
        if 'status' in payload or 'error' in payload:
            self._update(job_id, **{k: v for k, v in payload.items() if k in ('status', 'error')})
        bus.publish(job_id, payload)

    def _schedule_clear(self, job_id: str, seconds: int):
        def _clear():
            try:
                with SessionLocal() as db:
                    j = db.get(Job, job_id)
                    if j: db.delete(j); db.commit()
            finally:
                bus.publish(job_id, {"type": "cleared"})
        t = threading.Timer(seconds, _clear); t.daemon = True; t.start()

    # ---------- Cancel ----------
    def request_cancel(self, job_id: str):
        bus.request_cancel(job_id)

    def _is_cancelled(self, job_id: str) -> bool:
        return bus.is_cancelled(job_id)

    # ---------- IDs / naming ----------
    @staticmethod
    def _slugify(name: str) -> str:
        s = re.sub(r"\s+", "-", name.strip())
        s = re.sub(r"[^A-Za-z0-9._-]+", "", s)
        s = s.strip("-._")
        return s or "share"

    def _make_share_id(self, base_name: str) -> str:
        ts = int(time.time())
        slug = self._slugify(base_name)
        sid = f"{slug}-{ts}"
        final = sid; n = 1
        while os.path.exists(os.path.join(SHARE_ROOT, final)):
            n += 1; final = f"{sid}-{n}"
        return final

    # ---------- Disk ----------
    def _disk_usage(self) -> tuple[int, int, int]:
        total, used, free = shutil.disk_usage(SHARE_ROOT)
        return total, used, free

    def _free_bytes(self) -> int:
        return self._disk_usage()[2]

    def _ensure_space(self, need: int, job_id: str, context: str):
        total, used, free = self._disk_usage()
        bus.publish(job_id, {"message": f"{context} — Disk: free {_human(free)} / total {_human(total)}"})
        if free < need:
            raise RuntimeError(f"Not enough disk space ({_human(free)} free, need >= {_human(need)})")

    # ---------- AllDebrid helpers ----------
    def _magnet_upload_get_id(self, magnet: str) -> int:
        self._ad_rate.acquire()
        resp = self.ad.upload_magnets([magnet])
        data = resp.get('data', {})
        ids = list(_walk_ids(data))
        if ids: return ids[0]
        raise RuntimeError(f"Could not extract magnet id from response: {resp}")

    def _magnet_status_get_m(self, magnet_id: int) -> dict:
        self._ad_rate.acquire()
        st = self.ad.get_magnet_status(magnet_id)
        if st.get('status') != 'success':
            raise RuntimeError(f"AllDebrid status error: {st}")
        dat = st.get('data', {})
        mags = dat.get('magnets')
        if isinstance(mags, dict):
            return mags
        if isinstance(mags, list) and mags:
            for it in mags:
                try:
                    if int(it.get('id')) == int(magnet_id): return it
                except Exception: pass
            return mags[0]
        if isinstance(dat, dict) and isinstance(dat.get('magnet'), dict):
            return dat['magnet']
        return {}

    def _unlock_many(self, files: list[dict], job_id: str) -> list[tuple[str, str]]:
        """Unlock many Alldebrid file pages concurrently with rate limiting."""
        total = len(files)
        bus.publish(job_id, {"type": "unlock", "unlocked": 0, "total": total})
        results: list[tuple[str, str] | None] = [None] * total

        def work(idx: int, f: dict):
            page = f.get('l') or f.get('link') or ''
            name = f.get('n') or f.get('name') or ''
            if not page:
                return
            if self._is_cancelled(job_id):
                return
            self._ad_rate.acquire()
            try:
                r = self.ad.download_link(page)
                d = r.get('data', {})
                direct = d.get('link')
                if not direct:
                    links = d.get('links')
                    if isinstance(links, list) and links:
                        direct = links[0].get('link') or links[0].get('url')
                url = direct or page
                nm = name or os.path.basename(page)
                results[idx] = (url, nm)
            except Exception:
                results[idx] = (page, name or os.path.basename(page))
            finally:
                done = sum(1 for x in results if x is not None)
                if done == total or done % 2 == 0:
                    bus.publish(job_id, {"type": "unlock", "unlocked": done, "total": total})

        workers = max(1, min(AD_UNLOCK_CONC, 16))
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(work, i, f) for i, f in enumerate(files)]
            for fut in as_completed(futs):
                fut.result()

        bus.publish(job_id, {"message": f"Retrieved {sum(r is not None for r in results)}/{total} download links"})
        return [r for r in results if r]

    def _wait_and_unlock(self, magnet_id: int, job_id: str, timeout_sec: int = 900) -> list[tuple[str, str]]:
        """Poll until files exist, then unlock them in parallel."""
        deadline = time.time() + timeout_sec
        backoff = 1.0
        announced = set()

        while time.time() < deadline:
            if self._is_cancelled(job_id):
                raise RuntimeError("cancelled")

            m = self._magnet_status_get_m(magnet_id)
            status = m.get('status')
            code = m.get('statusCode')
            files = _first_file_entries(m)

            key = (status, code, len(files))
            if key not in announced:
                # removed 'links:0' noise
                self._emit(job_id, message=f"Debrid status: {status} (code={code}) • files:{len(files)}")
                announced.add(key)

            if files:
                self._emit(job_id, message=f"Retrieving download links…")
                return self._unlock_many(files, job_id)

            if isinstance(code, int) and code >= 5:
                raise RuntimeError(f"AllDebrid magnet failed (code {code})")
            time.sleep(backoff)
            backoff = min(4.0, backoff + 0.5)

        raise TimeoutError("Timed out waiting for AllDebrid files")

    # ---------- HEAD sizing (parallel) ----------
    def _sizes_parallel(self, urls: list[str], job_id: str) -> dict[str, int | None]:
        total = len(urls)
        out: dict[str, int | None] = {}
        bus.publish(job_id, {"message": f"Preparing downloads (sizing files)… {0}/{total}"})

        def work(u: str):
            try:
                r = self.http.head(u, timeout=HEAD_TIMEOUT, allow_redirects=True)
                r.raise_for_status()
                cl = r.headers.get("Content-Length")
                return int(cl) if cl else None
            except Exception:
                return None

        done = 0
        with ThreadPoolExecutor(max_workers=max(1, HEAD_CONC)) as ex:
            futs = {ex.submit(work, u): u for u in urls}
            for fut in as_completed(futs):
                u = futs[fut]
                out[u] = fut.result()
                done += 1
                if done % 4 == 0 or done == total:
                    bus.publish(job_id, {"message": f"Preparing downloads (sizing files)… {done}/{total}"})
        return out

    # ---------- HTTP download ----------
    def _head_info(self, url: str) -> tuple[bool, int | None]:
        try:
            r = self.http.head(url, timeout=15, allow_redirects=True)
            r.raise_for_status()
            size = None
            cl = r.headers.get("Content-Length")
            if cl: size = int(cl)
            supports = "bytes" in (r.headers.get("Accept-Ranges", "") or "").lower()
            return supports, size
        except Exception:
            return False, None

    def _preallocate(self, path: str, size: int):
        fd = os.open(path, os.O_RDWR | os.O_CREAT)
        try:
            if hasattr(os, "posix_fallocate"):
                os.posix_fallocate(fd, 0, size)
            else:
                os.ftruncate(fd, size)
        finally:
            os.close(fd)

    def _download_segmented(self, url: str, dest: str, job_id: str, name: str, size: int, parts: int) -> str:
        parts = max(2, int(parts))
        self._preallocate(dest, size)

        received = 0
        lock = threading.Lock()

        def _dl_part(idx: int, start: int, end: int):
            nonlocal received
            headers = {"Range": f"bytes={start}-{end}"}
            with self.http.get(url, headers=headers, stream=True, timeout=60) as r:
                r.raise_for_status()
                with open(dest, "r+b", buffering=0) as f:
                    f.seek(start)
                    for chunk in r.iter_content(chunk_size=CHUNK):
                        if self._is_cancelled(job_id):
                            raise RuntimeError("cancelled")
                        if not chunk: continue
                        f.write(chunk)
                        with lock:
                            received += len(chunk)
                            pct = int(received * 100 / size)
                            bus.publish(job_id, {"type": "progress","file": name,"received": received,"total": size,"pct": pct})

        part_size = math.ceil(size / parts)
        ranges = []
        for i in range(parts):
            start = i * part_size
            end = min(size - 1, start + part_size - 1)
            if start > end: break
            ranges.append((i, start, end))

        workers = min(parts, max(2, DL_SEGMENTS))
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(_dl_part, i, s, e) for (i, s, e) in ranges]
            for fut in as_completed(futs): fut.result()

        bus.publish(job_id, {"type": "progress","file": name,"received": size,"total": size,"pct": 100})
        return dest

    def _download_one(self, url: str, dest: str, job_id: str, display_name: str) -> str:
        supports, size = self._head_info(url)

        if size and size > 0:
            self._ensure_space(size + MIN_FREE_BYTES, job_id, f"Preparing to download {display_name}")

        if supports and size and size >= SEGMENT_MIN_BYTES and DL_SEGMENTS >= 2:
            try:
                self._emit(job_id, message=f"Segmented download x{DL_SEGMENTS} for {display_name}")
                return self._download_segmented(url, dest, job_id, display_name, size, parts=DL_SEGMENTS)
            except Exception as e:
                self._emit(job_id, message=f"Segmented failed, fallback: {e}")

        last_exc = None
        for _ in range(max(1, DL_RETRIES)):
            try:
                with self.http.get(url, stream=True, timeout=60) as r:
                    r.raise_for_status()
                    total = size
                    if total is None:
                        try:
                            cl = r.headers.get("Content-Length")
                            if cl: total = int(cl)
                        except Exception:
                            total = None
                    if total and self.max_size and total > self.max_size:
                        raise RuntimeError(f"File too large: {total} > {self.max_size}")

                    got = 0
                    last_emit = 0.0
                    last_pct = -1
                    with open(dest, "wb") as f:
                        for chunk in r.iter_content(chunk_size=CHUNK):
                            if self._is_cancelled(job_id):
                                raise RuntimeError("cancelled")
                            if not chunk: continue
                            if total is None and self._free_bytes() < MIN_FREE_BYTES + CHUNK:
                                raise RuntimeError("Not enough disk space during download")
                            f.write(chunk)
                            got += len(chunk)
                            if self.max_size and got > self.max_size:
                                raise RuntimeError(f"File too large while streaming: {got} > {self.max_size}")
                            pct = int(got * 100 / total) if total else None
                            now = time.time()
                            if (now - last_emit) >= 0.1 and (pct is None or pct != last_pct):
                                bus.publish(job_id, {"type": "progress","file": display_name,"received": got,"total": total,"pct": pct})
                                last_emit = now
                                last_pct = pct if pct is not None else last_pct
                if total:
                    bus.publish(job_id, {"type": "progress","file": display_name,"received": total,"total": total,"pct": 100})
                return dest
            except Exception as e:
                last_exc = e; time.sleep(1.0)
        raise last_exc

    # =================== Worker ===================
    def _run_job(self, job_id: str):
        local_items: list[tuple[str, str]] = []
        try:
            self._emit(job_id, status='running', message='Starting')
            bus.publish(job_id, {"type": "meta", "startedAt": int(time.time() * 1000)})

            total, used, free = self._disk_usage()
            self._emit(job_id, message=f"Disk: free {_human(free)} / total {_human(total)}")

            with SessionLocal() as db:
                j = db.get(Job, job_id)
                if not j: raise RuntimeError("Job not found")
                input_type, source_input = j.input_type, j.source_input
                include_trackers = j.include_trackers

            if self._is_cancelled(job_id):
                raise RuntimeError("cancelled")

            downloads: list[tuple[str, str]] = []
            base_name_for_id: str = "share"

            if input_type == 'torrent':
                if not torrent_to_magnet: raise RuntimeError("Torrent conversion not available")
                with open(source_input, 'rb') as f:
                    magnet = torrent_to_magnet(f.read(), include_trackers=include_trackers)
                mid = self._magnet_upload_get_id(magnet)
                self._emit(job_id, message='Debriding (magnet)…')
                downloads = self._wait_and_unlock(mid, job_id)
                base_name_for_id = os.path.splitext(os.path.basename(source_input))[0] or "share"

            elif input_type == 'magnet':
                mid = self._magnet_upload_get_id(source_input)
                self._emit(job_id, message='Debriding (magnet)…')
                downloads = self._wait_and_unlock(mid, job_id)
                m = re.search(r"(?:^|&)dn=([^&]+)", source_input)
                if m:
                    import urllib.parse as up
                    base_name_for_id = up.unquote(m.group(1))
                else:
                    base_name_for_id = "magnet"

            elif input_type == 'url':
                for line in source_input.splitlines():
                    if self._is_cancelled(job_id): raise RuntimeError("cancelled")
                    link = line.strip()
                    if not link: continue
                    try:
                        self._ad_rate.acquire()
                        r = self.ad.download_link(link)
                        d = r.get('data', {})
                        direct = d.get('link')
                        if not direct:
                            links = d.get('links')
                            if isinstance(links, list) and links:
                                direct = links[0].get('link') or links[0].get('url')
                        url = direct or link
                        name = d.get('filename') or os.path.basename(link.split('?', 1)[0].rstrip('/')) or 'file'
                    except Exception:
                        url = link
                        name = os.path.basename(link.split('?', 1)[0].rstrip('/')) or 'file'
                    downloads.append((url, name))
                base_name_for_id = "urls"

            else:
                raise RuntimeError(f"Unknown input type: {input_type}")

            if not downloads:
                raise RuntimeError("No downloadable files resolved")

            share_id = self._make_share_id(base_name_for_id)
            bus.publish(job_id, {"type": "meta", "name": share_id})

            # ---- NEW: parallel sizing (HEAD) with progress ----
            urls_only = [u for (u, _) in downloads]
            sizes_map = self._sizes_parallel(urls_only, job_id)
            total_known = sum(sz for sz in sizes_map.values() if isinstance(sz, int) and sz > 0)

            need = max(total_known, 0) + MIN_FREE_BYTES
            self._ensure_space(need, job_id, "Before downloading")

            if total_known:
                bus.publish(job_id, {"type": "overall", "phase": "downloading", "received": 0, "total": total_known, "pct": 0})
            else:
                bus.publish(job_id, {"message": "Starting downloads (size unknown)…"})

            # Download concurrently
            def _one(u: str, i: int, name: str):
                dest = os.path.join(self.temp, f"{uuid.uuid4()}_{name}")
                self._download_one(u, dest, job_id, name)
                return dest, name

            futures = [self.pool.submit(_one, u, i, name) for i, (u, name) in enumerate(downloads)]

            received_sum = 0
            for fut in as_completed(futures):
                if self._is_cancelled(job_id): raise RuntimeError("cancelled")
                p, fname = fut.result()
                local_items.append((p, fname))
                try: received_sum += os.path.getsize(p)
                except Exception: pass
                if total_known:
                    pct = min(99, int(received_sum * 100 / total_known))
                    bus.publish(job_id, {"type": "overall", "phase": "downloading", "received": received_sum, "total": total_known, "pct": pct})
                self._emit(job_id, message=f"Downloaded {len(local_items)}/{len(downloads)}")

            if self._is_cancelled(job_id): raise RuntimeError("cancelled")

            # Move to /share/<ID>/
            self._emit(job_id, status='uploading', message=f"Preparing share folder {share_id}")
            dst = os.path.join(SHARE_ROOT, share_id)
            os.makedirs(dst, mode=0o750, exist_ok=False)
            self._emit(job_id, message=f"Moving {len(local_items)} file(s) to share…")
            for p, fname in local_items:
                if self._is_cancelled(job_id): raise RuntimeError("cancelled")
                try:
                    shutil.move(p, os.path.join(dst, fname))
                except Exception:
                    shutil.copy2(p, os.path.join(dst, fname))
                    try: os.remove(p)
                    except Exception: pass

            share_url = f"{PUBLIC_BASE}/d/{share_id}/" if PUBLIC_BASE else f"/d/{share_id}/"
            self._emit(job_id, status='done')
            with SessionLocal() as db:
                jj = db.get(Job, job_id)
                if jj:
                    if hasattr(jj, "sharry_share_id"):  jj.sharry_share_id = share_id
                    if hasattr(jj, "sharry_public_web"): jj.sharry_public_web = share_url
                    db.commit()

            bus.publish(job_id, {"status": "done", "public": {"shareId": share_id}, "share_url": share_url})
            self._schedule_clear(job_id, 300)

        except Exception as e:
            msg = str(e).lower()
            if "cancelled" in msg or "canceled" in msg:
                self._emit(job_id, status='cancelled', error='')
                bus.publish(job_id, {"status":"cancelled", "message":"Cancelled"})
                self._schedule_clear(job_id, 5)
            else:
                traceback.print_exc()
                self._emit(job_id, status='error', error=str(e))
                self._schedule_clear(job_id, 60)
            # clean temps
            try:
                for p, _ in local_items:
                    if os.path.exists(p): os.remove(p)
            except Exception:
                pass
