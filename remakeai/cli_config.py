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
Config file management for Remake CLI
Stores credentials securely with chmod 600
"""
import os
import stat
import yaml
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime

DEFAULT_PLATFORM_URL = "https://apps.remake.ai"
CONFIG_DIR = Path.home() / ".config" / "remakeai"
CONFIG_FILE = CONFIG_DIR / "config.yml"


def get_config_path() -> Path:
    """Get the config file path"""
    return CONFIG_FILE


def load_config() -> Dict[str, Any]:
    """Load config from file, return empty dict if not exists"""
    if not CONFIG_FILE.exists():
        return {
            "platform": {"url": DEFAULT_PLATFORM_URL},
            "auth": {},
            "robots": []
        }

    with open(CONFIG_FILE, 'r') as f:
        config = yaml.safe_load(f) or {}

    # Ensure required keys exist
    if "platform" not in config:
        config["platform"] = {"url": DEFAULT_PLATFORM_URL}
    if "auth" not in config:
        config["auth"] = {}
    if "robots" not in config:
        config["robots"] = []

    return config


def save_config(config: Dict[str, Any]) -> None:
    """Save config to file with secure permissions (chmod 600)"""
    # Create directory if needed
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    # Write config
    with open(CONFIG_FILE, 'w') as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    # Set permissions: owner read/write only (chmod 600)
    os.chmod(CONFIG_FILE, stat.S_IRUSR | stat.S_IWUSR)


def get_auth_token() -> Optional[str]:
    """Get stored auth token"""
    config = load_config()
    return config.get("auth", {}).get("token")


def set_auth(token: str, email: str, expires_at: Optional[str] = None) -> None:
    """Store authentication credentials"""
    config = load_config()
    config["auth"] = {
        "token": token,
        "email": email,
        "expires_at": expires_at,
        "authenticated_at": datetime.utcnow().isoformat()
    }
    save_config(config)


def clear_auth() -> None:
    """Clear authentication credentials"""
    config = load_config()
    config["auth"] = {}
    save_config(config)


def get_robots() -> List[Dict[str, Any]]:
    """Get list of paired robots"""
    config = load_config()
    return config.get("robots", [])


def add_robot(robot: Dict[str, Any]) -> None:
    """Add a robot to config"""
    config = load_config()
    config["robots"].append({
        **robot,
        "paired_at": datetime.utcnow().isoformat()
    })
    save_config(config)


def remove_robot(robot_id: str = None, device_id: str = None, name: str = None) -> bool:
    """Remove a robot from config by id, device_id, or name"""
    config = load_config()
    robots = config.get("robots", [])

    original_count = len(robots)

    if robot_id:
        robots = [r for r in robots if r.get("id") != robot_id]
    elif device_id:
        robots = [r for r in robots if r.get("device_id") != device_id]
    elif name:
        robots = [r for r in robots if r.get("name") != name]

    config["robots"] = robots
    save_config(config)

    return len(robots) < original_count


def get_robot(name: str = None, robot_id: str = None) -> Optional[Dict[str, Any]]:
    """Get a specific robot by name or id"""
    robots = get_robots()

    if robot_id:
        return next((r for r in robots if r.get("id") == robot_id), None)
    elif name:
        return next((r for r in robots if r.get("name") == name), None)
    elif len(robots) == 1:
        return robots[0]

    return None


def get_platform_url() -> str:
    """Get platform URL"""
    config = load_config()
    return config.get("platform", {}).get("url", DEFAULT_PLATFORM_URL)


def set_platform_url(url: str) -> None:
    """Set platform URL"""
    config = load_config()
    config["platform"] = {"url": url}
    save_config(config)
