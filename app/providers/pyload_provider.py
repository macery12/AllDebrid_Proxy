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
    - Session-based authentication with CSRF token handling
    - Automatic re-authentication on session expiry
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
        self._csrf_token: Optional[str] = None
        self._timeout = (10, 60)
        self._authenticated = False

    def _get_session(self) -> requests.Session:
        """Get or create requests session and authenticate if needed."""
        if self._session is None:
            self._session = requests.Session()
        if not self._authenticated:
            self._authenticate()
        return self._session

    def _get_csrf_token(self) -> str:
        """Extract CSRF token from cookies."""
        if self._session:
            # Try common CSRF cookie names
            csrf_token = (
                self._session.cookies.get('csrftoken') or
                self._session.cookies.get('csrf_token') or
                self._session.cookies.get('CSRF-TOKEN') or
                self._session.cookies.get('_csrf_token')
            )
            if csrf_token:
                return csrf_token
        return ""

    def _authenticate(self):
        """Authenticate with PyLoad using session-based login."""
        try:
            # Step 1: GET the login page to establish session and get CSRF token
            resp = self._session.get(f"{self.url}/login", timeout=self._timeout)
            resp.raise_for_status()
            
            # Extract CSRF token from cookies
            csrf_token = self._get_csrf_token()
            
            # Step 2: POST login credentials with CSRF token
            headers = {}
            if csrf_token:
                headers['X-CSRFToken'] = csrf_token
                headers['Referer'] = f"{self.url}/login"
            
            # PyLoad expects form data, not JSON for login
            login_data = {
                "username": self.username,
                "password": self.password
            }
            
            resp = self._session.post(
                f"{self.url}/login",
                data=login_data,
                headers=headers,
                timeout=self._timeout,
                allow_redirects=True
            )
            resp.raise_for_status()
            
            # Update CSRF token after login
            self._csrf_token = self._get_csrf_token()
            self._authenticated = True
            
        except requests.RequestException as e:
            raise PyLoadProviderError(f"Authentication failed: {e}")

    def _api_call(self, endpoint: str, method: str = "GET", **params) -> Any:
        """Make API call to PyLoad with session and CSRF token."""
        session = self._get_session()
        url = f"{self.url}/api/{endpoint}"
        
        try:
            headers = {}
            # Include CSRF token for POST requests
            if method == "POST":
                csrf_token = self._get_csrf_token()
                if csrf_token:
                    headers['X-CSRFToken'] = csrf_token
                    headers['Referer'] = self.url
            
            if method == "GET":
                response = session.get(url, params=params, headers=headers, timeout=self._timeout)
            else:
                response = session.post(url, json=params, headers=headers, timeout=self._timeout)
            
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            # If we get 401, try re-authenticating once
            if hasattr(e, 'response') and e.response and e.response.status_code == 401:
                self._authenticated = False
                self._csrf_token = None
                # Retry once after re-authentication
                try:
                    session = self._get_session()
                    headers = {}
                    if method == "POST":
                        csrf_token = self._get_csrf_token()
                        if csrf_token:
                            headers['X-CSRFToken'] = csrf_token
                            headers['Referer'] = self.url
                    
                    if method == "GET":
                        response = session.get(url, params=params, headers=headers, timeout=self._timeout)
                    else:
                        response = session.post(url, json=params, headers=headers, timeout=self._timeout)
                    
                    response.raise_for_status()
                    return response.json()
                except requests.RequestException:
                    pass  # Fall through to raise original error
            
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
