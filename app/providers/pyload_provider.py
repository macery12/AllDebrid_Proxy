# app/providers/pyload_provider.py
import time
from typing import Any, Dict, List, Optional
import requests


class PyLoadProviderError(RuntimeError):
    """PyLoad provider error."""


class PyLoadProvider:
    """
    PyLoad provider for managing downloads via PyLoad with AllDebrid plugin.
    
    PyLoad handles the AllDebrid integration internally via its AllDebrid plugin.
    This provider manages packages, files, and download status through PyLoad's JSON API.
    
    Features:
    - HTTP Basic Auth for LinuxServer PyLoad-NG (CSRF disabled by default)
    - JSON API requests
    - Support for magnets and direct file URLs
    
    Methods:
      - upload_magnets(magnets: List[str]) -> List[str]
      - upload_links(links: List[str]) -> List[str]
      - get_package_status(package_id: str) -> Dict[str, Any]
      - download_link(package_id: str, file_index: int) -> str
    """

    def __init__(self, url: str, username: str, password: str):
        if not url or not username or not password:
            raise ValueError("PyLoad: url, username, and password are required")
        self.url = url.rstrip("/")
        self.username = username
        self.password = password
        self._session: Optional[requests.Session] = None
        self._timeout = (10, 60)

    def _get_session(self) -> requests.Session:
        """Get or create requests session with HTTP Basic Auth."""
        if self._session is None:
            self._session = requests.Session()
            # LSIO PyLoad-NG uses HTTP Basic Auth, CSRF disabled by default
            self._session.auth = (self.username, self.password)
        return self._session

    def _api_call(self, endpoint: str, method: str = "GET", **params) -> Any:
        """Make API call to PyLoad using HTTP Basic Auth and JSON payloads."""
        session = self._get_session()
        url = f"{self.url}/api/{endpoint}"
        
        try:
            if method == "GET":
                response = session.get(url, params=params, timeout=self._timeout)
            else:
                # LSIO PyLoad-NG expects JSON payloads for POST requests
                response = session.post(url, json=params, timeout=self._timeout)
            
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            raise PyLoadProviderError(f"PyLoad API error: {e}")

    def upload_magnets(self, magnets: List[str]) -> List[str]:
        """
        Upload magnet links to PyLoad.
        Returns a list of package IDs.
        """
        package_ids = []
        for magnet in magnets:
            try:
                # Add package with magnet link
                result = self._api_call(
                    "addPackage",
                    method="POST",
                    name="Magnet Download",
                    links=[magnet]
                )
                # Result is typically the package ID
                pkg_id = result if isinstance(result, (int, str)) else result.get("id")
                if pkg_id:
                    package_ids.append(str(pkg_id))
            except Exception as e:
                raise PyLoadProviderError(f"Failed to upload magnet: {e}")
        return package_ids

    def upload_links(self, links: List[str]) -> List[str]:
        """
        Upload direct links to PyLoad.
        Returns a list of package IDs.
        """
        package_ids = []
        for link in links:
            try:
                # Add package with link
                result = self._api_call(
                    "addPackage",
                    method="POST",
                    name="Direct Download",
                    links=[link]
                )
                pkg_id = result if isinstance(result, (int, str)) else result.get("id")
                if pkg_id:
                    package_ids.append(str(pkg_id))
            except Exception as e:
                raise PyLoadProviderError(f"Failed to upload link: {e}")
        return package_ids

    def get_package_status(self, package_id: str) -> Dict[str, Any]:
        """
        Get package status from PyLoad.
        Returns {"raw": <full payload>, "files": [{name, size, link?, file_id}, ...]}
        """
        try:
            pkg_id = int(package_id)
            # Get package data
            package_data = self._api_call("getPackageData", pid=pkg_id)
            
            files_out = []
            if package_data and "links" in package_data:
                for idx, link_data in enumerate(package_data["links"]):
                    file_info = {
                        "name": link_data.get("name", f"file_{idx}"),
                        "size": link_data.get("size", 0),
                        "link": link_data.get("url"),
                        "file_id": link_data.get("fid"),
                        "status": link_data.get("status"),
                        "plugin": link_data.get("plugin"),
                    }
                    files_out.append(file_info)
            
            return {"raw": package_data, "files": files_out}
        except Exception as e:
            raise PyLoadProviderError(f"Failed to get package status: {e}")

    def download_link(self, package_id: str, file_index: int) -> str:
        """
        Get the download link for a specific file in a package.
        PyLoad handles the unlocking via AllDebrid plugin automatically.
        """
        status = self.get_package_status(package_id)
        files = status.get("files") or []
        
        if not files:
            raise RuntimeError("download_link: no files yet (package not ready)")
        
        if not (0 <= file_index < len(files)):
            raise IndexError(f"download_link: file_index {file_index} out of range (0..{len(files)-1})")
        
        file_info = files[file_index]
        file_id = file_info.get("file_id")
        
        if not file_id:
            raise RuntimeError("download_link: file_id not available")
        
        try:
            # Get link info which includes the download URL
            link_data = self._api_call("getLinkInfo", fid=file_id)
            
            # The download URL is typically in the url field
            download_url = link_data.get("url") or file_info.get("link")
            
            if not download_url:
                raise RuntimeError("download_link: no download URL available")
            
            return download_url
        except Exception as e:
            raise PyLoadProviderError(f"Failed to get download link: {e}")

    def wait_for_package_ready(self, package_id: str, timeout: int = 300, poll_interval: int = 5) -> bool:
        """
        Wait for package to be ready (files available).
        Returns True if ready, False if timeout.
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                status = self.get_package_status(package_id)
                files = status.get("files") or []
                if files:
                    return True
            except Exception:
                pass
            time.sleep(poll_interval)
        return False
