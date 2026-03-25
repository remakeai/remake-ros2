# remakeai

ROS2 App Bridge for the [Remake.ai](https://remake.ai) robot app platform. Enables containerized apps to control ROS2 robots through a standardized Socket.IO protocol.

## What It Does

The App Bridge connects containerized apps to ROS2 robots:

```
App Container                    App Bridge                         ROS2
─────────────                    ──────────                         ────
                  Socket.IO
 RobotClient ◄──────────────► AppBridgeNode
                                    │
                                    ├── ROS2Bridge ◄──► /cmd_vel, /odom, /scan, ...
                                    │                   /navigate_to_pose (action)
                                    │
                                    └── ServiceManager
                                          ├── ros2 launch ... physical.launch.py
                                          ├── ros2 launch ... navigation.launch.py
                                          └── ros2 launch ... navigation.launch.py slam:=True
```

**Three components:**

| Component | Module | Purpose |
|-----------|--------|---------|
| **AppBridgeNode** | `app_bridge_node.py` | Socket.IO server implementing [ROBOT_APP_API.md](https://github.com/remakeai/architecture/blob/main/v2/ROBOT_APP_API.md) |
| **ROS2Bridge** | `ros2_bridge.py` | Converts ROS2 topics/actions to/from App API JSON |
| **ServiceManager** | `service_manager.py` | Starts/stops ROS2 launch files via `services.yaml` config |

## Quick Start

```bash
# Source ROS2
source /opt/ros/jazzy/setup.bash

# Build the package
cd /ros_ws
colcon build --packages-select remakeai
source install/setup.bash

# Start the App Bridge
ros2 launch remakeai app_bridge.launch.py robot_id:=my-robot
```

Apps can now connect to `http://<robot-ip>:8788` using the Remake SDK:

```python
from remake_sdk.socketio import RobotClient

client = RobotClient(socket_url="http://robot-ip:8788", app_id="com.example.myapp")
await client.connect()
await client.move(linear_x=0.3)
await client.stop()
```

## Launch Parameters

```bash
ros2 launch remakeai app_bridge.launch.py \
    host:=0.0.0.0 \
    port:=8788 \
    robot_id:=my-robot \
    services:=/path/to/services.yaml
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `host` | `0.0.0.0` | Socket.IO server bind address |
| `port` | `8788` | Socket.IO server port |
| `robot_id` | `remake-robot` | Robot ID sent in welcome message |
| `services` | `<pkg>/config/services.yaml` | Robot-specific service configuration |

## ROS2 Topics

### Subscribed (sensor data → apps)

| Topic | Type | App API Event |
|-------|------|---------------|
| `/odom` | `nav_msgs/Odometry` | `pose_data` |
| `/scan` | `sensor_msgs/LaserScan` | `scan_data` |
| `/battery_state` | `sensor_msgs/BatteryState` | `battery_data` |
| `/camera/image_raw` | `sensor_msgs/Image` | `camera_data` |
| `/imu/data` | `sensor_msgs/Imu` | `imu_data` |
| `/map` | `nav_msgs/OccupancyGrid` | `map_data` |
| `/diagnostics` | `diagnostic_msgs/DiagnosticArray` | `health_data` |

### Published (app commands → ROS2)

| Topic | Type | App API Command |
|-------|------|-----------------|
| `/cmd_vel` | `geometry_msgs/Twist` | `move_cmd`, `stop_cmd` |

### Action Clients

| Action | Type | App API Command |
|--------|------|-----------------|
| `/navigate_to_pose` | `nav2_msgs/NavigateToPose` | `navigate_cmd` |

## Service Management

The `ServiceManager` maps abstract `service_cmd` requests from apps to robot-specific `ros2 launch` commands, configured via `services.yaml`.

### services.yaml (Kaiaai robot example)

```yaml
robot:
  id: kaiaai

services:
  bringup:
    type: launch
    package: kaiaai_bringup
    launch_file: physical.launch.py
    depends_on: []

  navigation:
    type: launch
    package: kaiaai_bringup
    launch_file: navigation.launch.py
    args:
      map: "{map_path}"
      slam: "False"
    depends_on: [bringup]
    conflicts_with: [slam]

  slam:
    type: launch
    package: kaiaai_bringup
    launch_file: navigation.launch.py
    args:
      slam: "True"
    depends_on: [bringup]
    conflicts_with: [navigation]

maps:
  directory: "~/maps"
```

**Features:**
- Dependency resolution (starting `navigation` auto-starts `bringup`)
- Conflict detection (`slam` and `navigation` can't run simultaneously)
- Graceful shutdown (SIGINT → SIGTERM → SIGKILL with configurable timeout)
- Crash monitoring with `service_event` error reporting

To support a different robot, create a new `services.yaml` mapping that robot's launch files.

## Package Structure

```
remakeai/
├── remakeai/
│   ├── __init__.py
│   ├── app_bridge_node.py     # Socket.IO server + protocol handling
│   ├── ros2_bridge.py         # ROS2 ↔ App API conversion
│   ├── service_manager.py     # ros2 launch subprocess management
│   └── api.py                 # Platform REST API client
├── config/
│   └── services.yaml          # Robot-specific service definitions
├── launch/
│   └── app_bridge.launch.py   # ROS2 launch file
├── package.xml
└── setup.py
```

## Dependencies

- Python 3.10+
- ROS2 Jazzy (or later)
- python-socketio >= 5.0.0
- aiohttp >= 3.8.0
- pyyaml >= 6.0
- httpx >= 0.24.0

## Related

- [Remake SDK](https://github.com/remakeai/remake-sdk) (`~/remake-sdk`) - Python SDK with `RobotClient`, CLI, container runtime
- [Architecture Docs](https://github.com/remakeai/architecture) (`~/architecture/v2/`) - Protocol specs (ROBOT_APP_API.md, API_SENSOR_DATA.md)

## License

Apache-2.0
