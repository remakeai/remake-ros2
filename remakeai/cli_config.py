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
Config file management for Remake CLI.
Stores credentials securely with chmod 600.
"""
import os
import stat
import yaml
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime

DEFAULT_PLATFORM_URL = "https://apps.remake.ai"
DEFAULT_WEBSOCKET_URL = "wss://apps.remake.ai/robot-control"
CONFIG_DIR = Path.home() / ".config" / "remakeai"
CONFIG_FILE = CONFIG_DIR / "config.yml"

# Default runtime settings
DEFAULT_SETTINGS = {
    "platform_url": DEFAULT_PLATFORM_URL,
    "websocket_url": DEFAULT_WEBSOCKET_URL,
    "sensor_publish_rate": 10.0,
    "camera_jpeg_quality": 85,
    "asset_quota_mb": 100,
    "reconnect_interval": 5.0,
    "log_level": "info",
}


def get_config_path() -> Path:
    """Get the config file path."""
    return CONFIG_FILE


def load_config() -> Dict[str, Any]:
    """Load config from file, return defaults if not exists."""
    if not CONFIG_FILE.exists():
        return {
            "platform": {"url": DEFAULT_PLATFORM_URL},
            "settings": DEFAULT_SETTINGS.copy(),
            "auth": {},
            "robots": []
        }

    with open(CONFIG_FILE, 'r') as f:
        config = yaml.safe_load(f) or {}

    # Ensure required keys exist
    if "platform" not in config:
        config["platform"] = {"url": DEFAULT_PLATFORM_URL}
    if "settings" not in config:
        config["settings"] = DEFAULT_SETTINGS.copy()
    if "auth" not in config:
        config["auth"] = {}
    if "robots" not in config:
        config["robots"] = []

    # Ensure all default settings exist
    for key, value in DEFAULT_SETTINGS.items():
        if key not in config["settings"]:
            config["settings"][key] = value

    return config


def save_config(config: Dict[str, Any]) -> None:
    """Save config to file with secure permissions (chmod 600)."""
    # Create directory if needed
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    # Write config
    with open(CONFIG_FILE, 'w') as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    # Set permissions: owner read/write only (chmod 600)
    os.chmod(CONFIG_FILE, stat.S_IRUSR | stat.S_IWUSR)


# =============================================================================
# Authentication
# =============================================================================

def get_auth_token() -> Optional[str]:
    """Get stored auth token."""
    config = load_config()
    return config.get("auth", {}).get("token")


def get_auth() -> Dict[str, Any]:
    """Get full authentication info."""
    config = load_config()
    return config.get("auth", {})


def set_auth(token: str, email: str, expires_at: Optional[str] = None) -> None:
    """Store authentication credentials."""
    config = load_config()
    config["auth"] = {
        "token": token,
        "email": email,
        "expires_at": expires_at,
        "authenticated_at": datetime.utcnow().isoformat()
    }
    save_config(config)


def clear_auth() -> None:
    """Clear authentication credentials."""
    config = load_config()
    config["auth"] = {}
    save_config(config)


def is_authenticated() -> bool:
    """Check if user is authenticated."""
    return bool(get_auth_token())


# =============================================================================
# Robot Management
# =============================================================================

def get_robots() -> List[Dict[str, Any]]:
    """Get list of paired robots."""
    config = load_config()
    return config.get("robots", [])


def add_robot(robot: Dict[str, Any]) -> None:
    """Add a robot to config."""
    config = load_config()
    config["robots"].append({
        **robot,
        "paired_at": datetime.utcnow().isoformat()
    })
    save_config(config)


def remove_robot(robot_id: str = None, device_id: str = None, name: str = None) -> bool:
    """Remove a robot from config by id, device_id, or name."""
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


def clear_robots() -> None:
    """Remove all robots from config (for factory reset)."""
    config = load_config()
    config["robots"] = []
    save_config(config)


def get_robot(name: str = None, robot_id: str = None) -> Optional[Dict[str, Any]]:
    """Get a specific robot by name or id."""
    robots = get_robots()

    if robot_id:
        return next((r for r in robots if r.get("id") == robot_id), None)
    elif name:
        return next((r for r in robots if r.get("name") == name), None)
    elif len(robots) == 1:
        return robots[0]

    return None


# =============================================================================
# Platform URL
# =============================================================================

def get_platform_url() -> str:
    """Get platform URL."""
    config = load_config()
    return config.get("platform", {}).get("url", DEFAULT_PLATFORM_URL)


def set_platform_url(url: str) -> None:
    """Set platform URL."""
    config = load_config()
    if "platform" not in config:
        config["platform"] = {}
    config["platform"]["url"] = url
    save_config(config)


def get_websocket_url() -> str:
    """Get WebSocket URL for robot-control namespace."""
    config = load_config()
    return config.get("settings", {}).get("websocket_url", DEFAULT_WEBSOCKET_URL)


# =============================================================================
# Runtime Settings (for `remake config` command)
# =============================================================================

def get_setting(key: str) -> Any:
    """Get a specific setting value."""
    config = load_config()
    settings = config.get("settings", {})
    return settings.get(key, DEFAULT_SETTINGS.get(key))


def set_setting(key: str, value: Any) -> bool:
    """Set a specific setting value. Returns True if key is valid."""
    if key not in DEFAULT_SETTINGS:
        return False

    config = load_config()
    if "settings" not in config:
        config["settings"] = DEFAULT_SETTINGS.copy()

    # Convert value to appropriate type
    default_value = DEFAULT_SETTINGS[key]
    if isinstance(default_value, float):
        value = float(value)
    elif isinstance(default_value, int):
        value = int(value)

    config["settings"][key] = value
    save_config(config)
    return True


def get_all_settings() -> Dict[str, Any]:
    """Get all settings with their current values."""
    config = load_config()
    settings = config.get("settings", {})

    # Merge with defaults
    result = DEFAULT_SETTINGS.copy()
    result.update(settings)
    return result


def reset_settings(all_settings: bool = False) -> None:
    """Reset settings to defaults."""
    config = load_config()
    config["settings"] = DEFAULT_SETTINGS.copy()
    save_config(config)
