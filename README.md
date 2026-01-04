# remakeai

ROS2 platform client for [Remake.ai](https://remake.ai) - connect your robot to the Remake.ai platform and run third-party robot apps.

## Features

- **CLI Tool** (`remake`) - Pair, connect, and manage robots from the command line
- **Platform Connection** - Socket.IO client with HMAC-SHA256 authentication
- **ROS2 Bridge** - Bridge between ROS2 topics and platform commands
- **App Sessions** - Direct WebSocket connections to robot apps

## Quick Start

### Installation (ROS2 Workspace)

```bash
# Source ROS2
source /opt/ros/jazzy/setup.bash

# Create workspace (if needed)
mkdir -p ~/ros2_ws/src
cd ~/ros2_ws/src

# Clone the repository
git clone https://github.com/remakeai/remakeai_ros2.git remakeai

# Install dependencies
cd ~/ros2_ws
rosdep install --from-paths src --ignore-src -r -y

# Build the package
colcon build --symlink-install

# Source the workspace
source install/setup.bash
```

### Authentication

```bash
# Login with your platform token
remake login

# Follow the prompts to enter your CLI token from https://apps.remake.ai/tokens
```

### Pair a Robot

```bash
# Pair a robot from your account
remake pair

# Select from your available robots
```

### Connect to Platform

```bash
# Connect without ROS2 (for testing)
remake connect

# Connect with ROS2 bridge enabled
remake connect --ros2
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `remake login` | Authenticate with platform |
| `remake logout` | Clear stored credentials |
| `remake pair` | Pair a robot from your account |
| `remake factory-reset` | Factory reset (wipe credentials and assets) |
| `remake connect` | Connect robot to platform |
| `remake status` | Show login and robot status |
| `remake info` | Display robot capabilities |
| `remake test` | Run self-diagnostics |
| `remake logs` | View or upload robot logs |
| `remake update` | Check for firmware updates |
| `remake config` | View/modify runtime configuration |
| `remake assets` | Manage cached app assets |
| `remake launch` | Launch an app for testing |

### Examples

```bash
# Check current status
remake status

# Run diagnostics
remake test --verbose

# View configuration
remake config list

# Set a config value
remake config set sensor_publish_rate 20.0

# Upload logs for debugging
remake logs --upload --since 1h

# Check for updates
remake update --check
```

## Configuration

### Config File

Location: `~/.config/remakeai/config.yml`

```yaml
platform:
  url: https://apps.remake.ai

auth:
  token: cli_xxx...
  email: user@example.com

robots:
  - id: robot-abc-123
    name: My Robot
    secret: robot_secret_xxx...
    device_id: '00:11:22:33:44:55'

settings:
  platform_url: https://apps.remake.ai
  websocket_url: wss://apps.remake.ai/robot-control
  sensor_publish_rate: 10.0
  camera_jpeg_quality: 85
  asset_quota_mb: 100
  reconnect_interval: 5.0
  log_level: info
```

### Configuration Options

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `platform_url` | string | `https://apps.remake.ai` | Platform REST API URL |
| `websocket_url` | string | `wss://apps.remake.ai/robot-control` | Platform WebSocket URL |
| `sensor_publish_rate` | float | `10.0` | Sensor data publish rate (Hz) |
| `camera_jpeg_quality` | int | `85` | JPEG compression quality (1-100) |
| `asset_quota_mb` | int | `100` | Per-app asset storage quota (MB) |
| `reconnect_interval` | float | `5.0` | Reconnection retry interval (seconds) |
| `log_level` | string | `info` | Logging level (debug/info/warn/error) |

### Environment Variables

| Variable | Description |
|----------|-------------|
| `ROBOT_SECRET` | Robot authentication secret (recommended over config file) |
| `PLATFORM_URL` | Override platform URL |
| `ROBOT_ID` | Override robot ID |

## ROS2 Integration

When running with `--ros2` flag, the package bridges these topics:

### Subscribed Topics (Robot → Platform)

| Topic | Message Type | Description |
|-------|-------------|-------------|
| `/battery_state` | `sensor_msgs/BatteryState` | Battery level and status |
| `/odom` | `nav_msgs/Odometry` | Robot pose and velocity |
| `/scan` | `sensor_msgs/LaserScan` | LIDAR data |
| `/camera/image_raw` | `sensor_msgs/Image` | Camera images |

### Published Topics (Platform → Robot)

| Topic | Message Type | Description |
|-------|-------------|-------------|
| `/cmd_vel` | `geometry_msgs/Twist` | Velocity commands |

### Action Clients

| Action | Type | Description |
|--------|------|-------------|
| `/navigate_to_pose` | `nav2_msgs/NavigateToPose` | Autonomous navigation |

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      ROS2 Robot Firmware                         │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  remakeai Package                                        │    │
│  │  ┌─────────────────┐  ┌─────────────────┐               │    │
│  │  │ websocket_client│  │   ros2_bridge   │               │    │
│  │  │ (Socket.IO)     │  │ (Topics/Actions)│               │    │
│  │  └────────┬────────┘  └────────┬────────┘               │    │
│  └───────────┼────────────────────┼─────────────────────────┘    │
└──────────────┼────────────────────┼──────────────────────────────┘
               │                    │
               ▼                    ▼
          Platform              /cmd_vel
       (WebSocket/WSS)         /odom, /scan, etc.
```

## Security

- Credentials stored with `chmod 600` (owner read/write only)
- HMAC-SHA256 challenge-response authentication (secrets never sent directly)
- Robot secrets should be set via environment variable `ROBOT_SECRET`
- TLS/WSS for all platform connections

## Troubleshooting

### "Not logged in" error

```bash
remake login
# Enter your CLI token from https://apps.remake.ai/tokens
```

### "No robots paired" error

```bash
remake pair
# Select a robot from your account
```

### Connection issues

```bash
# Run diagnostics
remake test --verbose

# Check platform connectivity
remake status
```

### ROS2 bridge not working

Ensure ROS2 is installed and sourced:

```bash
source /opt/ros/jazzy/setup.bash
remake connect --ros2
```

## Development

### With ROS2

```bash
# Build with symlink for development
cd ~/ros2_ws
colcon build --symlink-install --packages-select remakeai

# Run tests
colcon test --packages-select remakeai
colcon test-result --verbose
```

### Standalone (without ROS2)

```bash
# Install in development mode
pip install -e .

# Run tests
pytest

# Check syntax
python3 -m py_compile remakeai/*.py
```

## Dependencies

- Python 3.10+
- click >= 8.0.0
- httpx >= 0.24.0
- python-socketio[client] >= 5.0.0
- pyyaml >= 6.0
- rclpy
- ROS2 Jazzy or later

## License

Apache-2.0

## Links

- [Remake.ai Platform](https://remake.ai)
- [GitHub Repository](https://github.com/remakeai/remakeai_ros2)