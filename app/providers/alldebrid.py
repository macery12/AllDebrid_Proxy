# app/providers/alldebrid.py
import requests
from typing import Any, Dict, List, Optional


class ADHTTPError(RuntimeError):
    """AllDebrid API returned a non-success status or HTTP error."""


class AllDebrid:
    """
    AllDebrid v4.1 API client matching the worker's expected interface.

    Methods:
      - upload_magnets(magnets: List[str]) -> List[str]
      - get_magnet_status(magnet_id: str) -> Dict[str, Any]  # {"raw":<full>, "files":[{name,size,link?}, ...]}
      - download_link(magnet_id: str, file_index: int) -> str  # unlocked direct URL
    """

    def __init__(self, api_key: str, agent: str = "alldebrid-proxy", base_url: str = "https://api.alldebrid.com/v4.1"):
        if not api_key:
            raise ValueError("AllDebrid: api_key is required")
        self.api_key = api_key
        self.agent = agent or "alldebrid-proxy"
        self.base = base_url.rstrip("/")
        self._timeout = (10, 60)  # (connect, read)

    # -------------------------
    # Internal HTTP helpers
    # -------------------------

    def _ok(self, r: requests.Response) -> Dict[str, Any]:
        r.raise_for_status()
        data = r.json()
        if data.get("status") != "success":
            raise ADHTTPError(f"AllDebrid error: {data}")
        return data.get("data") or {}

    def _params(self, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        p = {"agent": self.agent, "apikey": self.api_key}
        if extra:
            p.update(extra)
        return p

    def _get(self, path: str, **params) -> Dict[str, Any]:
        url = f"{self.base}{path}"
        r = requests.get(url, params=self._params(params), timeout=self._timeout)
        return self._ok(r)

    def _post(self, path: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.base}{path}"
        r = requests.post(url, data=self._params(data or {}), timeout=self._timeout)
        return self._ok(r)

    # -------------------------
    # Public interface
    # -------------------------

    def upload_magnets(self, magnets: List[str]) -> List[str]:
        """
        POST /magnet/upload  (expects magnets[] fields)
        Returns a list of string IDs.
        
        v4.1 API response (same as v4):
        - data.magnets: array of magnet objects, each with an 'id' field
        
        Includes fallback support for dict format (if magnets is a single object)
        for maximum backward/forward compatibility.
        """
        payload: Dict[str, Any] = {f"magnets[{i}]": m for i, m in enumerate(magnets)}
        data = self._post("/magnet/upload", data=payload)
        ids: List[str] = []
        
        # v4.1 returns magnets as an array
        magnets_data = data.get("magnets", [])
        if isinstance(magnets_data, list):
            for m in magnets_data:
                mid = m.get("id")
                if mid is not None:
                    ids.append(str(mid))
        # Fallback: check if magnets is a dict (older format)
        elif isinstance(magnets_data, dict):
            mid = magnets_data.get("id")
            if mid is not None:
                ids.append(str(mid))
        
        return ids

    def _normalize_items(self, arr: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Normalize any of these shapes into [{name, size, link?}]:
          {name|filename, size|filesize, link|url?}
        """
        out: List[Dict[str, Any]] = []
        for f in arr:
            name = f.get("name") or f.get("filename") or ""
            size = f.get("size") or f.get("filesize") or 0
            try:
                size = int(size)
            except Exception:
                size = 0
            link = f.get("link") or f.get("url") or None
            out.append({"name": name, "size": size, "link": link})
        return out

    def get_magnet_status(self, magnet_id: str) -> Dict[str, Any]:
        """
        GET /magnet/status?id=<magnet_id>
        Returns {"raw": <full payload>, "files": [{name,size,link?}, ...]}
        
        v4.1 API structure (similar to v4):
        - data.magnets: dict or list containing files/links
        - Fallbacks to top-level data.files / data.links if magnets not present
        
        The method handles various response shapes for maximum compatibility:
        1. data.magnets as dict with .files or .links arrays
        2. data.magnets as list with first element containing .files or .links
        3. Top-level data.files or data.links arrays (legacy/fallback)
        """
        data = self._get("/magnet/status", id=str(magnet_id))
        files_out: List[Dict[str, Any]] = []

        mags = data.get("magnets")

        # magnets can be a dict (common) or a list (older/other paths)
        if isinstance(mags, dict):
            if isinstance(mags.get("files"), list):
                files_out.extend(self._normalize_items(mags["files"]))
            if isinstance(mags.get("links"), list):
                files_out.extend(self._normalize_items(mags["links"]))
        elif isinstance(mags, list) and mags:
            m = mags[0]
            if isinstance(m.get("files"), list):
                files_out.extend(self._normalize_items(m["files"]))
            if isinstance(m.get("links"), list):
                files_out.extend(self._normalize_items(m["links"]))

        # Safety fallbacks: sometimes present at top level
        if not files_out and isinstance(data.get("files"), list):
            files_out.extend(self._normalize_items(data["files"]))
        if not files_out and isinstance(data.get("links"), list):
            files_out.extend(self._normalize_items(data["links"]))

        return {"raw": data, "files": files_out}

    def download_link(self, magnet_id: str, file_index: int) -> str:
        """
        Produce a direct, unlocked URL for the file at `file_index`.
        Tries per-file link/url from normalized files, then falls back to raw mirrors.
        """
        st = self.get_magnet_status(magnet_id)
        files = st.get("files") or []
        if not files:
            raise RuntimeError("download_link: no files yet (magnet not ready)")

        if not (0 <= file_index < len(files)):
            raise IndexError(f"download_link: file_index {file_index} out of range (0..{len(files)-1})")

        fi = files[file_index]
        url_candidate = fi.get("link") or fi.get("url")

        if not url_candidate:
            # Fall back to raw shape at the same index
            raw = st.get("raw") or {}
            candidates: List[Optional[str]] = []

            mags = raw.get("magnets")
            if isinstance(mags, dict):
                if isinstance(mags.get("links"), list) and file_index < len(mags["links"]):
                    candidates.append(mags["links"][file_index].get("link") or mags["links"][file_index].get("url"))
                if isinstance(mags.get("files"), list) and file_index < len(mags["files"]):
                    candidates.append(mags["files"][file_index].get("link") or mags["files"][file_index].get("url"))
            elif isinstance(mags, list) and mags:
                m = mags[0]
                if isinstance(m.get("links"), list) and file_index < len(m["links"]):
                    candidates.append(m["links"][file_index].get("link") or m["links"][file_index].get("url"))
                if isinstance(m.get("files"), list) and file_index < len(m["files"]):
                    candidates.append(m["files"][file_index].get("link") or m["files"][file_index].get("url"))

            if isinstance(raw.get("links"), list) and file_index < len(raw["links"]):
                candidates.append(raw["links"][file_index].get("link") or raw["links"][file_index].get("url"))
            if isinstance(raw.get("files"), list) and file_index < len(raw["files"]):
                candidates.append(raw["files"][file_index].get("link") or raw["files"][file_index].get("url"))

            url_candidate = next((c for c in candidates if c), None)

        if not url_candidate:
            raise RuntimeError(
                "download_link: couldn't locate a per-file URL in status; "
                "adapt mapping if your account exposes a different field."
            )

        # Unlock to get the final direct URL
        unlocked = self._get("/link/unlock", link=url_candidate)
        direct = unlocked.get("link") or unlocked.get("download") or unlocked.get("url")
        if not direct:
            raise RuntimeError(f"download_link: unlock returned no direct link (payload={unlocked})")
        return direct
