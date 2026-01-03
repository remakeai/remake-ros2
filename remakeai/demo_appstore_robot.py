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
Demo Robot for Remake AI Appstore Integration
Shows how to connect a Remake AI robot to the Remake AI Appstore
"""
import asyncio
import signal
import sys
import rclpy
from appstore_robot_client import AppstoreRobotClient

# ============================================
# CONFIGURATION - GET THESE FROM APPSTORE
# ============================================
# When you create a robot in the appstore, you get:
# 1. ROBOT_ID - UUID of your robot
# 2. ROBOT_SECRET - Secret token (shown only once!)
# ============================================

ROBOT_ID = "YOUR_ROBOT_ID_FROM_APPSTORE"
ROBOT_SECRET = "YOUR_ROBOT_SECRET_FROM_APPSTORE"
APPSTORE_URL = "http://localhost:5000"  # Change to https://apps.remake.ai for production

# Robot specification configuration
ROBOT_SPECIFICATION = {
    "api_version": 0,
    "model_name": "Remake AI Robot",
    "manufacturer": "Remake AI",
    "firmware_version": "1.0.0",
    "hardware_version": "v1.0",
    "sensors": [
        "lidar_2d",
        "cliff_sensors",
        "bump_sensors",
        "imu",
        "wheel_encoders",
        "camera_rgb",
        "wifi"
    ],
    "capabilities": [
        "mapping",
        "navigation",
        "remote_control"
    ],
    "battery_capacity_mah": 5200,
    "max_speed_ms": 0.35,
    "shape": {
        "type": "circular",
        "diameter_m": 0.35
    },
    "height_m": 0.092,
    "lidar_sensor": {
        "position": {
            "x_m": 0.0,
            "y_m": 0.0,
            "z_m": 0.082
        },
        "orientation": {
            "roll_deg": 0.0,
            "pitch_deg": 0.0,
            "yaw_deg": 0.0
        },
        "min_range_m": 0.12,
        "max_range_m": 8.0
    },
    "drive_type": "differential",
    "wheel_track_distance_m": 0.235,
    "docking_capability": True,
    "max_angular_speed_rad_s": 2.0,
    "weight_kg": 3.2
}


async def spin(robot, should_exit_func):
    """Run ROS2 spinning asynchronously"""
    try:
        while rclpy.ok() and not should_exit_func():
            rclpy.spin_once(robot, timeout_sec=0.01)
            await asyncio.sleep(0.001)
    except asyncio.CancelledError:
        pass


async def main():
    """Main function to run the robot controller"""
    print("=" * 60)
    print("🤖 Remake AI Robot → Remake AI Appstore Connector")
    print("=" * 60)
    print()
    print("📋 Configuration:")
    print(f"   • Robot ID: {ROBOT_ID}")
    print(f"   • Appstore URL: {APPSTORE_URL}")
    print()
    print("🔄 This robot will:")
    print("   • Authenticate with the Remake AI Appstore")
    print("   • Send real-time sensor data (LiDAR, battery, wifi, pose)")
    print("   • Receive and execute app launch commands")
    print("   • Maintain heartbeat connection")
    print("=" * 60)
    print()

    # Validate configuration
    if ROBOT_ID == "YOUR_ROBOT_ID_FROM_APPSTORE" or ROBOT_SECRET == "YOUR_ROBOT_SECRET_FROM_APPSTORE":
        print("❌ ERROR: Please configure ROBOT_ID and ROBOT_SECRET")
        print()
        print("📝 How to get your robot credentials:")
        print("   1. Go to Remake AI Appstore: http://localhost:3000")
        print("   2. Navigate to 'Robots' page")
        print("   3. Click 'Add Robot'")
        print("   4. Enter a name and click 'Create'")
        print("   5. Copy the Robot ID and Secret Token")
        print("   6. Paste them into this file (lines 13-14)")
        print()
        sys.exit(1)

    # Initialize ROS2
    rclpy.init()

    robot = None
    should_exit = False

    try:
        # Create appstore robot client
        robot = AppstoreRobotClient(
            robot_id=ROBOT_ID,
            robot_secret=ROBOT_SECRET,
            specification=ROBOT_SPECIFICATION,
            appstore_url=APPSTORE_URL
        )

        # Set up signal handlers for graceful shutdown
        def signal_handler(signum, frame):
            nonlocal should_exit
            print(f"\n🛑 Received signal {signum} - shutting down...")
            should_exit = True
            if robot:
                robot.cleanup_and_exit()

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        print("🚀 Starting robot client...")
        print("   Press Ctrl+C to stop")
        print()

        # Run both ROS2 spinning and appstore connection concurrently
        await asyncio.gather(
            spin(robot, lambda: should_exit),
            robot.connect_to_appstore()
        )

    except KeyboardInterrupt:
        print("\n🛑 Robot controller stopped by user")
        if robot:
            robot.cleanup_and_exit()
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Cleanup ROS2
        try:
            if robot:
                robot.destroy_node()
        except:
            pass
        try:
            if rclpy.ok():
                rclpy.shutdown()
        except:
            pass


if __name__ == "__main__":
    print("\n" + "="*60)
    print("🤖 Starting Remake AI Robot with Remake AI Appstore")
    print("="*60 + "\n")

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Program interrupted")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\n" + "="*60)
        print("👋 Robot controller terminated")
        print("="*60 + "\n")
