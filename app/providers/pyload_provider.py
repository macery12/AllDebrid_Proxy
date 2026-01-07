# app/providers/pyload_provider.py
import asyncio
import time
from typing import Any, Dict, List, Optional
from pyloadapi import PyLoadAPI, CannotConnect, InvalidAuth


class PyLoadProviderError(RuntimeError):
    """PyLoad provider error."""


class PyLoadProvider:
    """
    PyLoad provider for managing downloads via PyLoad with AllDebrid plugin.
    
    PyLoad handles the AllDebrid integration internally via its AllDebrid plugin.
    This provider manages packages, files, and download status through PyLoad's API.
    
    Methods:
      - upload_magnets(magnets: List[str]) -> List[str]
      - upload_links(links: List[str]) -> List[str]
      - get_package_status(package_id: str) -> Dict[str, Any]
      - download_link(package_id: str, file_index: int) -> str
      - get_file_info(file_id: int) -> Dict[str, Any]
    """

    def __init__(self, url: str, username: str, password: str):
        if not url or not username or not password:
            raise ValueError("PyLoad: url, username, and password are required")
        self.url = url.rstrip("/")
        self.username = username
        self.password = password
        self._api: Optional[PyLoadAPI] = None
        self._loop = None

    def _get_loop(self):
        """Get or create event loop."""
        try:
            loop = asyncio.get_running_loop()
            return loop
        except RuntimeError:
            if self._loop is None or self._loop.is_closed():
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)
            return self._loop

    def _run_async(self, coro):
        """Run async coroutine in sync context."""
        loop = self._get_loop()
        if loop.is_running():
            # If loop is already running, create a task
            return asyncio.create_task(coro)
        else:
            # Run until complete
            return loop.run_until_complete(coro)

    async def _get_api(self) -> PyLoadAPI:
        """Get or create PyLoad API client."""
        if self._api is None:
            try:
                self._api = PyLoadAPI(self.url, self.username, self.password)
                await self._api.login()
            except CannotConnect as e:
                raise PyLoadProviderError(f"Cannot connect to PyLoad at {self.url}: {e}")
            except InvalidAuth as e:
                raise PyLoadProviderError(f"Invalid PyLoad credentials: {e}")
            except Exception as e:
                raise PyLoadProviderError(f"PyLoad API error: {e}")
        return self._api

    def upload_magnets(self, magnets: List[str]) -> List[str]:
        """
        Upload magnet links to PyLoad.
        Returns a list of package IDs.
        """
        async def _upload():
            api = await self._get_api()
            package_ids = []
            for magnet in magnets:
                try:
                    # Add package with magnet link
                    pkg_id = await api.add_package(
                        name="Magnet Download",
                        links=[magnet]
                    )
                    package_ids.append(str(pkg_id))
                except Exception as e:
                    raise PyLoadProviderError(f"Failed to upload magnet: {e}")
            return package_ids

        return self._run_async(_upload())

    def upload_links(self, links: List[str]) -> List[str]:
        """
        Upload direct links to PyLoad.
        Returns a list of package IDs.
        """
        async def _upload():
            api = await self._get_api()
            package_ids = []
            for link in links:
                try:
                    # Add package with link
                    pkg_id = await api.add_package(
                        name="Direct Download",
                        links=[link]
                    )
                    package_ids.append(str(pkg_id))
                except Exception as e:
                    raise PyLoadProviderError(f"Failed to upload link: {e}")
            return package_ids

        return self._run_async(_upload())

    def get_package_status(self, package_id: str) -> Dict[str, Any]:
        """
        Get package status from PyLoad.
        Returns {"raw": <full payload>, "files": [{name, size, link?, file_id}, ...]}
        """
        async def _get_status():
            api = await self._get_api()
            try:
                pkg_id = int(package_id)
                # Get package data
                package_data = await api.get_package_data(pkg_id)
                
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

        return self._run_async(_get_status())

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
        
        async def _get_link():
            api = await self._get_api()
            try:
                # Get file info which includes the download URL
                file_data = await api.get_file_data(file_id)
                
                # The download URL is typically available after PyLoad processes it
                download_url = file_data.get("url") or file_info.get("link")
                
                if not download_url:
                    raise RuntimeError("download_link: no download URL available")
                
                return download_url
            except Exception as e:
                raise PyLoadProviderError(f"Failed to get download link: {e}")
        
        return self._run_async(_get_link())

    def get_file_info(self, file_id: int) -> Dict[str, Any]:
        """Get detailed file information."""
        async def _get_info():
            api = await self._get_api()
            try:
                return await api.get_file_data(file_id)
            except Exception as e:
                raise PyLoadProviderError(f"Failed to get file info: {e}")

        return self._run_async(_get_info())

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

    async def close(self):
        """Close the API connection."""
        if self._api:
            await self._api.close()
            self._api = None
