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
Remake.ai ROS2 Platform Client.

This package provides:
- CLI commands for robot management (`remake` command)
- WebSocket client for platform communication
- ROS2 bridge for robot sensor/actuator integration
- HTTP API client for platform REST endpoints
"""

__version__ = "0.1.0"
__author__ = "Remake.ai"

# Public API exports
from remakeai.api import PlatformClient, create_client
from remakeai.cli_config import (
    get_auth_token,
    get_platform_url,
    get_websocket_url,
    is_authenticated,
    get_robots,
    get_robot,
)

__all__ = [
    # Version info
    "__version__",
    "__author__",
    # API client
    "PlatformClient",
    "create_client",
    # Config utilities
    "get_auth_token",
    "get_platform_url",
    "get_websocket_url",
    "is_authenticated",
    "get_robots",
    "get_robot",
]
