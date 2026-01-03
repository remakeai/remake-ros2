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
HTTP API client for Remake.ai platform
"""
import httpx
from typing import Optional, Dict, Any


class AppstoreClient:
    """HTTP client for platform API"""

    def __init__(self, base_url: str, token: Optional[str] = None):
        self.base_url = base_url.rstrip('/')
        self.token = token

    def _headers(self) -> Dict[str, str]:
        """Get request headers with auth if available"""
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def authenticate(self, token: str) -> Dict[str, Any]:
        """
        Validate CLI token
        POST /api/cli/auth
        """
        response = httpx.post(
            f"{self.base_url}/api/cli/auth",
            json={"token": token},
            headers={"Content-Type": "application/json"},
            timeout=30.0
        )
        return response.json()

    def get_unpaired_robots(self) -> Dict[str, Any]:
        """
        Get user's robots that haven't been paired via CLI yet
        GET /api/cli/robots/unpaired
        """
        response = httpx.get(
            f"{self.base_url}/api/cli/robots/unpaired",
            headers=self._headers(),
            timeout=30.0
        )
        return response.json()

    def pair_robot(
        self,
        robot_id: Optional[str] = None,
        robot_name: Optional[str] = None,
        device_id: Optional[str] = None,
        product_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Pair an existing robot or create new
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

        response = httpx.post(
            f"{self.base_url}/api/cli/pair",
            json=payload,
            headers=self._headers(),
            timeout=30.0
        )
        return response.json()

    def unpair_robot(
        self,
        robot_name: Optional[str] = None,
        device_id: Optional[str] = None,
        robot_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Remove robot
        DELETE /api/cli/unpair
        """
        payload = {}
        if robot_name:
            payload["robot_name"] = robot_name
        if device_id:
            payload["device_id"] = device_id
        if robot_id:
            payload["robot_id"] = robot_id

        response = httpx.request(
            "DELETE",
            f"{self.base_url}/api/cli/unpair",
            json=payload,
            headers=self._headers(),
            timeout=30.0
        )
        return response.json()

    def get_status(self) -> Dict[str, Any]:
        """
        Get user and robots status
        GET /api/cli/status
        """
        response = httpx.get(
            f"{self.base_url}/api/cli/status",
            headers=self._headers(),
            timeout=30.0
        )
        return response.json()
