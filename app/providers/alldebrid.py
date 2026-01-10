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
        GET /magnet/status?id=<magnet_id>
        Returns {"raw": <full payload>, "files": [{name,size,link?}, ...]}
        Handles:
          - data.magnets (dict or list)
          - data.files / data.links (top level)
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
