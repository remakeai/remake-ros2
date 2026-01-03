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
WebSocket client for robot connection to Appstore
Uses python-socketio to match backend Socket.IO server
Uses event names from ilia branch (Nov 28, 2025)
"""
import time
import threading
from typing import Optional, Callable, Dict, Any

import socketio

from .ros2_bridge import ROS2Bridge, is_ros2_available


class RobotConnection:
    """
    Socket.IO connection handler for robot-to-platform communication

    IMPORTANT: Backend uses Socket.IO (not raw WebSocket), so we must use
    python-socketio client to properly handle the Socket.IO protocol.

    Event names (ilia branch conventions):
    - authenticate_cmd: Robot sends auth credentials
    - authenticate_response: Platform confirms auth
    - ping_cmd: Robot heartbeat with t1 timestamp
    - ping_response: Platform responds with t1, t2, t3, buffered_amount
    - establish_app_session_cmd: Platform sends Phase 1 app launch (API 0.2.0)
    - setup_app_cmd: Platform sends Phase 2 app setup (API 0.2.0)
    - enable_remote_control_cmd: Platform sends Phase 3 enable control (API 0.2.0)
    - app_exited_event: Robot notifies app termination
    """

    def __init__(
        self,
        appstore_url: str,
        robot_id: str,
        robot_secret: str,
        on_launch_app: Optional[Callable[[Dict[str, Any]], None]] = None,
        enable_ros2: bool = False
    ):
        self.appstore_url = appstore_url.rstrip('/')
        self.robot_id = robot_id
        self.robot_secret = robot_secret
        self.on_launch_app = on_launch_app
        self.enable_ros2 = enable_ros2

        self.connected = False
        self.authenticated = False
        self._running = False
        self._rtt_ms: Optional[float] = None
        self._auth_event = threading.Event()
        self._auth_success = False
        self._auth_message = ""

        # ROS2 bridge (initialized if enable_ros2=True)
        self.ros2_bridge: Optional[ROS2Bridge] = None

        # Create Socket.IO client
        self.sio = socketio.Client(
            reconnection=True,
            reconnection_attempts=5,
            reconnection_delay=1,
            logger=False,
            engineio_logger=False
        )

        # Register event handlers
        self._register_handlers()

    def _register_handlers(self):
        """Register Socket.IO event handlers for /robot-control namespace"""

        @self.sio.on('connect', namespace='/robot-control')
        def on_connect():
            print(f"Connected to {self.appstore_url}/robot-control")
            self.connected = True

            # Send authentication immediately after connect
            # API 0.2.0: product_id removed (now in robot_description)
            self.sio.emit('authenticate_cmd', {
                'robot_id': self.robot_id,
                'robot_secret': self.robot_secret
            }, namespace='/robot-control')

        @self.sio.on('disconnect', namespace='/robot-control')
        def on_disconnect():
            print("Disconnected from server")
            self.connected = False
            self.authenticated = False
            self._running = False

        @self.sio.on('authenticate_response', namespace='/robot-control')
        def on_auth_response(data):
            """Handle authentication response from platform"""
            if data.get('success'):
                self.authenticated = True
                self._auth_success = True
                self._auth_message = data.get('message', 'Authenticated')
                print(f"Authenticated successfully")
                print(f"Robot '{self.robot_id}' is now ONLINE")

                # Start ROS2 bridge if enabled
                if self.enable_ros2:
                    self._start_ros2_bridge()

                # Start heartbeat thread
                self._start_heartbeat()
            else:
                self._auth_success = False
                self._auth_message = data.get('message', 'Authentication failed')
                print(f"Authentication failed: {self._auth_message}")
                self._running = False

            self._auth_event.set()

        @self.sio.on('ping_response', namespace='/robot-control')
        def on_ping_response(data):
            """Handle ping response for RTT calculation"""
            t4 = time.time()  # Current time in seconds
            t1 = data.get('t1', t4)
            t2 = data.get('t2', t4)
            t3 = data.get('t3', t4)

            # RTT = (t4 - t1) - (t3 - t2), convert to ms
            self._rtt_ms = int(((t4 - t1) - (t3 - t2)) * 1000)

            # Report RTT back to backend for UI display
            self.sio.emit('rtt_report', {'rtt_ms': self._rtt_ms}, namespace='/robot-control')

        # API 0.2.0: Three-Phase App Launch Protocol
        @self.sio.on('establish_app_session_cmd', namespace='/robot-control')
        def on_establish_app_session(data):
            """Phase 1: Handle establish app session command from platform"""
            print(f"[Phase 1] Received establish_app_session_cmd: {data}")

            if self.on_launch_app:
                try:
                    self.on_launch_app(data)
                except Exception as e:
                    self.sio.emit('establish_app_session_response', {
                        'session_id': data.get('session_id'),
                        'status': 'failed',
                        'error_message': str(e)
                    }, namespace='/robot-control')
                    return

            # Send success response for Phase 1
            self.sio.emit('establish_app_session_response', {
                'session_id': data.get('session_id'),
                'status': 'success'
            }, namespace='/robot-control')

        @self.sio.on('setup_app_cmd', namespace='/robot-control')
        def on_setup_app(data):
            """Phase 2: Handle app setup command"""
            print(f"[Phase 2] Received setup_app_cmd: {data}")
            # CLI doesn't do app setup, just respond success
            self.sio.emit('setup_app_response', {
                'session_id': data.get('session_id'),
                'status': 'success'
            }, namespace='/robot-control')

        @self.sio.on('enable_remote_control_cmd', namespace='/robot-control')
        def on_enable_remote_control(data):
            """Phase 3: Handle enable remote control command"""
            print(f"[Phase 3] Received enable_remote_control_cmd: {data}")
            # CLI enables remote control (twist commands already handled)
            self.sio.emit('enable_remote_control_response', {
                'session_id': data.get('session_id'),
                'status': 'success'
            }, namespace='/robot-control')
            print(f"[Phase 3] App session ready - remote control enabled")

        @self.sio.on('twist_command', namespace='/robot-control')
        def on_twist_command(data):
            """Handle twist command from RPC app - forward to ROS2"""
            linear_x = float(data.get('linear_x', 0))
            angular_z = float(data.get('angular_z', 0))

            if self.ros2_bridge:
                self.ros2_bridge.publish_cmd_vel(linear_x, angular_z)
                print(f"[ROS2] /cmd_vel: linear={linear_x:.2f}, angular={angular_z:.2f}")
            else:
                print(f"[Twist] Received but ROS2 not enabled: linear={linear_x:.2f}, angular={angular_z:.2f}")

        @self.sio.on('unpaired', namespace='/robot-control')
        def on_unpaired(data):
            """Handle unpaired notification from platform"""
            print("Robot has been unpaired from Appstore")
            self._running = False
            self.sio.disconnect()

        @self.sio.on('connect_error', namespace='/robot-control')
        def on_connect_error(data):
            print(f"Connection error: {data}")
            self._running = False
            self._auth_event.set()

    def _start_heartbeat(self):
        """Start heartbeat thread to send periodic ping_cmd"""
        def heartbeat_loop():
            while self._running and self.authenticated:
                time.sleep(30)
                if self._running and self.authenticated:
                    t1 = time.time()  # Seconds for consistency
                    self.sio.emit('ping_cmd', {'t1': t1}, namespace='/robot-control')

        thread = threading.Thread(target=heartbeat_loop, daemon=True)
        thread.start()

    def _start_ros2_bridge(self):
        """Start ROS2 bridge for publishing /cmd_vel"""
        if not is_ros2_available():
            print("[ROS2] ROS2 not available. Install rclpy to enable.")
            return

        def on_pose(pose_data):
            """Callback when ROS2 receives pose from /odom"""
            if self.authenticated:
                self.sio.emit('robot_pose', pose_data, namespace='/robot-control')

        def on_battery(battery_data):
            """Callback when ROS2 receives battery state"""
            if self.authenticated:
                self.sio.emit('battery', battery_data, namespace='/robot-control')

        self.ros2_bridge = ROS2Bridge(on_pose=on_pose, on_battery=on_battery)
        self.ros2_bridge.start()

    def connect(self) -> bool:
        """
        Establish Socket.IO connection and authenticate

        Returns True if connection and auth successful, False otherwise
        """
        self._running = True
        self._auth_event.clear()

        try:
            # Connect to Socket.IO server with /robot-control namespace
            self.sio.connect(
                self.appstore_url,
                namespaces=['/robot-control'],
                transports=['websocket']
            )

            # Wait for authentication response (timeout 10 seconds)
            if not self._auth_event.wait(timeout=10.0):
                print("Authentication timeout")
                self.sio.disconnect()
                return False

            return self._auth_success

        except socketio.exceptions.ConnectionError as e:
            print(f"Connection failed: {e}")
            return False
        except Exception as e:
            print(f"Connection error: {e}")
            return False

    def wait(self):
        """Wait for connection to end (blocking)"""
        try:
            self.sio.wait()
        except KeyboardInterrupt:
            pass

    def disconnect(self):
        """Disconnect from server"""
        self._running = False
        if self.ros2_bridge:
            self.ros2_bridge.stop()
        if self.sio.connected:
            self.sio.disconnect()

    def stop(self):
        """Stop the connection (alias for disconnect)"""
        self.disconnect()

    @property
    def rtt_ms(self) -> Optional[float]:
        """Get last measured RTT in milliseconds"""
        return self._rtt_ms


def connect_robot(
    appstore_url: str,
    robot_id: str,
    robot_secret: str,
    enable_ros2: bool = False
) -> None:
    """
    Connect robot to Appstore and stay online (blocking)

    This is the main entry point for `kaia connect`

    Args:
        enable_ros2: If True, start ROS2 bridge to publish /cmd_vel
    """
    connection = RobotConnection(
        appstore_url=appstore_url,
        robot_id=robot_id,
        robot_secret=robot_secret,
        enable_ros2=enable_ros2
    )

    if connection.connect():
        print("Press Ctrl+C to disconnect")
        try:
            connection.wait()
        except KeyboardInterrupt:
            print("\nDisconnecting...")
        finally:
            connection.disconnect()
    else:
        print("Failed to connect")

    print("Disconnected")
