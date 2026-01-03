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
ROS2 Bridge Module for Remake CLI
================================
Handles ROS2 communication when --ros2 flag is used with remake connect.

This module:
- Publishes twist commands to /cmd_vel
- Subscribes to /odom for robot pose
- Sends pose/battery data back via callback
"""

import threading
from typing import Optional, Callable
import math

# ROS2 imports - gracefully handle if not installed
ROS2_AVAILABLE = False
try:
    import rclpy
    from rclpy.node import Node
    from geometry_msgs.msg import Twist
    from nav_msgs.msg import Odometry
    from sensor_msgs.msg import BatteryState
    ROS2_AVAILABLE = True
except ImportError:
    pass


class ROS2Bridge:
    """
    ROS2 Bridge that publishes /cmd_vel and subscribes to /odom
    """

    def __init__(
        self,
        on_pose: Optional[Callable] = None,
        on_battery: Optional[Callable] = None
    ):
        self.on_pose = on_pose
        self.on_battery = on_battery
        self._node = None
        self._spin_thread = None
        self._running = False

    def start(self):
        """Start the ROS2 bridge node"""
        if not ROS2_AVAILABLE:
            print("[ROS2] ROS2 not installed. Install rclpy to enable ROS2 bridge.")
            return False

        try:
            rclpy.init()
            self._node = _BridgeNode(
                on_pose=self.on_pose,
                on_battery=self.on_battery
            )
            self._running = True

            # Spin in background thread
            self._spin_thread = threading.Thread(
                target=self._spin_loop,
                daemon=True
            )
            self._spin_thread.start()

            print("[ROS2] Bridge started")
            print("[ROS2] Publishing to /cmd_vel")
            print("[ROS2] Subscribing to /odom")
            return True

        except Exception as e:
            print(f"[ROS2] Failed to start: {e}")
            return False

    def _spin_loop(self):
        """ROS2 spin loop in background thread"""
        while self._running and rclpy.ok():
            rclpy.spin_once(self._node, timeout_sec=0.1)

    def stop(self):
        """Stop the ROS2 bridge"""
        self._running = False
        if self._node:
            self._node.destroy_node()
        if ROS2_AVAILABLE:
            try:
                rclpy.shutdown()
            except:
                pass
        print("[ROS2] Bridge stopped")

    def publish_cmd_vel(self, linear_x: float, angular_z: float):
        """Publish velocity command to /cmd_vel"""
        if self._node:
            self._node.publish_cmd_vel(linear_x, angular_z)


if ROS2_AVAILABLE:
    class _BridgeNode(Node):
        """Internal ROS2 node for the bridge"""

        def __init__(self, on_pose=None, on_battery=None):
            super().__init__('remake_bridge')
            self.on_pose = on_pose
            self.on_battery = on_battery

            # Publisher for velocity commands
            self.cmd_vel_pub = self.create_publisher(Twist, '/cmd_vel', 10)

            # Subscriber for odometry
            self.odom_sub = self.create_subscription(
                Odometry, '/odom', self._odom_callback, 10
            )

            # Optional: battery state
            self.battery_sub = self.create_subscription(
                BatteryState, '/battery_state', self._battery_callback, 10
            )

            # Rate limiting
            self.last_odom_time = 0
            self.odom_rate = 0.1  # 10 Hz

        def publish_cmd_vel(self, linear_x: float, angular_z: float):
            """Publish Twist message to /cmd_vel"""
            twist = Twist()
            twist.linear.x = float(linear_x)
            twist.angular.z = float(angular_z)
            self.cmd_vel_pub.publish(twist)

        def _odom_callback(self, msg: Odometry):
            """Handle odometry messages"""
            # Rate limit
            now = self.get_clock().now().nanoseconds / 1e9
            if now - self.last_odom_time < self.odom_rate:
                return
            self.last_odom_time = now

            if not self.on_pose:
                return

            # Extract position
            x = msg.pose.pose.position.x
            y = msg.pose.pose.position.y

            # Quaternion to yaw
            q = msg.pose.pose.orientation
            siny_cosp = 2.0 * (q.w * q.z + q.x * q.y)
            cosy_cosp = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
            yaw = math.degrees(math.atan2(siny_cosp, cosy_cosp))

            self.on_pose({
                'x': round(x, 3),
                'y': round(y, 3),
                'yaw': round(yaw, 1)
            })

        def _battery_callback(self, msg: BatteryState):
            """Handle battery state messages"""
            if not self.on_battery:
                return

            self.on_battery({
                'level': int(msg.percentage * 100) if msg.percentage <= 1.0 else int(msg.percentage),
                'charging': msg.power_supply_status == BatteryState.POWER_SUPPLY_STATUS_CHARGING
            })
else:
    # Dummy class when ROS2 not available
    class _BridgeNode:
        pass


def is_ros2_available() -> bool:
    """Check if ROS2 is available"""
    return ROS2_AVAILABLE
