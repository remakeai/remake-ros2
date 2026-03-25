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
ROS2 Bridge Module for Remake AI Platform.

Bridges ROS2 topics/actions with App API messages.
Converts between ROS2 message formats and platform JSON schemas.

Spec: robot/API_SENSOR_DATA.md, robot/app/ROBOT_APP_API_REMOTE_CONTROL.md
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import math
import struct
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import numpy as np

# ROS2 imports - gracefully handle if not installed
ROS2_AVAILABLE = False
try:
    import rclpy
    from rclpy.node import Node
    from rclpy.action import ActionClient
    from rclpy.action.client import ClientGoalHandle
    from rclpy.qos import QoSProfile, QoSDurabilityPolicy, QoSReliabilityPolicy
    from rclpy.callback_groups import ReentrantCallbackGroup
    from geometry_msgs.msg import Twist, PoseStamped
    from nav_msgs.msg import Odometry, OccupancyGrid
    from sensor_msgs.msg import BatteryState, LaserScan, Image, Imu
    from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus
    from nav2_msgs.action import NavigateToPose
    from tf2_ros import TransformException
    from tf2_ros.buffer import Buffer
    from tf2_ros.transform_listener import TransformListener
    ROS2_AVAILABLE = True
except ImportError:
    pass

# Optional: PIL/Pillow for JPEG compression
PIL_AVAILABLE = False
try:
    from PIL import Image as PILImage
    PIL_AVAILABLE = True
except ImportError:
    pass

# Optional: OpenCV for image processing
CV2_AVAILABLE = False
try:
    import cv2
    from cv_bridge import CvBridge
    CV2_AVAILABLE = True
except ImportError:
    pass


logger = logging.getLogger(__name__)


# =============================================================================
# Configuration Classes
# =============================================================================

@dataclass
class SensorConfig:
    """Configuration for a sensor subscription."""
    topic: str
    msg_type: str
    event_name: str
    rate_hz: float = 10.0
    enabled: bool = True


@dataclass
class BridgeConfig:
    """Configuration for the ROS2 Bridge."""
    # Sensor publish rates (Hz)
    battery_rate_hz: float = 0.5      # 0.5 Hz = every 2 seconds
    pose_rate_hz: float = 10.0        # 10 Hz
    scan_rate_hz: float = 10.0        # 10 Hz
    camera_rate_hz: float = 5.0       # 5 Hz
    imu_rate_hz: float = 10.0         # 10 Hz
    health_rate_hz: float = 1.0       # 1 Hz
    map_rate_hz: float = 0.2          # Only on change, 0.2 Hz max

    # Camera settings
    camera_jpeg_quality: int = 85
    camera_max_width: int = 640
    camera_max_height: int = 480

    # Movement limits (safety)
    max_linear_velocity: float = 1.0   # m/s
    max_angular_velocity: float = 2.0  # rad/s

    # Navigation settings
    nav_action_name: str = '/navigate_to_pose'
    nav_feedback_rate_hz: float = 2.0  # Navigation progress updates

    # Frame IDs
    global_frame_id: str = 'map'
    base_frame_id: str = 'base_footprint'

    # Delta movement tolerance
    delta_position_tolerance: float = 0.05   # 5 cm
    delta_rotation_tolerance: float = 0.05   # ~3 degrees


class NavigationState(Enum):
    """Navigation state machine."""
    IDLE = "idle"
    NAVIGATING = "navigating"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StoppedReason(Enum):
    """Reason why the robot stopped moving."""
    COMMAND = "command"
    DELTA_REACHED = "delta_reached"
    OBSTACLE = "obstacle"
    ERROR = "error"


# =============================================================================
# Rate Limiter
# =============================================================================

class RateLimiter:
    """Thread-safe rate limiter for sensor data emission."""

    def __init__(self, rate_hz: float):
        self.min_interval = 1.0 / rate_hz if rate_hz > 0 else float('inf')
        self.last_time = 0.0
        self._lock = threading.Lock()

    def should_emit(self) -> bool:
        """Check if enough time has passed to emit data."""
        with self._lock:
            now = time.time()
            if now - self.last_time >= self.min_interval:
                self.last_time = now
                return True
            return False

    def reset(self):
        """Reset the rate limiter."""
        with self._lock:
            self.last_time = 0.0


# =============================================================================
# Movement Tracker for Delta Support
# =============================================================================

@dataclass
class MovementTarget:
    """Target for delta-based movement."""
    cmd_id: Optional[str] = None
    linear_velocity: float = 0.0
    angular_velocity: float = 0.0
    linear_delta: Optional[float] = None   # meters to travel
    angular_delta: Optional[float] = None  # radians to rotate
    obstacle_policy: str = "stop_before_contact"

    # Tracking state
    start_x: float = 0.0
    start_y: float = 0.0
    start_theta: float = 0.0
    accumulated_distance: float = 0.0
    accumulated_rotation: float = 0.0
    active: bool = False


class MovementTracker:
    """
    Tracks odometry deltas for move_cmd with delta support.

    When move_cmd includes linear.delta or angular.delta, this tracker:
    1. Records starting position/orientation
    2. Monitors odometry updates
    3. Stops robot when delta is reached
    4. Sends move_response with stopped_reason: 'delta_reached'
    """

    def __init__(
        self,
        on_delta_reached: Optional[Callable[[str, StoppedReason], None]] = None,
        position_tolerance: float = 0.05,
        rotation_tolerance: float = 0.05
    ):
        self.on_delta_reached = on_delta_reached
        self.position_tolerance = position_tolerance
        self.rotation_tolerance = rotation_tolerance

        self._target: Optional[MovementTarget] = None
        self._lock = threading.Lock()

        # Previous odometry for incremental tracking
        self._prev_x: Optional[float] = None
        self._prev_y: Optional[float] = None
        self._prev_theta: Optional[float] = None

    def start_tracking(
        self,
        cmd_id: Optional[str],
        linear_velocity: float,
        angular_velocity: float,
        linear_delta: Optional[float],
        angular_delta: Optional[float],
        obstacle_policy: str,
        current_x: float,
        current_y: float,
        current_theta: float
    ) -> MovementTarget:
        """Start tracking a new movement command with delta."""
        with self._lock:
            self._target = MovementTarget(
                cmd_id=cmd_id,
                linear_velocity=linear_velocity,
                angular_velocity=angular_velocity,
                linear_delta=linear_delta,
                angular_delta=angular_delta,
                obstacle_policy=obstacle_policy,
                start_x=current_x,
                start_y=current_y,
                start_theta=current_theta,
                accumulated_distance=0.0,
                accumulated_rotation=0.0,
                active=True
            )
            self._prev_x = current_x
            self._prev_y = current_y
            self._prev_theta = current_theta
            return self._target

    def stop_tracking(self) -> Optional[MovementTarget]:
        """Stop tracking and return the target."""
        with self._lock:
            target = self._target
            if target:
                target.active = False
            self._target = None
            self._prev_x = None
            self._prev_y = None
            self._prev_theta = None
            return target

    def update_odometry(self, x: float, y: float, theta: float) -> Optional[StoppedReason]:
        """
        Update with new odometry and check if delta is reached.

        Returns StoppedReason if delta was reached, None otherwise.
        """
        with self._lock:
            if not self._target or not self._target.active:
                return None

            # Calculate incremental movement
            if self._prev_x is not None:
                dx = x - self._prev_x
                dy = y - self._prev_y
                incremental_distance = math.sqrt(dx * dx + dy * dy)
                self._target.accumulated_distance += incremental_distance

                # Calculate angular change (handle wraparound)
                dtheta = theta - self._prev_theta
                # Normalize to [-pi, pi]
                while dtheta > math.pi:
                    dtheta -= 2 * math.pi
                while dtheta < -math.pi:
                    dtheta += 2 * math.pi
                self._target.accumulated_rotation += abs(dtheta)

            self._prev_x = x
            self._prev_y = y
            self._prev_theta = theta

            # Check if delta reached
            delta_reached = False

            if self._target.linear_delta is not None:
                if self._target.accumulated_distance >= (
                    self._target.linear_delta - self.position_tolerance
                ):
                    delta_reached = True

            if self._target.angular_delta is not None:
                if self._target.accumulated_rotation >= (
                    abs(self._target.angular_delta) - self.rotation_tolerance
                ):
                    delta_reached = True

            if delta_reached:
                cmd_id = self._target.cmd_id
                self._target.active = False
                self._target = None
                return StoppedReason.DELTA_REACHED

            return None

    @property
    def is_tracking(self) -> bool:
        """Check if actively tracking a movement."""
        with self._lock:
            return self._target is not None and self._target.active

    @property
    def current_target(self) -> Optional[MovementTarget]:
        """Get current movement target."""
        with self._lock:
            return self._target


# =============================================================================
# Message Converters
# =============================================================================

def quaternion_to_euler(x: float, y: float, z: float, w: float) -> Tuple[float, float, float]:
    """Convert quaternion to euler angles (roll, pitch, yaw)."""
    # Roll (x-axis rotation)
    sinr_cosp = 2.0 * (w * x + y * z)
    cosr_cosp = 1.0 - 2.0 * (x * x + y * y)
    roll = math.atan2(sinr_cosp, cosr_cosp)

    # Pitch (y-axis rotation)
    sinp = 2.0 * (w * y - z * x)
    if abs(sinp) >= 1:
        pitch = math.copysign(math.pi / 2, sinp)
    else:
        pitch = math.asin(sinp)

    # Yaw (z-axis rotation)
    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    yaw = math.atan2(siny_cosp, cosy_cosp)

    return roll, pitch, yaw


def euler_to_quaternion(roll: float, pitch: float, yaw: float) -> Tuple[float, float, float, float]:
    """Convert euler angles to quaternion (x, y, z, w)."""
    cy = math.cos(yaw * 0.5)
    sy = math.sin(yaw * 0.5)
    cp = math.cos(pitch * 0.5)
    sp = math.sin(pitch * 0.5)
    cr = math.cos(roll * 0.5)
    sr = math.sin(roll * 0.5)

    w = cr * cp * cy + sr * sp * sy
    x = sr * cp * cy - cr * sp * sy
    y = cr * sp * cy + sr * cp * sy
    z = cr * cp * sy - sr * sp * cy

    return x, y, z, w


def timestamp_ms() -> int:
    """Get current timestamp in milliseconds."""
    return int(time.time() * 1000)


def compress_image_jpeg(
    image_data: bytes,
    width: int,
    height: int,
    encoding: str,
    quality: int = 85,
    max_width: int = 640,
    max_height: int = 480
) -> Tuple[bytes, int, int]:
    """
    Compress image to JPEG format.

    Returns (jpeg_bytes, output_width, output_height).
    """
    if CV2_AVAILABLE:
        # Use OpenCV for compression
        if encoding in ('bgr8', 'rgb8'):
            # Decode based on encoding
            if encoding == 'bgr8':
                img = np.frombuffer(image_data, dtype=np.uint8).reshape((height, width, 3))
            else:  # rgb8
                img = np.frombuffer(image_data, dtype=np.uint8).reshape((height, width, 3))
                img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

            # Resize if needed
            if width > max_width or height > max_height:
                scale = min(max_width / width, max_height / height)
                new_width = int(width * scale)
                new_height = int(height * scale)
                img = cv2.resize(img, (new_width, new_height))
                width, height = new_width, new_height

            # Encode to JPEG
            _, jpeg_buffer = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, quality])
            return jpeg_buffer.tobytes(), width, height

    if PIL_AVAILABLE:
        # Use PIL for compression
        if encoding in ('bgr8', 'rgb8'):
            mode = 'RGB'
            if encoding == 'bgr8':
                # Convert BGR to RGB
                img_array = np.frombuffer(image_data, dtype=np.uint8).reshape((height, width, 3))
                img_array = img_array[:, :, ::-1]  # BGR to RGB
                image_data = img_array.tobytes()

            img = PILImage.frombytes(mode, (width, height), image_data)

            # Resize if needed
            if width > max_width or height > max_height:
                img.thumbnail((max_width, max_height), PILImage.Resampling.LANCZOS)
                width, height = img.size

            # Encode to JPEG
            buffer = io.BytesIO()
            img.save(buffer, format='JPEG', quality=quality)
            return buffer.getvalue(), width, height

    # Fallback: return raw data (not ideal)
    logger.warning("No image compression library available. Returning raw image data.")
    return image_data, width, height


# =============================================================================
# ROS2 Bridge Class
# =============================================================================

class ROS2Bridge:
    """
    Bridges ROS2 topics/actions with App API messages.

    Converts between ROS2 message formats and platform JSON schemas.

    Required ROS2 Subscriptions:
    - /battery_state (sensor_msgs/BatteryState) -> battery_data event
    - /odom (nav_msgs/Odometry) -> pose_data event
    - /scan (sensor_msgs/LaserScan) -> scan_data event
    - /camera/image_raw (sensor_msgs/Image) -> camera_data event
    - /imu/data (sensor_msgs/Imu) -> imu_data event
    - /diagnostics (diagnostic_msgs/DiagnosticArray) -> health_data event
    - /map (nav_msgs/OccupancyGrid) -> map_data event

    Required ROS2 Publishers:
    - /cmd_vel (geometry_msgs/Twist) - for move_cmd from app

    Required ROS2 Action Clients:
    - /navigate_to_pose (nav2_msgs/NavigateToPose) - for navigate_cmd from app
    """

    def __init__(
        self,
        config: Optional[BridgeConfig] = None,
        on_battery_data: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_pose_data: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_scan_data: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_camera_data: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_imu_data: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_health_data: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_map_data: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_navigation_data: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_move_response: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        """
        Initialize the ROS2 Bridge.

        Args:
            config: Bridge configuration (uses defaults if None)
            on_battery_data: Callback for battery_data events
            on_pose_data: Callback for pose_data events
            on_scan_data: Callback for scan_data events
            on_camera_data: Callback for camera_data events
            on_imu_data: Callback for imu_data events
            on_health_data: Callback for health_data events
            on_map_data: Callback for map_data events
            on_navigation_data: Callback for navigation_data events
            on_move_response: Callback for move_response events
        """
        self.config = config or BridgeConfig()

        # Callbacks for emitting data to app
        self.on_battery_data = on_battery_data
        self.on_pose_data = on_pose_data
        self.on_scan_data = on_scan_data
        self.on_camera_data = on_camera_data
        self.on_imu_data = on_imu_data
        self.on_health_data = on_health_data
        self.on_map_data = on_map_data
        self.on_navigation_data = on_navigation_data
        self.on_move_response = on_move_response

        # Rate limiters
        self._battery_limiter = RateLimiter(self.config.battery_rate_hz)
        self._pose_limiter = RateLimiter(self.config.pose_rate_hz)
        self._scan_limiter = RateLimiter(self.config.scan_rate_hz)
        self._camera_limiter = RateLimiter(self.config.camera_rate_hz)
        self._imu_limiter = RateLimiter(self.config.imu_rate_hz)
        self._health_limiter = RateLimiter(self.config.health_rate_hz)
        self._map_limiter = RateLimiter(self.config.map_rate_hz)
        self._nav_feedback_limiter = RateLimiter(self.config.nav_feedback_rate_hz)

        # Movement tracker for delta support
        self._movement_tracker = MovementTracker(
            on_delta_reached=self._handle_delta_reached,
            position_tolerance=self.config.delta_position_tolerance,
            rotation_tolerance=self.config.delta_rotation_tolerance
        )

        # Current pose (for relative navigation and delta tracking)
        self._current_x: float = 0.0
        self._current_y: float = 0.0
        self._current_theta: float = 0.0
        self._pose_lock = threading.Lock()

        # Navigation state
        self._nav_state = NavigationState.IDLE
        self._nav_cmd_id: Optional[str] = None
        self._nav_goal_handle: Optional[ClientGoalHandle] = None
        self._nav_start_distance: float = 0.0
        self._nav_lock = threading.Lock()

        # Map change detection
        self._last_map_hash: Optional[int] = None

        # ROS2 node (created in start())
        self._node: Optional[_BridgeNode] = None
        self._spin_thread: Optional[threading.Thread] = None
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def start(self, node_name: str = 'remake_ros2_bridge') -> bool:
        """
        Start the ROS2 bridge.

        Args:
            node_name: Name for the ROS2 node

        Returns:
            True if started successfully, False otherwise
        """
        if not ROS2_AVAILABLE:
            logger.error("ROS2 not installed. Install rclpy to enable ROS2 bridge.")
            return False

        try:
            # Initialize ROS2 if not already
            if not rclpy.ok():
                rclpy.init()

            # Create the bridge node
            self._node = _BridgeNode(
                bridge=self,
                node_name=node_name,
                config=self.config
            )

            self._running = True

            # Create event loop for async operations
            self._loop = asyncio.new_event_loop()

            # Spin in background thread
            self._spin_thread = threading.Thread(
                target=self._spin_loop,
                daemon=True,
                name='ros2_bridge_spin'
            )
            self._spin_thread.start()

            logger.info("ROS2 Bridge started")
            logger.info(f"  Publishing to: /cmd_vel")
            logger.info(f"  Subscribing to: /battery_state, /odom, /scan, /camera/image_raw, /imu/data, /diagnostics, /map")
            logger.info(f"  Action client: {self.config.nav_action_name}")

            return True

        except Exception as e:
            logger.exception(f"Failed to start ROS2 bridge: {e}")
            return False

    def stop(self):
        """Stop the ROS2 bridge."""
        self._running = False

        # Cancel any active navigation
        if self._nav_goal_handle is not None:
            try:
                self._cancel_navigation_sync()
            except Exception as e:
                logger.warning(f"Error cancelling navigation during shutdown: {e}")

        # Stop movement tracking
        self._movement_tracker.stop_tracking()

        # Destroy node
        if self._node:
            try:
                self._node.destroy_node()
            except Exception:
                pass
            self._node = None

        # Shutdown ROS2
        if ROS2_AVAILABLE:
            try:
                rclpy.shutdown()
            except Exception:
                pass

        # Close event loop
        if self._loop:
            try:
                self._loop.close()
            except Exception:
                pass
            self._loop = None

        logger.info("ROS2 Bridge stopped")

    def _spin_loop(self):
        """ROS2 spin loop in background thread."""
        asyncio.set_event_loop(self._loop)
        while self._running and rclpy.ok():
            try:
                rclpy.spin_once(self._node, timeout_sec=0.1)
            except Exception as e:
                if self._running:
                    logger.error(f"Error in spin loop: {e}")

    # =========================================================================
    # Command Handlers (called from App)
    # =========================================================================

    def handle_move_cmd(self, data: Dict[str, Any]):
        """
        Handle move_cmd from app.

        Payload:
        {
            "cmd_id": "string (optional)",
            "linear": {"x": float, "delta": float (optional)},
            "angular": {"z": float, "delta": float (optional)},
            "obstacle_policy": "string (optional)"
        }
        """
        if not self._node:
            logger.error("ROS2 bridge not started")
            return

        cmd_id = data.get('cmd_id')
        linear = data.get('linear', {})
        angular = data.get('angular', {})
        obstacle_policy = data.get('obstacle_policy', 'stop_before_contact')

        linear_x = float(linear.get('x', 0.0))
        angular_z = float(angular.get('z', 0.0))
        linear_delta = linear.get('delta')
        angular_delta = angular.get('delta')

        # Apply velocity limits
        linear_x = max(-self.config.max_linear_velocity,
                       min(self.config.max_linear_velocity, linear_x))
        angular_z = max(-self.config.max_angular_velocity,
                        min(self.config.max_angular_velocity, angular_z))

        # Start delta tracking if deltas specified
        if linear_delta is not None or angular_delta is not None:
            with self._pose_lock:
                current_x = self._current_x
                current_y = self._current_y
                current_theta = self._current_theta

            self._movement_tracker.start_tracking(
                cmd_id=cmd_id,
                linear_velocity=linear_x,
                angular_velocity=angular_z,
                linear_delta=float(linear_delta) if linear_delta else None,
                angular_delta=float(angular_delta) if angular_delta else None,
                obstacle_policy=obstacle_policy,
                current_x=current_x,
                current_y=current_y,
                current_theta=current_theta
            )
            logger.info(f"Started delta tracking: linear_delta={linear_delta}, angular_delta={angular_delta}")

        # Publish velocity command
        self._node.publish_cmd_vel(linear_x, angular_z)
        logger.debug(f"Published cmd_vel: linear.x={linear_x:.3f}, angular.z={angular_z:.3f}")

    def handle_stop_cmd(self, data: Dict[str, Any] = None):
        """
        Handle stop_cmd from app.

        Immediately stops the robot and cancels any navigation.
        """
        if not self._node:
            logger.error("ROS2 bridge not started")
            return

        cmd_id = data.get('cmd_id') if data else None

        # Stop movement tracking
        target = self._movement_tracker.stop_tracking()
        if target and target.cmd_id:
            self._emit_move_response(target.cmd_id, StoppedReason.COMMAND)

        # Stop robot
        self._node.publish_cmd_vel(0.0, 0.0)
        logger.info("Robot stopped via stop_cmd")

        # Cancel navigation if active
        with self._nav_lock:
            if self._nav_state == NavigationState.NAVIGATING:
                self._cancel_navigation_async()

    def handle_navigate_cmd(self, data: Dict[str, Any]):
        """
        Handle navigate_cmd from app.

        Payload:
        {
            "cmd_id": "string (required)",
            "goal_x": float,
            "goal_y": float,
            "goal_theta": float (optional),
            "reference_frame": "map" | "robot",
            "path_points": [...] (optional),
            "validate_only": bool (optional),
            "tolerance": {...} (optional),
            "desired_velocity": {...} (optional)
        }
        """
        if not self._node:
            logger.error("ROS2 bridge not started")
            self._emit_navigation_rejected(data.get('cmd_id'), "ROS2 bridge not started")
            return

        cmd_id = data.get('cmd_id')
        if not cmd_id:
            logger.error("navigate_cmd requires cmd_id")
            return

        goal_x = float(data.get('goal_x', 0.0))
        goal_y = float(data.get('goal_y', 0.0))
        goal_theta = data.get('goal_theta')
        reference_frame = data.get('reference_frame', 'map')
        validate_only = data.get('validate_only', False)

        # Convert to map frame if using robot-relative coordinates
        if reference_frame == 'robot':
            with self._pose_lock:
                current_x = self._current_x
                current_y = self._current_y
                current_theta = self._current_theta

            # Rotate and translate goal
            cos_theta = math.cos(current_theta)
            sin_theta = math.sin(current_theta)
            rotated_x = goal_x * cos_theta - goal_y * sin_theta
            rotated_y = goal_x * sin_theta + goal_y * cos_theta
            goal_x = current_x + rotated_x
            goal_y = current_y + rotated_y

            if goal_theta is not None:
                goal_theta = current_theta + goal_theta

        # Convert goal_theta to quaternion
        if goal_theta is not None:
            qx, qy, qz, qw = euler_to_quaternion(0.0, 0.0, goal_theta)
        else:
            qx, qy, qz, qw = 0.0, 0.0, 0.0, 1.0

        if validate_only:
            # TODO: Implement path validation via Nav2 service
            # For now, assume path is valid
            self._emit_navigation_validation(cmd_id, True)
            return

        # Check if already navigating
        with self._nav_lock:
            if self._nav_state == NavigationState.NAVIGATING:
                # Cancel current navigation first
                self._cancel_navigation_async()

            self._nav_cmd_id = cmd_id
            self._nav_state = NavigationState.NAVIGATING

            # Calculate initial distance for progress
            with self._pose_lock:
                dx = goal_x - self._current_x
                dy = goal_y - self._current_y
                self._nav_start_distance = math.sqrt(dx * dx + dy * dy)

        # Send goal asynchronously
        self._node.send_navigation_goal(
            cmd_id=cmd_id,
            goal_x=goal_x,
            goal_y=goal_y,
            goal_qx=qx,
            goal_qy=qy,
            goal_qz=qz,
            goal_qw=qw
        )

        logger.info(f"Navigation goal sent: ({goal_x:.2f}, {goal_y:.2f}), cmd_id={cmd_id}")

    def handle_dock_cmd(self, data: Dict[str, Any]):
        """
        Handle dock_cmd from app.

        Commands robot to navigate to and dock at charging station.
        """
        cmd_id = data.get('cmd_id')
        if not cmd_id:
            logger.error("dock_cmd requires cmd_id")
            return

        # TODO: Implement docking via Nav2 dock action or custom logic
        # For now, emit a not-implemented error
        if self.on_move_response:
            self.on_move_response({
                'cmd_id': cmd_id,
                'success': False,
                'error': 'dock_not_implemented',
                'message': 'Docking is not yet implemented',
                'timestamp': timestamp_ms()
            })

    # =========================================================================
    # Internal Handlers
    # =========================================================================

    def _handle_delta_reached(self, cmd_id: str, reason: StoppedReason):
        """Called when movement delta is reached."""
        if self._node:
            self._node.publish_cmd_vel(0.0, 0.0)
        self._emit_move_response(cmd_id, reason)
        logger.info(f"Delta reached, robot stopped: cmd_id={cmd_id}")

    def _emit_move_response(self, cmd_id: Optional[str], reason: StoppedReason):
        """Emit move_response event."""
        if self.on_move_response:
            self.on_move_response({
                'cmd_id': cmd_id,
                'stopped_reason': reason.value,
                'timestamp': timestamp_ms()
            })

    def _emit_navigation_rejected(self, cmd_id: Optional[str], message: str):
        """Emit navigation_data with rejection."""
        if self.on_navigation_data:
            self.on_navigation_data({
                'cmd_id': cmd_id,
                'active': False,
                'success': False,
                'status': {
                    'code': 'remote_control_disabled',
                    'severity': 'error',
                    'message': message
                },
                'timestamp': timestamp_ms()
            })

    def _emit_navigation_validation(self, cmd_id: str, reachable: bool):
        """Emit navigation_data with validation result."""
        if self.on_navigation_data:
            self.on_navigation_data({
                'cmd_id': cmd_id,
                'active': False,
                'success': reachable,
                'validation': {
                    'reachable': reachable
                },
                'timestamp': timestamp_ms()
            })

    def _cancel_navigation_async(self):
        """Cancel navigation (async version for use in callbacks)."""
        if self._node and self._nav_goal_handle:
            try:
                future = self._nav_goal_handle.cancel_goal_async()
                # Don't wait for result in callback context
            except Exception as e:
                logger.error(f"Error cancelling navigation: {e}")

    def _cancel_navigation_sync(self):
        """Cancel navigation (sync version for use during shutdown)."""
        if self._node and self._nav_goal_handle:
            try:
                future = self._nav_goal_handle.cancel_goal_async()
                rclpy.spin_until_future_complete(self._node, future, timeout_sec=2.0)
            except Exception as e:
                logger.error(f"Error cancelling navigation: {e}")

    # =========================================================================
    # Sensor Data Handlers (called from ROS2 callbacks)
    # =========================================================================

    def _handle_battery_state(self, msg):
        """Handle BatteryState message."""
        if not self._battery_limiter.should_emit():
            return

        # Normalize percentage (some drivers use 0-1, others 0-100)
        percentage = msg.percentage
        if percentage <= 1.0:
            level = int(percentage * 100)
        else:
            level = int(min(100, percentage))

        charging = msg.power_supply_status == 1  # CHARGING

        data = {
            'level': level,
            'charging': charging,
            'timestamp': timestamp_ms()
        }

        if self.on_battery_data:
            self.on_battery_data(data)

    def _handle_odometry(self, msg):
        """Handle Odometry message."""
        # Extract pose
        x = msg.pose.pose.position.x
        y = msg.pose.pose.position.y

        q = msg.pose.pose.orientation
        _, _, theta = quaternion_to_euler(q.x, q.y, q.z, q.w)

        # Update current pose
        with self._pose_lock:
            self._current_x = x
            self._current_y = y
            self._current_theta = theta

        # Check delta tracking
        stopped_reason = self._movement_tracker.update_odometry(x, y, theta)
        if stopped_reason:
            target = self._movement_tracker.current_target
            cmd_id = target.cmd_id if target else None
            if self._node:
                self._node.publish_cmd_vel(0.0, 0.0)
            self._emit_move_response(cmd_id, stopped_reason)

        # Rate-limited emit
        if not self._pose_limiter.should_emit():
            return

        data = {
            'x': round(x, 3),
            'y': round(y, 3),
            'theta': round(theta, 4),
            'timestamp': timestamp_ms()
        }

        if self.on_pose_data:
            self.on_pose_data(data)

    def _handle_laser_scan(self, msg):
        """Handle LaserScan message."""
        if not self._scan_limiter.should_emit():
            return

        # Convert ranges to Float32Array format
        ranges = np.array(msg.ranges, dtype=np.float32)

        # Replace inf/nan with range_max
        ranges = np.where(np.isfinite(ranges), ranges, msg.range_max)

        # Convert to binary and base64 encode
        ranges_binary = ranges.tobytes()
        ranges_base64 = base64.b64encode(ranges_binary).decode('utf-8')

        data = {
            'sensor_id': 'lidar_main',
            'ranges': ranges_base64,
            'encoding': 'float32',
            'point_count': len(msg.ranges),
            'angle': {
                'min': float(msg.angle_min),
                'max': float(msg.angle_max)
            },
            'timestamp': timestamp_ms()
        }

        if self.on_scan_data:
            self.on_scan_data(data)

    def _handle_camera_image(self, msg):
        """Handle Image message."""
        if not self._camera_limiter.should_emit():
            return

        try:
            # Compress to JPEG
            jpeg_data, width, height = compress_image_jpeg(
                image_data=bytes(msg.data),
                width=msg.width,
                height=msg.height,
                encoding=msg.encoding,
                quality=self.config.camera_jpeg_quality,
                max_width=self.config.camera_max_width,
                max_height=self.config.camera_max_height
            )

            # Base64 encode
            image_base64 = base64.b64encode(jpeg_data).decode('utf-8')

            data = {
                'sensor_id': 'camera_front',
                'image_data': image_base64,
                'format': 'jpeg',
                'width': width,
                'height': height,
                'timestamp': timestamp_ms()
            }

            if self.on_camera_data:
                self.on_camera_data(data)

        except Exception as e:
            logger.error(f"Error processing camera image: {e}")

    def _handle_imu(self, msg):
        """Handle Imu message."""
        if not self._imu_limiter.should_emit():
            return

        data = {
            'sensor_id': 'imu_main',
            'acceleration': {
                'x': round(msg.linear_acceleration.x, 4),
                'y': round(msg.linear_acceleration.y, 4),
                'z': round(msg.linear_acceleration.z, 4)
            },
            'gyroscope': {
                'x': round(msg.angular_velocity.x, 4),
                'y': round(msg.angular_velocity.y, 4),
                'z': round(msg.angular_velocity.z, 4)
            },
            'timestamp': timestamp_ms()
        }

        # Add orientation if available (non-zero covariance indicates valid data)
        if msg.orientation_covariance[0] != -1:  # -1 means no orientation
            q = msg.orientation
            roll, pitch, yaw = quaternion_to_euler(q.x, q.y, q.z, q.w)
            data['orientation'] = {
                'roll': round(roll, 4),
                'pitch': round(pitch, 4),
                'yaw': round(yaw, 4)
            }

        if self.on_imu_data:
            self.on_imu_data(data)

    def _handle_diagnostics(self, msg):
        """Handle DiagnosticArray message."""
        if not self._health_limiter.should_emit():
            return

        # Convert diagnostics to health format
        faults = []
        overall_severity = 'ok'

        for status in msg.status:
            if status.level == DiagnosticStatus.OK:
                continue

            severity = 'warning' if status.level == DiagnosticStatus.WARN else 'error'
            if status.level == DiagnosticStatus.ERROR:
                overall_severity = 'error'
            elif overall_severity == 'ok' and status.level == DiagnosticStatus.WARN:
                overall_severity = 'warning'

            fault = {
                'subsystem': status.name,
                'code': status.hardware_id or 'unknown',
                'severity': severity,
                'message': status.message
            }
            faults.append(fault)

        data = {
            'overall': overall_severity,
            'faults': faults,
            'timestamp': timestamp_ms()
        }

        if self.on_health_data:
            self.on_health_data(data)

    def _handle_occupancy_grid(self, msg):
        """Handle OccupancyGrid message."""
        # Calculate hash to detect changes
        data_hash = hash(tuple(msg.data[:1000]))  # Sample for performance
        if data_hash == self._last_map_hash:
            return
        self._last_map_hash = data_hash

        if not self._map_limiter.should_emit():
            return

        # Convert to PNG format for efficient transmission
        try:
            # Create grayscale image from occupancy grid
            # 0 = free (white), 100 = occupied (black), -1 = unknown (gray)
            width = msg.info.width
            height = msg.info.height

            img_data = np.array(msg.data, dtype=np.int8).reshape((height, width))

            # Map values: -1 -> 128 (unknown), 0 -> 255 (free), 100 -> 0 (occupied)
            img = np.zeros((height, width), dtype=np.uint8)
            img[img_data == -1] = 128  # Unknown
            img[img_data == 0] = 255   # Free
            img[img_data >= 1] = 0     # Occupied (invert for visualization)

            # Encode to PNG
            if PIL_AVAILABLE:
                pil_img = PILImage.fromarray(img, mode='L')
                buffer = io.BytesIO()
                pil_img.save(buffer, format='PNG')
                png_data = buffer.getvalue()
            elif CV2_AVAILABLE:
                _, png_buffer = cv2.imencode('.png', img)
                png_data = png_buffer.tobytes()
            else:
                # Fallback: send raw data
                png_data = img.tobytes()

            data = {
                'data': base64.b64encode(png_data).decode('utf-8'),
                'format': 'png',
                'resolution': float(msg.info.resolution),
                'origin': {
                    'x': float(msg.info.origin.position.x),
                    'y': float(msg.info.origin.position.y),
                    'theta': 0.0
                },
                'width': width,
                'height': height,
                'timestamp': timestamp_ms()
            }

            if self.on_map_data:
                self.on_map_data(data)

        except Exception as e:
            logger.error(f"Error processing occupancy grid: {e}")

    def _handle_navigation_goal_response(self, accepted: bool, cmd_id: str):
        """Handle navigation goal acceptance/rejection."""
        if not accepted:
            with self._nav_lock:
                self._nav_state = NavigationState.FAILED
                self._nav_cmd_id = None

            if self.on_navigation_data:
                self.on_navigation_data({
                    'cmd_id': cmd_id,
                    'active': False,
                    'success': False,
                    'status': {
                        'code': 'invalid_goal',
                        'severity': 'error',
                        'message': 'Navigation goal rejected by planner'
                    },
                    'timestamp': timestamp_ms()
                })
        else:
            # Goal accepted - emit initial navigation_data
            if self.on_navigation_data:
                self.on_navigation_data({
                    'cmd_id': cmd_id,
                    'active': True,
                    'progress': 0,
                    'timestamp': timestamp_ms()
                })

    def _handle_navigation_feedback(self, feedback, cmd_id: str):
        """Handle navigation feedback."""
        if not self._nav_feedback_limiter.should_emit():
            return

        distance_remaining = feedback.distance_remaining

        # Calculate progress percentage
        with self._nav_lock:
            start_dist = self._nav_start_distance
        if start_dist > 0:
            progress = max(0, min(100, int((1 - distance_remaining / start_dist) * 100)))
        else:
            progress = 0

        # Calculate ETA (rough estimate)
        # Assume average speed of 0.3 m/s
        avg_speed = 0.3
        eta_seconds = int(distance_remaining / avg_speed) if avg_speed > 0 else 0

        if self.on_navigation_data:
            self.on_navigation_data({
                'cmd_id': cmd_id,
                'active': True,
                'progress': progress,
                'distance_remaining': round(distance_remaining, 2),
                'eta_seconds': eta_seconds,
                'timestamp': timestamp_ms()
            })

    def _handle_navigation_result(self, status: int, cmd_id: str):
        """
        Handle navigation result.

        Status codes (from action_msgs/GoalStatus):
        1 = ACCEPTED
        2 = EXECUTING
        3 = CANCELING
        4 = SUCCEEDED
        5 = CANCELED
        6 = ABORTED
        """
        with self._nav_lock:
            if status == 4:  # SUCCEEDED
                self._nav_state = NavigationState.SUCCEEDED
                success = True
                status_code = None
            elif status == 5:  # CANCELED
                self._nav_state = NavigationState.CANCELLED
                success = False
                status_code = 'cancelled'
            else:  # ABORTED or other failure
                self._nav_state = NavigationState.FAILED
                success = False
                status_code = 'stuck' if status == 6 else 'blocked'

            self._nav_goal_handle = None

        if self.on_navigation_data:
            data = {
                'cmd_id': cmd_id,
                'active': False,
                'success': success,
                'timestamp': timestamp_ms()
            }
            if status_code:
                data['status'] = {
                    'code': status_code,
                    'severity': 'error',
                    'message': f'Navigation {status_code}'
                }
            self.on_navigation_data(data)

        logger.info(f"Navigation completed: success={success}, cmd_id={cmd_id}")

    # =========================================================================
    # Public Methods
    # =========================================================================

    def get_current_pose(self) -> Tuple[float, float, float]:
        """Get current robot pose (x, y, theta)."""
        with self._pose_lock:
            return self._current_x, self._current_y, self._current_theta

    def is_navigating(self) -> bool:
        """Check if navigation is in progress."""
        with self._nav_lock:
            return self._nav_state == NavigationState.NAVIGATING

    def is_tracking_movement(self) -> bool:
        """Check if delta movement tracking is active."""
        return self._movement_tracker.is_tracking

    def update_config(self, **kwargs):
        """Update bridge configuration dynamically."""
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)

                # Update rate limiters if rates changed
                if key == 'battery_rate_hz':
                    self._battery_limiter = RateLimiter(value)
                elif key == 'pose_rate_hz':
                    self._pose_limiter = RateLimiter(value)
                elif key == 'scan_rate_hz':
                    self._scan_limiter = RateLimiter(value)
                elif key == 'camera_rate_hz':
                    self._camera_limiter = RateLimiter(value)
                elif key == 'imu_rate_hz':
                    self._imu_limiter = RateLimiter(value)
                elif key == 'health_rate_hz':
                    self._health_limiter = RateLimiter(value)
                elif key == 'map_rate_hz':
                    self._map_limiter = RateLimiter(value)


# =============================================================================
# Internal ROS2 Node
# =============================================================================

if ROS2_AVAILABLE:
    class _BridgeNode(Node):
        """Internal ROS2 node for the bridge."""

        def __init__(self, bridge: ROS2Bridge, node_name: str, config: BridgeConfig):
            super().__init__(node_name)
            self._bridge = bridge
            self._config = config
            self._logger = self.get_logger()

            # Callback group for concurrent callbacks
            self._callback_group = ReentrantCallbackGroup()

            # Create QoS profiles
            sensor_qos = QoSProfile(depth=10)
            latched_qos = QoSProfile(
                depth=1,
                durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
                reliability=QoSReliabilityPolicy.RELIABLE
            )

            # =====================================================
            # Publishers
            # =====================================================
            self._cmd_vel_pub = self.create_publisher(Twist, '/cmd_vel', 10)

            # =====================================================
            # Subscribers
            # =====================================================
            self._battery_sub = self.create_subscription(
                BatteryState,
                '/battery_state',
                self._battery_callback,
                sensor_qos,
                callback_group=self._callback_group
            )

            self._odom_sub = self.create_subscription(
                Odometry,
                '/odom',
                self._odom_callback,
                sensor_qos,
                callback_group=self._callback_group
            )

            self._scan_sub = self.create_subscription(
                LaserScan,
                '/scan',
                self._scan_callback,
                sensor_qos,
                callback_group=self._callback_group
            )

            self._camera_sub = self.create_subscription(
                Image,
                '/camera/image_raw',
                self._camera_callback,
                sensor_qos,
                callback_group=self._callback_group
            )

            self._imu_sub = self.create_subscription(
                Imu,
                '/imu/data',
                self._imu_callback,
                sensor_qos,
                callback_group=self._callback_group
            )

            self._diagnostics_sub = self.create_subscription(
                DiagnosticArray,
                '/diagnostics',
                self._diagnostics_callback,
                sensor_qos,
                callback_group=self._callback_group
            )

            self._map_sub = self.create_subscription(
                OccupancyGrid,
                '/map',
                self._map_callback,
                latched_qos,
                callback_group=self._callback_group
            )

            # =====================================================
            # Action Client for Navigation
            # =====================================================
            self._nav_action_client = ActionClient(
                self,
                NavigateToPose,
                config.nav_action_name,
                callback_group=self._callback_group
            )

            # Track pending navigation
            self._pending_nav_cmd_id: Optional[str] = None

            self._logger.info(f'ROS2 Bridge Node initialized: {node_name}')

        def publish_cmd_vel(self, linear_x: float, angular_z: float):
            """Publish Twist message to /cmd_vel."""
            msg = Twist()
            msg.linear.x = float(linear_x)
            msg.linear.y = 0.0
            msg.linear.z = 0.0
            msg.angular.x = 0.0
            msg.angular.y = 0.0
            msg.angular.z = float(angular_z)
            self._cmd_vel_pub.publish(msg)

        def send_navigation_goal(
            self,
            cmd_id: str,
            goal_x: float,
            goal_y: float,
            goal_qx: float,
            goal_qy: float,
            goal_qz: float,
            goal_qw: float
        ):
            """Send navigation goal to Nav2."""
            # Wait for action server (with timeout)
            if not self._nav_action_client.wait_for_server(timeout_sec=5.0):
                self._logger.error("Navigation action server not available")
                self._bridge._handle_navigation_goal_response(False, cmd_id)
                return

            # Create goal message
            goal_msg = NavigateToPose.Goal()
            goal_msg.pose.header.stamp = self.get_clock().now().to_msg()
            goal_msg.pose.header.frame_id = self._config.global_frame_id
            goal_msg.pose.pose.position.x = goal_x
            goal_msg.pose.pose.position.y = goal_y
            goal_msg.pose.pose.position.z = 0.0
            goal_msg.pose.pose.orientation.x = goal_qx
            goal_msg.pose.pose.orientation.y = goal_qy
            goal_msg.pose.pose.orientation.z = goal_qz
            goal_msg.pose.pose.orientation.w = goal_qw

            self._pending_nav_cmd_id = cmd_id

            # Send goal with callbacks
            send_goal_future = self._nav_action_client.send_goal_async(
                goal_msg,
                feedback_callback=self._nav_feedback_callback
            )
            send_goal_future.add_done_callback(self._nav_goal_response_callback)

        def _nav_goal_response_callback(self, future):
            """Handle navigation goal response."""
            try:
                goal_handle = future.result()
                cmd_id = self._pending_nav_cmd_id

                if not goal_handle.accepted:
                    self._bridge._handle_navigation_goal_response(False, cmd_id)
                    return

                self._bridge._nav_goal_handle = goal_handle
                self._bridge._handle_navigation_goal_response(True, cmd_id)

                # Get result async
                result_future = goal_handle.get_result_async()
                result_future.add_done_callback(self._nav_result_callback)

            except Exception as e:
                self._logger.error(f"Error in navigation goal response: {e}")

        def _nav_feedback_callback(self, feedback_msg):
            """Handle navigation feedback."""
            try:
                cmd_id = self._pending_nav_cmd_id
                if cmd_id:
                    self._bridge._handle_navigation_feedback(
                        feedback_msg.feedback,
                        cmd_id
                    )
            except Exception as e:
                self._logger.error(f"Error in navigation feedback: {e}")

        def _nav_result_callback(self, future):
            """Handle navigation result."""
            try:
                result = future.result()
                cmd_id = self._pending_nav_cmd_id
                self._pending_nav_cmd_id = None

                if cmd_id:
                    self._bridge._handle_navigation_result(result.status, cmd_id)
            except Exception as e:
                self._logger.error(f"Error in navigation result: {e}")

        # =====================================================
        # Sensor Callbacks
        # =====================================================

        def _battery_callback(self, msg: BatteryState):
            """Handle BatteryState message."""
            try:
                self._bridge._handle_battery_state(msg)
            except Exception as e:
                self._logger.error(f"Error in battery callback: {e}")

        def _odom_callback(self, msg: Odometry):
            """Handle Odometry message."""
            try:
                self._bridge._handle_odometry(msg)
            except Exception as e:
                self._logger.error(f"Error in odometry callback: {e}")

        def _scan_callback(self, msg: LaserScan):
            """Handle LaserScan message."""
            try:
                self._bridge._handle_laser_scan(msg)
            except Exception as e:
                self._logger.error(f"Error in scan callback: {e}")

        def _camera_callback(self, msg: Image):
            """Handle Image message."""
            try:
                self._bridge._handle_camera_image(msg)
            except Exception as e:
                self._logger.error(f"Error in camera callback: {e}")

        def _imu_callback(self, msg: Imu):
            """Handle Imu message."""
            try:
                self._bridge._handle_imu(msg)
            except Exception as e:
                self._logger.error(f"Error in IMU callback: {e}")

        def _diagnostics_callback(self, msg: DiagnosticArray):
            """Handle DiagnosticArray message."""
            try:
                self._bridge._handle_diagnostics(msg)
            except Exception as e:
                self._logger.error(f"Error in diagnostics callback: {e}")

        def _map_callback(self, msg: OccupancyGrid):
            """Handle OccupancyGrid message."""
            try:
                self._bridge._handle_occupancy_grid(msg)
            except Exception as e:
                self._logger.error(f"Error in map callback: {e}")

else:
    # Dummy class when ROS2 not available
    class _BridgeNode:
        pass


# =============================================================================
# Utility Functions
# =============================================================================

def is_ros2_available() -> bool:
    """Check if ROS2 is available."""
    return ROS2_AVAILABLE


def create_bridge_from_params(node: 'Node') -> ROS2Bridge:
    """
    Create ROS2Bridge with configuration from ROS2 parameters.

    Expected parameters:
    - sensor_publish_rate (float): Default sensor rate in Hz
    - camera_jpeg_quality (int): JPEG quality 1-100
    - max_linear_velocity (float): Max linear velocity m/s
    - max_angular_velocity (float): Max angular velocity rad/s
    """
    if not ROS2_AVAILABLE:
        raise RuntimeError("ROS2 not available")

    # Declare parameters with defaults
    node.declare_parameter('sensor_publish_rate', 10.0)
    node.declare_parameter('camera_jpeg_quality', 85)
    node.declare_parameter('max_linear_velocity', 1.0)
    node.declare_parameter('max_angular_velocity', 2.0)

    # Get parameter values
    sensor_rate = node.get_parameter('sensor_publish_rate').value
    jpeg_quality = node.get_parameter('camera_jpeg_quality').value
    max_linear = node.get_parameter('max_linear_velocity').value
    max_angular = node.get_parameter('max_angular_velocity').value

    # Create config
    config = BridgeConfig(
        pose_rate_hz=sensor_rate,
        scan_rate_hz=sensor_rate,
        imu_rate_hz=sensor_rate,
        camera_jpeg_quality=jpeg_quality,
        max_linear_velocity=max_linear,
        max_angular_velocity=max_angular
    )

    return ROS2Bridge(config=config)
