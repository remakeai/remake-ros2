#!/usr/bin/env python3
#
# Copyright 2025 REMAKE.AI
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
HTTP API client for Remake.ai platform.
"""
import httpx
from typing import Optional, Dict, Any


class PlatformClient:
    """HTTP client for platform REST API."""

    def __init__(self, base_url: str, token: Optional[str] = None):
        self.base_url = base_url.rstrip('/')
        self.token = token

    def _headers(self) -> Dict[str, str]:
        """Get request headers with auth if available."""
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _request(
        self,
        method: str,
        endpoint: str,
        json: Optional[Dict] = None,
        data: Optional[bytes] = None,
        content_type: Optional[str] = None,
        timeout: float = 30.0
    ) -> Dict[str, Any]:
        """Make HTTP request with error handling."""
        url = f"{self.base_url}{endpoint}"
        headers = self._headers()

        if content_type:
            headers["Content-Type"] = content_type

        try:
            response = httpx.request(
                method,
                url,
                json=json,
                content=data,
                headers=headers,
                timeout=timeout
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            # Try to extract error message from response
            try:
                error_data = e.response.json()
                return {"success": False, "error": error_data.get("error", str(e))}
            except Exception:
                return {"success": False, "error": str(e)}
        except httpx.RequestError as e:
            return {"success": False, "error": f"Request failed: {e}"}

    # =========================================================================
    # Authentication
    # =========================================================================

    def authenticate(self, token: str) -> Dict[str, Any]:
        """
        Validate CLI token.
        POST /api/cli/auth
        """
        response = httpx.post(
            f"{self.base_url}/api/cli/auth",
            json={"token": token},
            headers={"Content-Type": "application/json"},
            timeout=30.0
        )
        return response.json()

    # =========================================================================
    # Robot Management
    # =========================================================================

    def get_unpaired_robots(self) -> Dict[str, Any]:
        """
        Get user's robots that haven't been paired via CLI yet.
        GET /api/cli/robots/unpaired
        """
        return self._request("GET", "/api/cli/robots/unpaired")

    def pair_robot(
        self,
        robot_id: Optional[str] = None,
        robot_name: Optional[str] = None,
        device_id: Optional[str] = None,
        product_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Pair an existing robot or create new.
        POST /api/cli/pair
        """
        payload = {}
        if robot_id:
            payload["robot_id"] = robot_id
        if robot_name:
            payload["robot_name"] = robot_name
        if device_id:
            payload["device_id"] = device_id
        if product_id:
            payload["product_id"] = product_id

        return self._request("POST", "/api/cli/pair", json=payload)

    def get_status(self) -> Dict[str, Any]:
        """
        Get user and robots status.
        GET /api/cli/status
        """
        return self._request("GET", "/api/cli/status")

    # =========================================================================
    # Firmware Updates
    # =========================================================================

    def get_firmware_info(self, robot_id: str) -> Dict[str, Any]:
        """
        Check for firmware updates.
        GET /api/cli/robots/{robot_id}/firmware
        """
        return self._request("GET", f"/api/cli/robots/{robot_id}/firmware")

    def download_firmware(self, robot_id: str, version: str) -> Optional[bytes]:
        """
        Download firmware binary.
        GET /api/cli/robots/{robot_id}/firmware/{version}/download
        """
        url = f"{self.base_url}/api/cli/robots/{robot_id}/firmware/{version}/download"
        try:
            response = httpx.get(
                url,
                headers=self._headers(),
                timeout=300.0,  # 5 min timeout for large downloads
                follow_redirects=True
            )
            response.raise_for_status()
            return response.content
        except Exception:
            return None

    # =========================================================================
    # Logging
    # =========================================================================

    def upload_logs(self, robot_id: str, logs: bytes, since: str = None) -> Dict[str, Any]:
        """
        Upload compressed logs for debugging.
        POST /api/cli/robots/{robot_id}/logs
        """
        # Use multipart form for binary upload
        files = {"logs": ("logs.tar.gz", logs, "application/gzip")}
        data = {}
        if since:
            data["since"] = since

        url = f"{self.base_url}/api/cli/robots/{robot_id}/logs"
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        try:
            response = httpx.post(
                url,
                files=files,
                data=data,
                headers=headers,
                timeout=120.0  # 2 min timeout for uploads
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            try:
                return {"success": False, "error": e.response.json().get("error", str(e))}
            except Exception:
                return {"success": False, "error": str(e)}
        except httpx.RequestError as e:
            return {"success": False, "error": f"Upload failed: {e}"}

    # =========================================================================
    # App Management
    # =========================================================================

    def get_app_info(self, app_id: str) -> Dict[str, Any]:
        """
        Get app information for launch command.
        GET /api/cli/apps/{app_id}
        """
        return self._request("GET", f"/api/cli/apps/{app_id}")

    def get_user_apps(self) -> Dict[str, Any]:
        """
        Get list of apps available to user.
        GET /api/cli/apps
        """
        return self._request("GET", "/api/cli/apps")


def create_client(base_url: str, token: Optional[str] = None) -> PlatformClient:
    """Factory function to create a platform client."""
    return PlatformClient(base_url, token)
