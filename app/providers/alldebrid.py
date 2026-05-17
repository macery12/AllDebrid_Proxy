# app/providers/alldebrid.py
import requests
from typing import Any, Dict, List, Optional


class ADHTTPError(RuntimeError):
    """AllDebrid API returned a non-success status or HTTP error."""


class AllDebrid:
    """
    Minimal AllDebrid client matching the worker's expected interface.

    Methods:
      - upload_magnets(magnets: List[str]) -> List[str]
      - upload_links(links: List[str]) -> List[str]
      - get_link_info(link: str) -> Dict[str, Any]
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
        """
        payload: Dict[str, Any] = {f"magnets[{i}]": m for i, m in enumerate(magnets)}
        data = self._post("/magnet/upload", data=payload)
        ids: List[str] = []
        for m in data.get("magnets", []):
            mid = m.get("id")
            if mid is not None:
                ids.append(str(mid))
        return ids

    def upload_links(self, links: List[str]) -> List[str]:
        """
        POST /link/unlock (expects link parameter for each link)
        For direct links, we unlock them immediately to get file info.
        Returns a list of unlocked URLs that can be used for downloading.
        
        Note: Unlike magnets which are uploaded and tracked, links are immediately
        unlocked and returned as direct download URLs.
        """
        unlocked_urls: List[str] = []
        for link in links:
            try:
                unlocked_url = self.unlock_link(link)
                unlocked_urls.append(unlocked_url)
            except Exception as e:
                # Re-raise with context about which link failed
                raise ADHTTPError(f"Failed to unlock link {link}: {str(e)}")
        return unlocked_urls

    def unlock_link(self, link: str) -> str:
        """
        Unlock a single link and return the direct download URL.
        
        Args:
            link: The URL to unlock
            
        Returns:
            Direct download URL
            
        Raises:
            ADHTTPError: If unlock fails or returns no URL
        """
        data = self._get("/link/unlock", link=link)
        unlocked_url = data.get("link") or data.get("download") or data.get("url")
        if not unlocked_url:
            raise ADHTTPError(f"Link unlock returned no direct URL for {link}")
        return unlocked_url

    def get_link_info(self, link: str) -> Dict[str, Any]:
        """
        GET /link/infos to get information about a link before unlocking.
        Returns file information including filename and size.
        
        Args:
            link: The URL to get information about
            
        Returns:
            Dictionary with link information including 'filename', 'filesize', 'host', etc.
        """
        data = self._get("/link/infos", link=link)
        infos = data.get("infos") or {}
        if isinstance(infos, list) and infos:
            infos = infos[0]
        return infos

    def _normalize_items(self, arr: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Normalize v4.1 file entries into [{name, size, link?}].
        
        In v4.1, files are structured as:
          - files[].e[] where each entry has {n: name, s: size, l: locked_link}
          - OR older formats with {name|filename, size|filesize, link|url}
        
        This flattens nested e[] arrays and normalizes field names.
        """
        out: List[Dict[str, Any]] = []
        
        for item in arr:
            # v4.1 format: check if this is a directory with e[] entries
            if "e" in item and isinstance(item["e"], list):
                # Recursively flatten entries
                out.extend(self._normalize_items(item["e"]))
            else:
                # Extract fields - try v4.1 format first (n, s, l), then fallback to older formats
                name = item.get("n") or item.get("name") or item.get("filename") or ""
                size = item.get("s") or item.get("size") or item.get("filesize") or 0
                try:
                    size = int(size)
                except Exception:
                    size = 0
                # Note: 'l' contains a locked link that must be unlocked via /link/unlock
                link = item.get("l") or item.get("link") or item.get("url") or None
                out.append({"name": name, "size": size, "link": link})
        
        return out

    def get_magnet_status(self, magnet_id: str) -> Dict[str, Any]:
        """
        POST /v4.1/magnet/status?id=<magnet_id>
        Returns a rich dict:
          {
            "raw":          <full API payload>,
            "files":        [{name, size, link?}, ...],   # non-empty when statusCode == 4
            "statusCode":   int | None,
            "status_text":  str,   # e.g. "Downloading", "In Queue", "Ready"
            "filename":     str,
            "total_size":   int,   # bytes reported by AllDebrid
            "downloaded":   int,   # bytes downloaded so far on AD side
            "seeders":      int,
            "downloadSpeed": int,  # bytes/s on AD side
            "uploadSpeed":  int,
          }
        Handles data.magnets as either a dict or list.
        """
        data = self._get("/magnet/status", id=str(magnet_id))
        files_out: List[Dict[str, Any]] = []

        mags = data.get("magnets")
        mag_obj: Optional[Dict[str, Any]] = None

        # magnets can be a dict (single-ID query) or a list
        if isinstance(mags, dict):
            mag_obj = mags
            if isinstance(mags.get("files"), list):
                files_out.extend(self._normalize_items(mags["files"]))
            if isinstance(mags.get("links"), list):
                files_out.extend(self._normalize_items(mags["links"]))
        elif isinstance(mags, list) and mags:
            mag_obj = mags[0]
            if isinstance(mag_obj.get("files"), list):
                files_out.extend(self._normalize_items(mag_obj["files"]))
            if isinstance(mag_obj.get("links"), list):
                files_out.extend(self._normalize_items(mag_obj["links"]))

        # Safety fallbacks: sometimes present at top level
        if not files_out and isinstance(data.get("files"), list):
            files_out.extend(self._normalize_items(data["files"]))
        if not files_out and isinstance(data.get("links"), list):
            files_out.extend(self._normalize_items(data["links"]))

        result: Dict[str, Any] = {"raw": data, "files": files_out}

        # Expose processing fields so callers can show real-time AllDebrid state
        if mag_obj:
            result["statusCode"]   = mag_obj.get("statusCode")
            result["status_text"]  = mag_obj.get("status") or ""
            result["filename"]     = mag_obj.get("filename") or ""
            result["total_size"]   = int(mag_obj.get("size") or 0)
            result["downloaded"]   = int(mag_obj.get("downloaded") or 0)
            result["seeders"]      = int(mag_obj.get("seeders") or 0)
            result["downloadSpeed"] = int(mag_obj.get("downloadSpeed") or 0)
            result["uploadSpeed"]  = int(mag_obj.get("uploadSpeed") or 0)

        return result

    def get_magnet_files(self, magnet_id: str) -> List[Dict[str, Any]]:
        """
        POST https://api.alldebrid.com/v4/magnet/files
        Fetches the file tree for a *ready* magnet (statusCode 4).
        In v4.1 the files were removed from the status response and live here instead.
        Returns a normalised list of {name, size, link?}.
        """
        # This endpoint lives under /v4/, not /v4.1/
        v4_base = self.base.replace("/v4.1", "/v4")
        if "/v4.1" not in self.base:
            # Already v4 or custom base — just append to root
            v4_base = "https://api.alldebrid.com/v4"
        url = f"{v4_base}/magnet/files"
        payload = self._params({"id[0]": str(magnet_id)})
        r = requests.post(url, data=payload, timeout=self._timeout)
        r.raise_for_status()
        resp = r.json()
        if resp.get("status") != "success":
            raise ADHTTPError(f"AllDebrid magnet/files error: {resp}")
        magnets = (resp.get("data") or {}).get("magnets") or []
        if isinstance(magnets, list):
            for mag in magnets:
                if str(mag.get("id")) == str(magnet_id):
                    files = mag.get("files") or []
                    if files:
                        return self._normalize_items(files)
        return []

    def download_link(self, magnet_id: str, file_index: int) -> str:
        """
        Produce a direct, unlocked URL for the file at `file_index`.
        
        In v4.1:
        1. Get magnet status which returns normalized files
        2. Extract the locked link from files[file_index]
        3. Call /link/unlock to get the final direct URL
        """
        st = self.get_magnet_status(magnet_id)
        files = st.get("files") or []
        if not files:
            raise RuntimeError("download_link: no files yet (magnet not ready)")

        if not (0 <= file_index < len(files)):
            raise IndexError(f"download_link: file_index {file_index} out of range (0..{len(files)-1})")

        # Get the locked link from the normalized file entry
        fi = files[file_index]
        locked_link = fi.get("link")
        
        if not locked_link:
            raise RuntimeError(
                f"download_link: couldn't locate a locked link for file_index {file_index}. "
                f"The magnet may not be ready or the file structure is unexpected."
            )

        # Unlock the locked link to get the final direct URL
        unlocked = self._get("/link/unlock", link=locked_link)
        direct = unlocked.get("link") or unlocked.get("download") or unlocked.get("url")
        if not direct:
            raise RuntimeError(f"download_link: unlock returned no direct link (payload={unlocked})")
        return direct
