# Core Components

## 12 Module Architecture

### 1. platform_client_node.py (~900 lines)
**Robot Management API Socket.IO Client**

Main component that connects robot to Remake.AI platform.

**Key Classes:**
- `PlatformClientConfig` - Configuration dataclass
- `CommandTracker` - Tracks in-flight commands with timeouts
- `RobotDescription` - Auto-discovers robot capabilities
- `AppSession` - Single app session state management
- `PlatformClientNode` - Main ROS2 node with all event handlers

**Key Features:**
- HMAC-SHA256 challenge-response authentication
- 3-phase app launch protocol handling
- Heartbeat/ping with RTT calculation
- Command correlation via cmd_id
- Exponential backoff reconnection (1s → 30s max)

**Key Event Handlers:**
```
authenticate_challenge    → Compute HMAC signature
authenticate_result       → Confirm authentication
ping_response            → Calculate RTT
establish_app_session_cmd → Phase 1 session setup
setup_app_cmd            → Phase 2 resource preparation
enable_remote_control_cmd → Phase 3 control enablement
terminate_app_cmd        → Clean up session
factory_reset_cmd        → Reset robot state
```

---

### 2. app_session_manager.py (~800 lines)
**Per-App WebSocket Handler**

Manages connection to specific app when session is active.

**Key Classes:**
- `AppConnection` - Single app WebSocket connection
- `AppSessionManager` - Manages active app sessions
- `SessionState` - Tracks connection lifecycle

**Key Features:**
- Dual WebSocket architecture (platform + app)
- Command relay between app and robot
- Automatic connection management
- Error handling and recovery
- Session state validation

**Responsibilities:**
- Connect to app WebSocket URL
- Relay move commands from app
- Send sensor data to app
- Handle app disconnection
- Clean up on termination

---

### 3. ros2_bridge.py (~3000+ lines)
**ROS2 Sensor & Action Integration**

Bridges ROS2 topics/actions to Socket.IO events.

**Sensors Published:**
| Sensor | Topic | Frequency | Size |
|--------|-------|-----------|------|
| LaserScan | /scan | 2 Hz (0.5s) | ~50 KB |
| Battery | /battery_state | 0.5 Hz (2s) | ~200 B |
| Pose | /odom | 2 Hz (0.5s) | ~150 B |
| Map | /map | 0.2 Hz (5s) | ~150-300 KB |
| Camera | /color_camera/image_raw | 5 Hz (0.2s) | ~30-50 KB |

**Commands Handled:**
- `move_cmd` → Publish to `/cmd_vel`
- `stop_cmd` → Publish zero velocities
- `navigate_to_pose` → Call Nav2 action
- `cancel_navigation` → Cancel Nav2 action

**Key Features:**
- Rate limiting with deduplication
- Data compression (JPEG for camera, base64)
- Quaternion normalization
- TF frame management
- Occupancy grid encoding

---

### 4. asset_manager.py (~600 lines)
**Per-App File Storage with Quota**

Manages file upload/download/delete for each app.

**Key Classes:**
- `FileMetadata` - File information
- `AssetManager` - File operations manager
- `QuotaTracker` - Quota enforcement

**Key Features:**
- Per-app quotas (default 100MB)
- Path traversal attack prevention
- SHA256 integrity verification
- File size limits (max 50MB or 50% quota)
- Separate storage per app
- Delete with quota recovery

**Operations:**
```
upload_file(app_id, filename, data)
download_file(app_id, filename)
delete_file(app_id, filename)
list_files(app_id)
get_app_usage_bytes(app_id)
get_app_remaining_quota_bytes(app_id)
```

---

### 5. cli.py (~1500+ lines)
**13 Command-Line Commands**

Command-line interface for user interaction.

**Commands:**
1. `remake login` - OAuth login
2. `remake logout` - Clear credentials
3. `remake pair` - Pair new robot
4. `remake unpair` - Remove robot
5. `remake robots` - List paired robots
6. `remake connect` - Connect to platform
7. `remake status` - Show system status
8. `remake info` - Show robot/app info
9. `remake logs` - Display system logs
10. `remake config` - Manage configuration
11. `remake assets` - Manage app assets
12. `remake launch` - Launch app
13. `remake factory-reset` - Factory reset

**Key Features:**
- Interactive prompts
- Config persistence
- Error handling
- Progress indicators
- Help documentation

---

### 6. cli_config.py (~500+ lines)
**Configuration Management**

Persistent storage for credentials and settings.

**Stored Data:**
- Auth tokens (with expiration)
- Robot credentials (per robot)
- Platform URLs
- Asset quotas
- Feature flags

**Key Functions:**
```
load_config() - Load from disk
get_auth_token() - Get current token
set_auth(token, email, expires_at) - Store auth
is_authenticated() - Check if logged in
get_robots() - List paired robots
add_robot(data) - Add new robot
get_setting(key) - Get config value
set_setting(key, value) - Set config value
```

**Storage Locations:**
- Linux/Mac: `~/.config/remake/config.json`
- Windows: `%APPDATA%\Remake\config.json`

---

### 7. websocket_client.py (~480 lines)
**Raw WebSocket Client**

Alternative to Socket.IO for direct connections.

**Key Classes:**
- `WebSocketClient` - Base WebSocket handler
- `AppWebSocketClient` - App connection handler
- `RobotWebSocketClient` - Robot connection handler

**Use Cases:**
- Direct app connections
- Fallback when Socket.IO unavailable
- Custom protocol implementations

---

### 8. api.py (~400+ lines)
**REST API Client**

HTTP client for Remake.AI REST endpoints.

**Endpoints Supported:**
- Authentication (login, refresh)
- Robot management (CRUD)
- App launching
- Session management
- Asset operations
- Firmware info
- Logging

**Key Methods:**
```
login(email, password) - Get auth token
get_robots() - List user's robots
launch_app(app_id, robot_id) - Start app
get_session(session_id) - Get session info
upload_asset(app_id, filename, data) - Store file
```

---

### 9. robot_client.py (~180 lines)
**Abstract Base Class**

Defines interface for robot client implementations.

**Key Classes:**
- `RobotClient` - Abstract base
- `RobotClientROS2` - ROS2 implementation
- `AppstoreRobotClient` - Appstore integration

**Methods:**
```
connect() - Connect to platform
disconnect() - Clean disconnect
publish_cmd_vel(linear_x, angular_z) - Send movement
subscribe_scan(callback) - Listen to laser
subscribe_battery(callback) - Listen to battery
navigate_to_pose(x, y, callback) - Navigate
```

---

### 10. message_callback_mixin.py (~120 lines)
**Pub/Sub Message Routing**

Mixin for event-based message handling.

**Features:**
- Message type routing
- Callback registration
- Message validation
- Error handling

**Pattern:**
```python
# Register handler
robot.on_message('laser_scan', handle_scan)

# Send message
robot.publish('cmd_vel', {'linear_x': 0.5})
```

---

### 11. launch/platform_client.launch.py
**ROS2 Launch Configuration**

Configures and starts platform client node.

**Parameters:**
- `platform_url` - Remake.AI platform URL
- `robot_id` - Robot identifier
- `robot_secret` - Authentication secret
- `enable_ros2` - Enable ROS2 bridge
- `ros2_domain_id` - ROS2 domain
- `log_level` - Debug/Info/Warn/Error

**Usage:**
```bash
ros2 launch remakeai platform_client.launch.py \
  platform_url:="wss://apps.remake.ai" \
  robot_id:="robot-001"
```

---

### 12. config/default_config.yaml
**Default Configuration**

Default settings for all parameters.

**Contents:**
```yaml
platform:
  url: "wss://apps.remake.ai"
  timeout_sec: 10
  reconnect_attempts: 5

robot:
  heartbeat_interval_sec: 30
  max_velocity_m_s: 0.5
  max_angular_velocity_rad_s: 2.0

sensors:
  laser_scan_hz: 2.0
  battery_hz: 0.5
  pose_hz: 2.0
  map_hz: 0.2
  camera_hz: 5.0

assets:
  quota_mb: 100.0
  max_file_size_mb: 50.0
```

---

## Component Dependencies

```
platform_client_node.py
├── websocket_client.py
├── ros2_bridge.py
├── asset_manager.py
├── cli_config.py
└── message_callback_mixin.py

app_session_manager.py
├── websocket_client.py
└── message_callback_mixin.py

cli.py
├── api.py
├── cli_config.py
├── platform_client_node.py
└── asset_manager.py

ros2_bridge.py
├── robot_client.py
└── message_callback_mixin.py
```

---

## Module Interactions

1. **User runs CLI** → `cli.py`
2. **CLI authenticates** → `api.py` + `cli_config.py`
3. **CLI connects robot** → `platform_client_node.py`
4. **Platform client connects** → `websocket_client.py`
5. **ROS2 topics flow** → `ros2_bridge.py`
6. **App launches** → `app_session_manager.py`
7. **Files stored** → `asset_manager.py`
8. **Sensor data streams** → `message_callback_mixin.py`

---

## Code Statistics

| Module | Lines | Purpose |
|--------|-------|---------|
| platform_client_node.py | 900 | Platform connection |
| ros2_bridge.py | 3000+ | Sensor integration |
| app_session_manager.py | 800 | App management |
| cli.py | 1500+ | User interface |
| cli_config.py | 500+ | Configuration |
| asset_manager.py | 600 | File storage |
| api.py | 400+ | REST client |
| websocket_client.py | 480 | WebSocket client |
| Others | 1000+ | Supporting modules |
| **TOTAL** | **~12,000** | **Complete system** |
