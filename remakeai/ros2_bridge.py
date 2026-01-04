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
ROS2 Bridge Module for Remake CLI.

Handles ROS2 communication when --ros2 flag is used with `remake connect`.

This module:
- Publishes twist commands to /cmd_vel
- Subscribes to /odom for robot pose
- Subscribes to /battery_state for battery level
- Subscribes to /scan for LIDAR data (future)
- Sends sensor data back via callbacks
"""

import time
import threading
from typing import Optional, Callable, Dict, Any, List
import math

# ROS2 imports - gracefully handle if not installed
ROS2_AVAILABLE = False
try:
    import rclpy
    from rclpy.node import Node
    from geometry_msgs.msg import Twist
    from nav_msgs.msg import Odometry
    from sensor_msgs.msg import BatteryState, LaserScan
    ROS2_AVAILABLE = True
except ImportError:
    pass


class ROS2Bridge:
    """
    ROS2 Bridge that publishes /cmd_vel and subscribes to sensor topics.

    Provides callbacks for:
    - pose_data: Robot position (x, y, theta)
    - battery_data: Battery level and charging status
    - scan_data: LIDAR scan (future)
    """

    def __init__(
        self,
        on_pose: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_battery: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_scan: Optional[Callable[[Dict[str, Any]], None]] = None
    ):
        self.on_pose = on_pose
        self.on_battery = on_battery
        self.on_scan = on_scan
        self._node = None
        self._spin_thread = None
        self._running = False

    def start(self) -> bool:
        """Start the ROS2 bridge node."""
        if not ROS2_AVAILABLE:
            print("[ROS2] ROS2 not installed. Install rclpy to enable ROS2 bridge.")
            return False

        try:
            rclpy.init()
            self._node = _BridgeNode(
                on_pose=self.on_pose,
                on_battery=self.on_battery,
                on_scan=self.on_scan
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
            print("[ROS2] Subscribing to /odom, /battery_state")
            return True

        except Exception as e:
            print(f"[ROS2] Failed to start: {e}")
            return False

    def _spin_loop(self):
        """ROS2 spin loop in background thread."""
        while self._running and rclpy.ok():
            rclpy.spin_once(self._node, timeout_sec=0.1)

    def stop(self):
        """Stop the ROS2 bridge."""
        self._running = False
        if self._node:
            self._node.destroy_node()
        if ROS2_AVAILABLE:
            try:
                rclpy.shutdown()
            except Exception:
                pass
        print("[ROS2] Bridge stopped")

    def publish_cmd_vel(self, linear_x: float, angular_z: float):
        """Publish velocity command to /cmd_vel."""
        if self._node:
            self._node.publish_cmd_vel(linear_x, angular_z)

    def get_available_topics(self) -> List[str]:
        """Get list of available ROS2 topics (for diagnostics)."""
        if self._node:
            return self._node.get_available_topics()
        return []

    def is_topic_publishing(self, topic: str) -> bool:
        """Check if a topic is actively publishing (for diagnostics)."""
        if self._node:
            return self._node.is_topic_publishing(topic)
        return False


if ROS2_AVAILABLE:
    class _BridgeNode(Node):
        """Internal ROS2 node for the bridge."""

        def __init__(self, on_pose=None, on_battery=None, on_scan=None):
            super().__init__('remakeai_bridge')
            self.on_pose = on_pose
            self.on_battery = on_battery
            self.on_scan = on_scan

            # Publisher for velocity commands
            self.cmd_vel_pub = self.create_publisher(Twist, '/cmd_vel', 10)

            # Subscriber for odometry
            self.odom_sub = self.create_subscription(
                Odometry, '/odom', self._odom_callback, 10
            )

            # Subscriber for battery state
            self.battery_sub = self.create_subscription(
                BatteryState, '/battery_state', self._battery_callback, 10
            )

            # Subscriber for laser scan (optional)
            self.scan_sub = self.create_subscription(
                LaserScan, '/scan', self._scan_callback, 10
            )

            # Rate limiting
            self.last_odom_time = 0
            self.odom_rate = 0.1  # 10 Hz max

            self.last_battery_time = 0
            self.battery_rate = 10.0  # 0.1 Hz max (every 10 seconds)

            self.last_scan_time = 0
            self.scan_rate = 0.1  # 10 Hz max

            # Topic activity tracking (for diagnostics)
            self._topic_last_msg: Dict[str, float] = {}

        def publish_cmd_vel(self, linear_x: float, angular_z: float):
            """Publish Twist message to /cmd_vel."""
            twist = Twist()
            twist.linear.x = float(linear_x)
            twist.angular.z = float(angular_z)
            self.cmd_vel_pub.publish(twist)

        def _odom_callback(self, msg: Odometry):
            """Handle odometry messages."""
            now = self.get_clock().now().nanoseconds / 1e9
            self._topic_last_msg['/odom'] = now

            # Rate limit
            if now - self.last_odom_time < self.odom_rate:
                return
            self.last_odom_time = now

            if not self.on_pose:
                return

            # Extract position
            x = msg.pose.pose.position.x
            y = msg.pose.pose.position.y

            # Quaternion to theta (radians)
            q = msg.pose.pose.orientation
            siny_cosp = 2.0 * (q.w * q.z + q.x * q.y)
            cosy_cosp = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
            theta = math.atan2(siny_cosp, cosy_cosp)

            self.on_pose({
                'x': round(x, 3),
                'y': round(y, 3),
                'theta': round(theta, 4),
                'timestamp': int(time.time() * 1000)
            })

        def _battery_callback(self, msg: BatteryState):
            """Handle battery state messages."""
            now = self.get_clock().now().nanoseconds / 1e9
            self._topic_last_msg['/battery_state'] = now

            # Rate limit
            if now - self.last_battery_time < self.battery_rate:
                return
            self.last_battery_time = now

            if not self.on_battery:
                return

            # Handle percentage (can be 0-1 or 0-100 depending on driver)
            percentage = msg.percentage
            if percentage <= 1.0:
                level = int(percentage * 100)
            else:
                level = int(percentage)

            self.on_battery({
                'level': level,
                'charging': msg.power_supply_status == BatteryState.POWER_SUPPLY_STATUS_CHARGING,
                'timestamp': int(time.time() * 1000)
            })

        def _scan_callback(self, msg: LaserScan):
            """Handle laser scan messages."""
            now = self.get_clock().now().nanoseconds / 1e9
            self._topic_last_msg['/scan'] = now

            # Rate limit
            if now - self.last_scan_time < self.scan_rate:
                return
            self.last_scan_time = now

            if not self.on_scan:
                return

            # Convert ranges to list, replacing inf with max_range
            ranges = []
            for r in msg.ranges:
                if math.isinf(r) or math.isnan(r):
                    ranges.append(msg.range_max)
                else:
                    ranges.append(round(r, 3))

            self.on_scan({
                'angle_min': msg.angle_min,
                'angle_max': msg.angle_max,
                'angle_increment': msg.angle_increment,
                'range_min': msg.range_min,
                'range_max': msg.range_max,
                'ranges': ranges,
                'timestamp': int(time.time() * 1000)
            })

        def get_available_topics(self) -> List[str]:
            """Get list of available ROS2 topics."""
            topic_list = self.get_topic_names_and_types()
            return [name for name, _ in topic_list]

        def is_topic_publishing(self, topic: str) -> bool:
            """Check if a topic has published recently (within 5 seconds)."""
            last_msg = self._topic_last_msg.get(topic)
            if last_msg is None:
                return False
            now = self.get_clock().now().nanoseconds / 1e9
            return (now - last_msg) < 5.0

else:
    # Dummy class when ROS2 not available
    class _BridgeNode:
        pass


def is_ros2_available() -> bool:
    """Check if ROS2 is available."""
    return ROS2_AVAILABLE
