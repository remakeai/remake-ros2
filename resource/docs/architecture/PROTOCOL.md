# Communication Protocol

## Socket.IO Namespaces & Events

### /robot-control Namespace
**Robot ↔ Platform Communication**

This is the main namespace where robots authenticate and manage app sessions.

---

## Authentication Flow

### Step 1: Robot Sends authenticate_cmd
```json
{
  "robot_id": "robot-001",
  "robot_secret": "secret_key_xyz"
}
```

### Step 2: Platform Sends authenticate_challenge
```json
{
  "success": true,
  "nonce": "server_nonce_abc123def456"
}
```

### Step 3: Robot Computes HMAC-SHA256 Signature
```python
import hmac
import hashlib

signature = hmac.new(
    robot_secret.encode('utf-8'),
    nonce.encode('utf-8'),
    hashlib.sha256
).hexdigest()
```

### Step 4: Robot Sends authenticate_response
```json
{
  "signature": "a1b2c3d4e5f6..."  // 64 hex characters
}
```

### Step 5: Platform Sends authenticate_result
```json
{
  "success": true,
  "message": "Authenticated"
}
```

**Timeout:** 10 seconds
**Attempts:** 5 with exponential backoff (1s, 2s, 4s, 8s, 16s, then 30s max)

---

## Heartbeat/Ping System

### Robot Sends ping_cmd
```json
{
  "t1": 1000  // Client send time in milliseconds
}
```

**Frequency:** Every 30 seconds

### Platform Responds with ping_response
```json
{
  "t1": 1000,  // Original send time
  "t2": 1010,  // Server receive time
  "t3": 1020   // Server send time
}
```

### RTT Calculation
```python
t4 = time.time() * 1000  # Client receive time

# RTT = (t4 - t1) - (t3 - t2)
rtt_ms = (t4 - t1) - (t3 - t2)

# Clock offset = ((t2 - t1) + (t3 - t4)) / 2
clock_offset_ms = ((t2 - t1) + (t3 - t4)) / 2
```

**Purpose:** Measure network latency and detect clock skew

---

## Three-Phase App Launch Protocol

### Phase 1: Establish App Session

**Platform → Robot: establish_app_session_cmd**
```json
{
  "cmd_id": "cmd_123abc",
  "session_id": "sess_app_xyz",
  "app_id": "hello-world",
  "session_token": "token_xyz789",
  "app_ws_url": "wss://apps.remake.ai/sessions/sess_app_xyz",
  "connection_ticket": "ticket_abc123"
}
```

**Robot → Platform: establish_app_session_response**
```json
{
  "cmd_id": "cmd_123abc",
  "session_id": "sess_app_xyz",
  "status": "success"
}
```

**State Transition:** DISCONNECTED → CONNECTING → CONNECTED

**Timeout:** 10 seconds

---

### Phase 2: Setup App

**Platform → Robot: setup_app_cmd**
```json
{
  "cmd_id": "cmd_456def",
  "session_id": "sess_app_xyz"
}
```

**Robot → Platform: setup_app_response**
```json
{
  "cmd_id": "cmd_456def",
  "session_id": "sess_app_xyz",
  "status": "success",
  "installation_summary": {
    "state_restored": false,
    "assets_uploaded": 3
  }
}
```

**State Transition:** CONNECTED → SETTING_UP → READY

**Timeout:** 30 seconds

---

### Phase 3: Enable Remote Control

**Platform → Robot: enable_remote_control_cmd**
```json
{
  "cmd_id": "cmd_789ghi",
  "session_id": "sess_app_xyz"
}
```

**Robot → Platform: enable_remote_control_response**
```json
{
  "cmd_id": "cmd_789ghi",
  "session_id": "sess_app_xyz",
  "status": "success"
}
```

**State Transition:** READY → ACTIVE

**Timeout:** 10 seconds

---

## Movement Commands

### Twist Command (Linear + Angular Velocity)

**App → Robot: move_cmd**
```json
{
  "type": "move",
  "linear": {
    "x": 0.3,
    "y": 0.0,
    "z": 0.0
  },
  "angular": {
    "x": 0.0,
    "y": 0.0,
    "z": 0.5
  }
}
```

**Robot Implementation:**
```python
# Publish to ROS2 /cmd_vel topic
linear_x = float(linear['x'])  # -0.5 to +0.5 m/s
angular_z = float(angular['z'])  # -2.0 to +2.0 rad/s

# Velocity limits enforced
linear_x = max(-0.5, min(0.5, linear_x))
angular_z = max(-2.0, min(2.0, angular_z))
```

---

### Stop Command

**App → Robot: stop_cmd**
```json
{
  "type": "stop"
}
```

**Effect:** Immediately stop movement (zero velocities)

---

### Navigate to Pose (Nav2)

**App → Robot: navigate_to_pose_cmd**
```json
{
  "cmd_id": "cmd_nav_001",
  "target_pose": {
    "x": 2.5,
    "y": 1.5,
    "qw": 1.0,
    "qx": 0.0,
    "qy": 0.0,
    "qz": 0.0
  },
  "relative": false,
  "timeout_sec": 60
}
```

**Robot Implementation:**
```python
# Call Nav2 navigate_to_pose action
action_goal = NavigateToPose.Goal()
action_goal.pose.pose.position.x = 2.5
action_goal.pose.pose.position.y = 1.5

# Wait for result with timeout
result = await client.send_goal_async(action_goal)
```

**Robot → App: navigation_feedback**
```json
{
  "type": "navigation_feedback",
  "action_id": "cmd_nav_001",
  "status": "EXECUTING",
  "distance_remaining": 1.2,
  "estimated_time_remaining_sec": 4
}
```

---

## Sensor Data Streaming

### LaserScan (2 Hz)

**Robot → App: laser_scan**
```json
{
  "type": "laser_scan",
  "ranges": [0.5, 0.51, 0.52, ...],  // 360 floats
  "angle_min": -3.14159,
  "angle_max": 3.14159,
  "angle_increment": 0.01745,
  "range_min": 0.15,
  "range_max": 5.0,
  "header": {
    "seq": 123,
    "frame_id": "laser"
  }
}
```

**Frequency:** 2 Hz (emit every 500ms)
**Size:** ~50 KB (base64 encoded)

---

### Battery State (0.5 Hz)

**Robot → App: battery_data**
```json
{
  "type": "battery",
  "voltage": 14.8,
  "current": -2.5,
  "charge": 4.25,
  "capacity": 5.0,
  "percentage": 85.0,
  "status": "discharging"
}
```

**Frequency:** 0.5 Hz (emit every 2000ms)
**Size:** ~200 bytes

---

### Robot Pose (2 Hz)

**Robot → App: pose_data**
```json
{
  "type": "pose",
  "x": 1.5,
  "y": 2.3,
  "z": 0.0,
  "qw": 0.707,
  "qx": 0.0,
  "qy": 0.0,
  "qz": 0.707,
  "timestamp": "2025-01-07T12:00:00.123Z"
}
```

**Frequency:** 2 Hz (emit every 500ms)
**Size:** ~150 bytes

---

### Occupancy Grid Map (0.2 Hz)

**Robot → App: map_data**
```json
{
  "type": "map",
  "info": {
    "width": 384,
    "height": 384,
    "resolution": 0.05,
    "origin": {
      "x": 0.0,
      "y": 0.0,
      "theta": 0.0
    }
  },
  "data": [-1, 0, 100, ...]  // 384×384 values
}
```

**Frequency:** 0.2 Hz (emit every 5000ms)
**Size:** ~150-300 KB
**Values:** -1 (unknown), 0 (free), 100 (occupied)

---

### Camera Frame (5 Hz max)

**Robot → App: camera_data**
```json
{
  "type": "camera",
  "encoding": "jpeg",
  "width": 320,
  "height": 240,
  "data": "base64_encoded_jpeg_data...",
  "quality": 80,
  "timestamp": "2025-01-07T12:00:00.200Z"
}
```

**Frequency:** 5 Hz (emit every 200ms)
**Size:** ~30-50 KB (JPEG compressed)

---

## Rate Limiting & Deduplication

### Buffer Strategy
```python
class SensorStreamBuffer:
    def __init__(self, max_frequency_hz):
        self.min_interval_ms = 1000.0 / max_frequency_hz
        self.last_emit_time_ms = 0
        self.last_data = None

    def should_emit(self) -> bool:
        elapsed = time.time() * 1000 - self.last_emit_time_ms
        return elapsed >= self.min_interval_ms

    def add(self, data) -> bool:
        if data == self.last_data:
            return False  # Skip duplicate
        return True  # Accept new data
```

### Benefits
- Prevents network flooding
- Reduces bandwidth usage
- Skips unchanged data
- Improves app responsiveness

---

## Error Handling

### Error Response Format
```json
{
  "status": "failed",
  "error": "error_code",
  "error_message": "Human readable description"
}
```

### Common Error Codes
- `session_not_found` - Session doesn't exist
- `session_conflict` - Another session active
- `invalid_state` - Wrong state for operation
- `timeout` - Operation took too long
- `authentication_failed` - Auth rejected
- `insufficient_quota` - Asset quota exceeded

### Error Recovery
- Automatic reconnection with backoff
- Session state rollback on failure
- Resource cleanup
- User notification via CLI

---

## Token Management

| Token Type | Lifetime | Usage |
|-----------|----------|-------|
| Auth Token | 1 hour | API authentication |
| Session Token | 1 hour | App session identification |
| Connection Ticket | 5 minutes | One-time app connection |
| Refresh Token | 30 days | Get new auth token |

---

## Security Measures

### HMAC-SHA256 Authentication
- Robot secret never transmitted
- Server computes same signature
- Timing-safe comparison (`hmac.compare_digest`)

### Session Isolation
- One app session at a time
- Separate credentials per robot
- App cannot access other app files

### Path Traversal Prevention
```python
def sanitize_path(filename: str) -> str:
    # Remove path separators and traverse attempts
    sanitized = filename.replace('\\', '/').replace('..', '')
    sanitized = sanitized.lstrip('/')
    return sanitized
```

### Rate Limiting
- 5 auth attempts per minute
- 20 app launches per 5 minutes
- 100 general API calls per 15 minutes
