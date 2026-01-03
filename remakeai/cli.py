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
Remake CLI - Command-line tool for pairing robots with Appstore
"""
import click

from . import __version__
from .cli_config import (
    load_config, get_auth_token, set_auth, clear_auth,
    get_robots, add_robot, remove_robot, get_robot, get_appstore_url, set_appstore_url
)
from .api import AppstoreClient
from .websocket_client import connect_robot


@click.group()
@click.version_option(version=__version__, prog_name='remake')
def cli():
    """Remake CLI - Pair and connect robots to Appstore"""
    pass


@cli.command()
@click.option('--email', help='Account email (optional, for reference)')
@click.option('--url', help='Appstore URL (default: https://apps.remake.ai)')
def login(email, url):
    """Authenticate with Appstore using a CLI token"""
    config = load_config()

    # Check if already logged in
    existing_token = get_auth_token()
    if existing_token:
        existing_email = config.get('auth', {}).get('email', 'unknown')
        click.echo(f"Already logged in as {existing_email}")
        if not click.confirm("Login with a different account?"):
            return

    # Show instructions
    appstore_url = url or get_appstore_url()
    click.echo("")
    click.echo("To get your CLI token:")
    click.echo(f"  1. Go to {appstore_url}/tokens")
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
    client = AppstoreClient(appstore_url)

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

            # Save the appstore URL if provided
            if url:
                set_appstore_url(appstore_url)

            click.echo(f"Logged in as {user_email}")
            click.echo(f"Appstore URL: {appstore_url}")
            click.echo("Credentials saved to ~/.config/remakeai/config.yml")
        else:
            click.echo(f"Login failed: {result.get('error', 'Invalid token')}")

    except Exception as e:
        click.echo(f"Login failed: {e}")


@cli.command()
def logout():
    """Clear stored credentials"""
    clear_auth()
    click.echo("Logged out successfully")


@cli.command()
@click.option('--robot-id', help='Robot ID to pair (skip selection)')
@click.option('--device-id', help='Unique device identifier')
def pair(robot_id, device_id):
    """Pair a robot from your Appstore account"""
    token = get_auth_token()

    if not token:
        click.echo("Not logged in. Run 'remake login' first.")
        return

    appstore_url = get_appstore_url()
    client = AppstoreClient(appstore_url, token)

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
                click.echo(f"  1. Go to {appstore_url}/robots")
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


@cli.command()
@click.option('--robot-name', help='Robot name to unpair')
@click.option('--device-id', help='Device ID to unpair')
@click.option('--robot-id', help='Robot ID to unpair')
def unpair(robot_name, device_id, robot_id):
    """Remove a robot from Appstore"""
    token = get_auth_token()

    if not token:
        click.echo("Not logged in. Run 'remake login' first.")
        return

    # If no identifier provided, try to use default robot
    if not robot_name and not device_id and not robot_id:
        robots = get_robots()
        if len(robots) == 0:
            click.echo("No robots paired. Nothing to unpair.")
            return
        elif len(robots) == 1:
            robot = robots[0]
            robot_name = robot.get('name')
            click.echo(f"Unpairing robot '{robot_name}'...")
        else:
            click.echo("Multiple robots found. Specify --robot-name, --device-id, or --robot-id")
            for r in robots:
                click.echo(f"  - {r.get('name')} (device: {r.get('device_id')})")
            return

    appstore_url = get_appstore_url()
    client = AppstoreClient(appstore_url, token)

    try:
        result = client.unpair_robot(
            robot_name=robot_name,
            device_id=device_id,
            robot_id=robot_id
        )

        if result.get('success'):
            # Remove from local config
            remove_robot(robot_id=robot_id, device_id=device_id, name=robot_name)
            click.echo(result.get('message', 'Robot unpaired successfully'))
        else:
            click.echo(f"Unpair failed: {result.get('error')}")

    except Exception as e:
        click.echo(f"Unpair failed: {e}")


@cli.command()
@click.option('--robot-name', help='Robot to connect')
@click.option('--ros2', is_flag=True, help='Enable ROS2 bridge (publishes to /cmd_vel)')
def connect(robot_name, ros2):
    """Connect robot to Appstore (go online)"""
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
            status = "offline"
            click.echo(f"  {i}. {r.get('name')} ({r.get('device_id')}) - {status}")

        choice = click.prompt("Enter number", type=int)
        if 1 <= choice <= len(robots):
            robot = robots[choice - 1]
        else:
            click.echo("Invalid selection")
            return

    click.echo(f"Connecting '{robot.get('name')}' to Appstore...")
    if ros2:
        click.echo("[ROS2] Bridge enabled - will publish to /cmd_vel")
    click.echo("")

    appstore_url = get_appstore_url()

    # connect_robot is now synchronous (uses python-socketio)
    connect_robot(
        appstore_url=appstore_url,
        robot_id=robot.get('id'),
        robot_secret=robot.get('secret'),
        enable_ros2=ros2
    )


@cli.command()
def status():
    """Show current login and robot status"""
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

    # Appstore URL
    click.echo(f"Appstore: {get_appstore_url()}")
    click.echo("")


@cli.command()
def disconnect():
    """Placeholder for disconnect - connection ends with Ctrl+C"""
    click.echo("To disconnect, press Ctrl+C while 'remake connect' is running")


def main():
    """Main entry point"""
    cli()


if __name__ == '__main__':
    main()
