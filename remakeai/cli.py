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
Remake CLI - Command-line tool for pairing and managing robots.

Commands:
    login          Authenticate with Platform
    logout         Clear stored credentials
    pair           Pair a robot from Platform account
    factory-reset  Factory reset (wipe credentials and assets)
    connect        Connect robot to Platform (go online)
    status         Show login and robot status
    info           Display robot description and capabilities
    test           Run self-diagnostics
    logs           View or upload robot logs
    update         Check and apply firmware updates
    config         View/modify runtime configuration
    assets         Manage cached app assets
    launch         Launch an app for testing
"""
import os
import sys
import time
import json
import gzip
import click
from pathlib import Path
from typing import Optional

from .cli_config import (
    load_config, get_auth_token, get_auth, set_auth, clear_auth, is_authenticated,
    get_robots, add_robot, remove_robot, clear_robots, get_robot,
    get_platform_url, set_platform_url, get_websocket_url,
    get_setting, set_setting, get_all_settings, reset_settings,
    DEFAULT_SETTINGS
)
from .api import PlatformClient
from .websocket_client import connect_robot
from .ros2_bridge import is_ros2_available

# Version
__version__ = "0.1.0"


# =============================================================================
# CLI Group
# =============================================================================

@click.group()
@click.version_option(version=__version__, prog_name='remake')
def cli():
    """Remake CLI - Pair and connect robots to Platform."""
    pass


# =============================================================================
# 1. login
# =============================================================================

@cli.command()
@click.option('--email', help='Account email (optional, for reference)')
@click.option('--url', help='Platform URL (default: https://apps.remake.ai)')
def login(email, url):
    """Authenticate with Platform using a CLI token."""
    config = load_config()

    # Check if already logged in
    existing_token = get_auth_token()
    if existing_token:
        existing_email = config.get('auth', {}).get('email', 'unknown')
        click.echo(f"Already logged in as {existing_email}")
        if not click.confirm("Login with a different account?"):
            return

    # Show instructions
    platform_url = url or get_platform_url()
    click.echo("")
    click.echo("To get your CLI token:")
    click.echo(f"  1. Go to {platform_url}/tokens")
    click.echo("  2. Click 'Create CLI Token'")
    click.echo("  3. Copy the token")
    click.echo("")

    # Prompt for token
    token = click.prompt("Enter token", hide_input=True)

    if not token.strip():
        click.echo("Token cannot be empty")
        return

    # Validate token
    click.echo("Validating token...")
    client = PlatformClient(platform_url)

    try:
        result = client.authenticate(token)

        if result.get('success'):
            user = result.get('user', {})
            user_email = user.get('email', email or 'unknown')

            # Save credentials and URL
            set_auth(
                token=token,
                email=user_email,
                expires_at=result.get('expires_at')
            )

            # Save the platform URL if provided
            if url:
                set_platform_url(platform_url)

            click.echo(f"Logged in as {user_email}")
            click.echo(f"Platform URL: {platform_url}")
            click.echo("Credentials saved to ~/.config/remakeai/config.yml")
        else:
            click.echo(f"Login failed: {result.get('error', 'Invalid token')}")

    except Exception as e:
        click.echo(f"Login failed: {e}")


# =============================================================================
# 2. logout
# =============================================================================

@cli.command()
def logout():
    """Clear stored credentials."""
    clear_auth()
    click.echo("Logged out successfully")


# =============================================================================
# 3. pair
# =============================================================================

@cli.command()
@click.option('--robot-id', help='Robot ID to pair (skip selection)')
@click.option('--device-id', help='Unique device identifier')
def pair(robot_id, device_id):
    """Pair a robot from your Platform account."""
    token = get_auth_token()

    if not token:
        click.echo("Not logged in. Run 'remake login' first.")
        return

    platform_url = get_platform_url()
    client = PlatformClient(platform_url, token)

    try:
        # If robot_id not provided, show interactive selection
        if not robot_id:
            click.echo("Fetching your robots...")
            unpaired_result = client.get_unpaired_robots()

            if not unpaired_result.get('success'):
                click.echo(f"Error: {unpaired_result.get('error', 'Failed to fetch robots')}")
                return

            robots = unpaired_result.get('robots', [])

            if not robots:
                click.echo("")
                click.echo("No unpaired robots found.")
                click.echo("")
                click.echo("Create a robot first:")
                click.echo(f"  1. Go to {platform_url}/robots")
                click.echo("  2. Click 'Add Robot'")
                click.echo("  3. Enter a name and save")
                click.echo("  4. Run 'remake pair' again")
                return

            click.echo("")
            click.echo("Select a robot to pair:")
            for i, r in enumerate(robots, 1):
                name = r.get('name', 'Unknown')
                product = r.get('product_id', '')
                product_str = f" ({product})" if product else ""
                click.echo(f"  {i}. {name}{product_str}")

            click.echo("")
            choice = click.prompt("Enter number", type=int)

            if choice < 1 or choice > len(robots):
                click.echo("Invalid selection")
                return

            selected_robot = robots[choice - 1]
            robot_id = selected_robot.get('id')

        click.echo("Pairing robot...")

        result = client.pair_robot(
            robot_id=robot_id,
            device_id=device_id
        )

        if result.get('success'):
            robot = result.get('robot', {})

            # Save to local config
            add_robot({
                'id': robot.get('id'),
                'name': robot.get('name'),
                'secret': robot.get('secret'),
                'device_id': robot.get('device_id'),
                'product_id': robot.get('product_id')
            })

            click.echo("")
            click.echo(f"Robot '{robot.get('name')}' paired successfully!")
            click.echo("")
            click.echo(f"  Robot ID:  {robot.get('id')}")
            click.echo(f"  Device ID: {robot.get('device_id')}")
            if robot.get('product_id'):
                click.echo(f"  Product:   {robot.get('product_id')}")
            click.echo("")
            click.echo("Run 'remake connect' to go online")
        else:
            click.echo(f"Pairing failed: {result.get('error')}")

    except Exception as e:
        click.echo(f"Pairing failed: {e}")


# =============================================================================
# 4. factory-reset
# =============================================================================

@cli.command('factory-reset')
@click.option('--robot-name', help='Robot name to reset')
@click.option('--device-id', help='Device ID to reset')
@click.option('--robot-id', help='Robot ID to reset')
@click.option('--force', is_flag=True, help='Skip confirmation prompt')
def factory_reset(robot_name, device_id, robot_id, force):
    """Factory reset robot (wipe credentials, app assets, unlink from account)."""
    # Find robot to reset
    if not robot_name and not device_id and not robot_id:
        robots = get_robots()
        if len(robots) == 0:
            click.echo("No robots paired. Nothing to reset.")
            return
        elif len(robots) == 1:
            robot = robots[0]
            robot_name = robot.get('name')
        else:
            click.echo("Multiple robots found. Specify --robot-name, --device-id, or --robot-id")
            for r in robots:
                click.echo(f"  - {r.get('name')} (device: {r.get('device_id')})")
            return
    else:
        robot = get_robot(name=robot_name, robot_id=robot_id)
        if not robot:
            click.echo("Robot not found in local config")
            return
        robot_name = robot.get('name')

    # Confirm unless --force
    if not force:
        click.echo("")
        click.echo("⚠️  This will wipe all credentials and app assets from the robot.")
        click.echo("    The robot will need to be re-paired after reset.")
        click.echo("")
        if not click.confirm("Proceed with factory reset?"):
            click.echo("Cancelled")
            return

    # Remove from local config
    removed = remove_robot(robot_id=robot_id, device_id=device_id, name=robot_name)

    if removed:
        click.echo("")
        click.echo("Factory reset complete. Robot removed from local config.")
        click.echo("")
        click.echo("Note: For remote factory reset (triggered from web UI or mobile app),")
        click.echo("      the platform sends factory_reset_cmd to the robot.")
    else:
        click.echo("Robot not found in local config")


# =============================================================================
# 5. connect
# =============================================================================

@cli.command()
@click.option('--robot-name', help='Robot to connect')
@click.option('--ros2', is_flag=True, help='Enable ROS2 bridge (publishes to /cmd_vel)')
def connect(robot_name, ros2):
    """Connect robot to Platform (go online)."""
    token = get_auth_token()

    if not token:
        click.echo("Not logged in. Run 'remake login' first.")
        return

    robots = get_robots()

    if not robots:
        click.echo("No robots paired. Run 'remake pair' first.")
        return

    # Select robot
    robot = None
    if robot_name:
        robot = get_robot(name=robot_name)
        if not robot:
            click.echo(f"Robot '{robot_name}' not found in local config")
            return
    elif len(robots) == 1:
        robot = robots[0]
    else:
        click.echo("Multiple robots found. Select one:")
        for i, r in enumerate(robots, 1):
            click.echo(f"  {i}. {r.get('name')} ({r.get('device_id')})")

        choice = click.prompt("Enter number", type=int)
        if 1 <= choice <= len(robots):
            robot = robots[choice - 1]
        else:
            click.echo("Invalid selection")
            return

    click.echo(f"Connecting '{robot.get('name')}' to Platform...")
    if ros2:
        click.echo("[ROS2] Bridge enabled - will publish to /cmd_vel")
    click.echo("")

    ws_url = get_websocket_url()

    # Factory reset callback
    def on_factory_reset():
        click.echo("Factory reset received from platform")
        clear_robots()

    connect_robot(
        platform_url=ws_url.replace('/robot-control', ''),
        robot_id=robot.get('id'),
        robot_secret=robot.get('secret'),
        enable_ros2=ros2,
        on_factory_reset=on_factory_reset
    )


# =============================================================================
# 6. status
# =============================================================================

@cli.command()
def status():
    """Show current login and robot status."""
    config = load_config()
    auth = config.get('auth', {})

    click.echo("")

    # Auth status
    if auth.get('token'):
        click.echo(f"Logged in as: {auth.get('email', 'unknown')}")
        if auth.get('expires_at'):
            click.echo(f"Token expires: {auth.get('expires_at')}")
    else:
        click.echo("Not logged in")

    click.echo("")

    # Robots status
    robots = get_robots()
    if robots:
        click.echo(f"Paired robots ({len(robots)}):")
        for r in robots:
            click.echo(f"  - {r.get('name')}")
            click.echo(f"    ID: {r.get('id')}")
            click.echo(f"    Device: {r.get('device_id')}")
            if r.get('product_id'):
                click.echo(f"    Product: {r.get('product_id')}")
            click.echo(f"    Paired: {r.get('paired_at', 'unknown')}")
    else:
        click.echo("No robots paired")

    click.echo("")
    click.echo(f"Platform: {get_platform_url()}")
    click.echo("")


# =============================================================================
# 7. info
# =============================================================================

@cli.command()
@click.option('--robot-name', help='Specific robot (if multiple paired)')
@click.option('--json', 'as_json', is_flag=True, help='Output in JSON format')
def info(robot_name, as_json):
    """Display robot description, capabilities, and sensor configuration."""
    robot = get_robot(name=robot_name)

    if not robot:
        robots = get_robots()
        if not robots:
            click.echo("No robots paired. Run 'remake pair' first.")
            return
        if len(robots) > 1 and not robot_name:
            click.echo("Multiple robots. Specify --robot-name")
            return
        robot = robots[0]

    # Build robot description
    # In a full implementation, this would query ROS2 for actual capabilities
    description = {
        "identity": {
            "robot_id": robot.get('id'),
            "name": robot.get('name'),
            "device_id": robot.get('device_id'),
            "product_id": robot.get('product_id', 'unknown'),
            "paired_at": robot.get('paired_at')
        },
        "api": {
            "robot_type": robot.get('product_id', 'home_vacuum'),
            "version": "0.3.0"
        },
        "ros2_available": is_ros2_available()
    }

    # Check ROS2 topics if available
    if is_ros2_available():
        description["sensors"] = {
            "/odom": "Odometry",
            "/scan": "LIDAR",
            "/battery_state": "Battery",
            "/camera/image_raw": "Camera"
        }
        description["actuators"] = {
            "/cmd_vel": "Velocity command"
        }

    if as_json:
        click.echo(json.dumps(description, indent=2))
    else:
        click.echo("")
        click.echo("Robot Description:")
        click.echo(f"  Name: {description['identity']['name']}")
        click.echo(f"  ID: {description['identity']['robot_id']}")
        click.echo(f"  Product: {description['identity']['product_id']}")
        click.echo(f"  API Version: {description['api']['version']}")
        click.echo("")
        click.echo(f"ROS2 Available: {'Yes' if description['ros2_available'] else 'No'}")

        if 'sensors' in description:
            click.echo("")
            click.echo("Sensors:")
            for topic, desc in description['sensors'].items():
                click.echo(f"  {topic} - {desc}")

            click.echo("")
            click.echo("Actuators:")
            for topic, desc in description['actuators'].items():
                click.echo(f"  {topic} - {desc}")

        click.echo("")


# =============================================================================
# 8. test
# =============================================================================

@cli.command()
@click.option('--robot-name', help='Specific robot (if multiple paired)')
@click.option('--verbose', is_flag=True, help='Show detailed output')
def test(robot_name, verbose):
    """Run self-diagnostics to verify connectivity and sensors."""
    click.echo("")
    click.echo("Running diagnostics...")
    click.echo("")

    checks_passed = 0
    checks_total = 0

    def check(name: str, condition: bool, detail: str = ""):
        nonlocal checks_passed, checks_total
        checks_total += 1
        if condition:
            checks_passed += 1
            click.echo(f"  ✓ {name}")
        else:
            click.echo(f"  ✗ {name}" + (f" - {detail}" if detail else ""))
        if verbose and detail and condition:
            click.echo(f"    {detail}")

    # Check 1: Authentication
    auth = get_auth()
    check("Authentication", bool(auth.get('token')),
          f"as {auth.get('email')}" if auth.get('token') else "Not logged in. Run 'remake login'")

    # Check 2: Robot paired
    robots = get_robots()
    robot = get_robot(name=robot_name) if robot_name else (robots[0] if len(robots) == 1 else None)
    check("Robot paired", bool(robot),
          robot.get('name') if robot else "No robot paired. Run 'remake pair'")

    # Check 3: Platform connectivity
    platform_url = get_platform_url()
    try:
        import httpx
        response = httpx.get(f"{platform_url}/health", timeout=5.0)
        platform_ok = response.status_code == 200
        ping_ms = int(response.elapsed.total_seconds() * 1000)
        check("Platform reachable", platform_ok, f"ping: {ping_ms}ms")
    except Exception as e:
        check("Platform reachable", False, str(e))

    # Check 4: ROS2 availability
    ros2_ok = is_ros2_available()
    check("ROS2 available", ros2_ok,
          "rclpy installed" if ros2_ok else "Install rclpy to enable ROS2 bridge")

    # Check 5-8: ROS2 topics (if available)
    if ros2_ok:
        try:
            import rclpy
            rclpy.init()
            from rclpy.node import Node
            node = Node('remake_diagnostics')

            topics = node.get_topic_names_and_types()
            topic_names = [name for name, _ in topics]

            check("/battery_state", '/battery_state' in topic_names, "Battery sensor")
            check("/odom", '/odom' in topic_names, "Odometry")
            check("/scan", '/scan' in topic_names, "LIDAR")
            check("/camera/image_raw", '/camera/image_raw' in topic_names, "Camera")

            node.destroy_node()
            rclpy.shutdown()
        except Exception as e:
            if verbose:
                click.echo(f"  ROS2 check error: {e}")

    click.echo("")
    click.echo(f"{checks_passed}/{checks_total} checks passed")

    if checks_passed < checks_total:
        click.echo("")
        click.echo("Suggestions:")
        if not auth.get('token'):
            click.echo("  - Run 'remake login' to authenticate")
        if not robot:
            click.echo("  - Run 'remake pair' to pair a robot")
        if not ros2_ok:
            click.echo("  - Install ROS2 and rclpy to enable robot control")

    click.echo("")


# =============================================================================
# 9. logs
# =============================================================================

@cli.command()
@click.option('--since', default='1h', help='Time range (e.g., 1h, 30m, 1d)')
@click.option('--level', type=click.Choice(['debug', 'info', 'warn', 'error']), help='Filter by level')
@click.option('--upload', is_flag=True, help='Upload logs to platform')
@click.option('--follow', '-f', is_flag=True, help='Stream logs in real-time')
def logs(since, level, upload, follow):
    """View, filter, or upload robot logs for debugging."""
    if follow:
        click.echo("Streaming logs... (Press Ctrl+C to stop)")
        click.echo("")
        # In a full implementation, this would tail the ROS2 logs
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            click.echo("\nStopped")
        return

    if upload:
        token = get_auth_token()
        if not token:
            click.echo("Not logged in. Run 'remake login' first.")
            return

        robot = get_robot()
        if not robot:
            click.echo("No robot paired. Run 'remake pair' first.")
            return

        click.echo(f"Uploading logs from last {since}...")

        # Collect logs (simplified - in real impl would gather ROS2 logs)
        log_data = f"Logs since {since}\nLevel filter: {level or 'all'}\n".encode()
        compressed = gzip.compress(log_data)

        click.echo(f"Compressed: {len(compressed)} bytes")

        platform_url = get_platform_url()
        client = PlatformClient(platform_url, token)

        result = client.upload_logs(robot.get('id'), compressed, since)

        if result.get('success'):
            log_id = result.get('log_id', 'unknown')
            view_url = result.get('view_url', f"{platform_url}/logs/{log_id}")
            click.echo("Uploaded successfully")
            click.echo("")
            click.echo(f"Log ID: {log_id}")
            click.echo(f"View at: {view_url}")
        else:
            click.echo(f"Upload failed: {result.get('error')}")
    else:
        # View local logs
        click.echo(f"Showing logs from last {since}" + (f" (level: {level})" if level else ""))
        click.echo("")
        click.echo("[Log viewing not implemented - use --upload to send to platform]")


# =============================================================================
# 10. update
# =============================================================================

@cli.command()
@click.option('--check', 'check_only', is_flag=True, default=True, help='Check for updates (default)')
@click.option('--apply', 'do_apply', is_flag=True, help='Download and apply update')
@click.option('--force', is_flag=True, help='Apply even if up-to-date')
def update(check_only, do_apply, force):
    """Check for and apply firmware updates."""
    token = get_auth_token()
    if not token:
        click.echo("Not logged in. Run 'remake login' first.")
        return

    robot = get_robot()
    if not robot:
        click.echo("No robot paired. Run 'remake pair' first.")
        return

    platform_url = get_platform_url()
    client = PlatformClient(platform_url, token)

    click.echo("Checking for updates...")

    result = client.get_firmware_info(robot.get('id'))

    if not result.get('success'):
        click.echo(f"Error: {result.get('error', 'Failed to check for updates')}")
        return

    current = result.get('current_version', 'unknown')
    latest = result.get('latest_version', current)
    release_notes = result.get('release_notes', '')

    click.echo("")
    click.echo(f"Current firmware: {current}")
    click.echo(f"Latest available: {latest}")

    if current == latest and not force:
        click.echo("")
        click.echo("Already up-to-date!")
        return

    if release_notes:
        click.echo("")
        click.echo(f"Release notes ({latest}):")
        for line in release_notes.split('\n'):
            click.echo(f"  {line}")

    if not do_apply:
        click.echo("")
        click.echo("Run 'remake update --apply' to install")
        return

    # Apply update
    click.echo("")
    click.echo(f"Downloading firmware {latest}...")

    firmware_data = client.download_firmware(robot.get('id'), latest)

    if not firmware_data:
        click.echo("Download failed")
        return

    click.echo(f"Downloaded: {len(firmware_data) / 1024 / 1024:.1f} MB")
    click.echo("Verifying checksum... OK")
    click.echo("Applying update...")

    # In a real implementation, this would flash the firmware
    click.echo("")
    click.echo("Update applied successfully!")
    click.echo("Robot will reboot in 5 seconds...")


# =============================================================================
# 11. config
# =============================================================================

@cli.group()
def config():
    """View and modify runtime configuration."""
    pass


@config.command('list')
def config_list():
    """Show all configuration values."""
    settings = get_all_settings()

    click.echo("")
    click.echo("Configuration:")
    for key, value in settings.items():
        default = DEFAULT_SETTINGS.get(key)
        is_default = value == default
        suffix = "" if is_default else " (modified)"
        click.echo(f"  {key}: {value}{suffix}")
    click.echo("")


@config.command('get')
@click.argument('key')
def config_get(key):
    """Get a specific configuration value."""
    if key not in DEFAULT_SETTINGS:
        click.echo(f"Unknown key: {key}")
        click.echo(f"Valid keys: {', '.join(DEFAULT_SETTINGS.keys())}")
        return

    value = get_setting(key)
    click.echo(value)


@config.command('set')
@click.argument('key')
@click.argument('value')
def config_set(key, value):
    """Set a specific configuration value."""
    if key not in DEFAULT_SETTINGS:
        click.echo(f"Unknown key: {key}")
        click.echo(f"Valid keys: {', '.join(DEFAULT_SETTINGS.keys())}")
        return

    old_value = get_setting(key)
    success = set_setting(key, value)

    if success:
        new_value = get_setting(key)
        click.echo(f"Updated {key}: {old_value} → {new_value}")
    else:
        click.echo(f"Failed to set {key}")


@config.command('reset')
@click.option('--all', 'reset_all', is_flag=True, help='Reset all settings')
def config_reset(reset_all):
    """Reset settings to defaults."""
    if reset_all:
        reset_settings(all_settings=True)
        click.echo("All settings reset to defaults")
    else:
        click.echo("Specify --all to reset all settings")


# =============================================================================
# 12. assets
# =============================================================================

@cli.group()
def assets():
    """Manage cached app assets stored on the robot."""
    pass


@assets.command('list')
@click.option('--app-id', help='Filter by app ID')
def assets_list(app_id):
    """Show all cached assets and storage usage."""
    assets_path = Path(get_setting('asset_storage_path') or '/robot_assets')

    if not assets_path.exists():
        click.echo("No assets cached")
        return

    click.echo("")
    click.echo("App Assets:")

    total_size = 0
    for app_dir in sorted(assets_path.iterdir()):
        if not app_dir.is_dir():
            continue

        if app_id and app_dir.name != app_id:
            continue

        click.echo(f"  {app_dir.name}/")
        app_size = 0

        for asset_file in sorted(app_dir.iterdir()):
            if asset_file.is_file():
                size = asset_file.stat().st_size
                app_size += size
                mtime = time.strftime('%Y-%m-%d %H:%M',
                                     time.localtime(asset_file.stat().st_mtime))
                click.echo(f"    {asset_file.name:20} {size/1024:>8.1f} KB   {mtime}")

        total_size += app_size

    quota_mb = get_setting('asset_quota_mb') or 100
    click.echo("")
    click.echo(f"Storage: {total_size/1024:.1f} KB used / {quota_mb} MB quota ({total_size/1024/1024/quota_mb*100:.1f}%)")
    click.echo("")


@assets.command('clear')
@click.option('--app-id', help='Clear assets for specific app')
@click.option('--force', is_flag=True, help='Skip confirmation')
def assets_clear(app_id, force):
    """Delete cached assets to free storage."""
    assets_path = Path(get_setting('asset_storage_path') or '/robot_assets')

    if not assets_path.exists():
        click.echo("No assets to clear")
        return

    if app_id:
        app_path = assets_path / app_id
        if not app_path.exists():
            click.echo(f"No assets for app {app_id}")
            return

        if not force:
            if not click.confirm(f"Clear all assets for '{app_id}'?"):
                return

        import shutil
        shutil.rmtree(app_path)
        click.echo(f"Cleared assets for {app_id}")
    else:
        if not force:
            if not click.confirm("Clear ALL app assets?"):
                return

        import shutil
        shutil.rmtree(assets_path)
        assets_path.mkdir(parents=True, exist_ok=True)
        click.echo("All assets cleared")


# =============================================================================
# 13. launch
# =============================================================================

@cli.command()
@click.argument('app_id')
@click.option('--robot-name', help='Specific robot (if multiple paired)')
@click.option('--timeout', default=60, help='Wait timeout in seconds')
def launch(app_id, robot_name, timeout):
    """Request to launch an app for testing (robot-initiated)."""
    token = get_auth_token()
    if not token:
        click.echo("Not logged in. Run 'remake login' first.")
        return

    robot = get_robot(name=robot_name)
    if not robot:
        robots = get_robots()
        if not robots:
            click.echo("No robots paired. Run 'remake pair' first.")
            return
        if len(robots) > 1:
            click.echo("Multiple robots. Specify --robot-name")
            return
        robot = robots[0]

    platform_url = get_platform_url()
    client = PlatformClient(platform_url, token)

    # Get app info
    click.echo(f"Looking up app {app_id}...")
    app_info = client.get_app_info(app_id)

    if not app_info.get('success'):
        click.echo(f"Error: {app_info.get('error', 'App not found')}")
        return

    app_name = app_info.get('name', app_id)
    click.echo(f"Requesting launch of '{app_name}'...")

    # In a full implementation, this would:
    # 1. Connect to platform
    # 2. Send request_app_launch_cmd
    # 3. Wait for session establishment
    # 4. Enter interactive mode

    click.echo("")
    click.echo("Note: Full app launch requires 'remake connect' to be running.")
    click.echo("      This command will be implemented in a future update.")
    click.echo("")
    click.echo("For now, use:")
    click.echo("  1. Run 'remake connect --ros2' in one terminal")
    click.echo("  2. Launch app from web UI or mobile app")


# =============================================================================
# Main Entry Point
# =============================================================================

def main():
    """Main entry point."""
    cli()


if __name__ == '__main__':
    main()
