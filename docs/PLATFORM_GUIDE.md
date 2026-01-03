# Kaia.ai Platform Integration Guide

## Overview

This guide explains how to connect your **Kaia.ai ROS2 robot** to the **Remake.ai platform**, enabling:

- Secure robot authentication using secret tokens
- Real-time robot status tracking (online/offline)
- Sensor data streaming (LiDAR, battery, WiFi, pose, camera)
- Remote app launching and control
- Automatic reconnection with heartbeat

## Prerequisites

- ROS2 Jazzy (or compatible)
- Python 3.8+
- Kaia.ai packages installed

## Quick Start

### Step 1: Register Your Robot

1. Open the platform web interface
2. Navigate to **Robots** page
3. Click **"Add Robot"**
4. Enter robot name (e.g., "My Kaia Robot")
5. Click **"Create Robot"**
6. **Important**: Copy the displayed credentials:
   - **Robot ID** (UUID like `a1b2c3d4-e5f6-...`)

### Step 2: Configure Robot

Create a configuration file or set environment variables:

```bash
export KAIAAI_ROBOT_ID="a1b2c3d4-e5f6-7890-abcd-1234567890ab"
export KAIAAI_ROBOT_SECRET="12345678-90ab-cdef-1234-567890abcdef"
export KAIAAI_PLATFORM_URL="https://apps.remake.ai"
```

Or configure in Python:

```python
import os

ROBOT_ID = os.environ.get('KAIAAI_ROBOT_ID')
ROBOT_SECRET = os.environ.get('KAIAAI_ROBOT_SECRET')
PLATFORM_URL = os.environ.get('KAIAAI_PLATFORM_URL', 'https://apps.remake.ai')
```

### Step 3: Launch Robot

```bash
# In ROS2 workspace
cd ~/ros_ws/src/kaiaai/kaiaai
python3 demo_appstore_robot.py
```

### Step 4: Verify Connection

You should see in the terminal:
```
Connected to platform - authenticating...
Authentication successful
Sending ping to platform
```

On the platform UI, your robot status should show **"Online"**.

## Security Best Practices

### Secret Token Storage

**Never commit your `ROBOT_SECRET` to version control!**

Recommended approaches:

1. **Environment variables** (recommended):
   ```bash
   export ROBOT_SECRET="your-secret-here"
   ```

2. **Load from environment in code**:
   ```python
   import os
   ROBOT_SECRET = os.environ.get('ROBOT_SECRET')
   ```

3. **ROS2 parameters**:
   ```bash
   ros2 run kaiaai demo_appstore_robot --ros-args \
     -p robot_id:=... -p robot_secret:=...
   ```

### Production Deployment

For production, always use HTTPS/WSS:

```python
PLATFORM_URL = "https://apps.remake.ai"
```

## Example: Complete Robot Setup

```python
#!/usr/bin/env python3
import os
import asyncio
import rclpy
from appstore_robot_client import AppstoreRobotClient

# Load from environment variables (recommended)
ROBOT_ID = os.environ['KAIAAI_ROBOT_ID']
ROBOT_SECRET = os.environ['KAIAAI_ROBOT_SECRET']
PLATFORM_URL = os.environ.get('KAIAAI_PLATFORM_URL', 'https://apps.remake.ai')

ROBOT_SPEC = {
    "model_name": "Kaia.ai Loki",
    "manufacturer": "Maker's Pet",
    # ... rest of specification
}

async def main():
    rclpy.init()

    robot = AppstoreRobotClient(
        robot_id=ROBOT_ID,
        robot_secret=ROBOT_SECRET,
        specification=ROBOT_SPEC,
        appstore_url=PLATFORM_URL
    )

    try:
        await robot.connect_to_appstore()
    finally:
        robot.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    asyncio.run(main())
```

## Sensor Data Streaming

Once connected, your robot can stream the following data:

| Data Type | Description |
|-----------|-------------|
| `laser_scan` | LiDAR data |
| `battery` | Battery level, voltage, temperature |
| `wifi` | WiFi RSSI signal strength |
| `robot_pose` | Robot position (x, y, yaw) |
| `map` | Occupancy grid map |
| `camera` | JPEG-encoded images |
| `navigation_feedback` | Navigation progress |
| `navigation_status` | Navigation state changes |

## Robot Status

| Status | Meaning |
|--------|---------|
| Online | Robot is connected and sending heartbeat |
| Offline | Robot is not connected |

## Troubleshooting

### Robot Can't Connect

1. **Check network connectivity**: Ensure your robot can reach the platform URL
2. **Verify credentials**: Double-check your Robot ID and Secret Token
3. **Check firewall**: Ensure outbound HTTPS/WSS connections are allowed

### Authentication Fails

1. Verify that the Robot ID and Secret Token match exactly what was shown during registration

### Robot Shows Offline

1. Check that the robot process is running
2. Verify network connectivity
3. Check for error messages in the robot terminal

## Support

- **Issues**: https://github.com/kaiaai/kaiaai/issues
- **Community**: https://github.com/makerspet/support/discussions