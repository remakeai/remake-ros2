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
WebSocket client for robot connection to Platform.
Uses python-socketio to match backend Socket.IO server.

Implements Robot Management API from:
  robot/management/ROBOT_MANAGEMENT_API.md
"""
import time
import hmac
import hashlib
import threading
from typing import Optional, Callable, Dict, Any

import socketio

from .ros2_bridge import ROS2Bridge, is_ros2_available


class RobotConnection:
    """
    Socket.IO connection handler for robot-to-platform communication.

    Implements Robot Management API:
    - Challenge-response authentication (HMAC-SHA256)
    - Three-phase app launch protocol
    - Heartbeat/ping system
    - Factory reset handling

    Event names (from ROBOT_MANAGEMENT_API.md):
    - authenticate_cmd: Robot sends robot_id
    - authenticate_challenge: Platform sends nonce
    - authenticate_response: Robot sends HMAC signature
    - authenticate_result: Platform confirms auth
    - ping_cmd/ping_response: Heartbeat with RTT
    - establish_app_session_cmd: Phase 1 app launch
    - setup_app_cmd: Phase 2 app setup
    - enable_remote_control_cmd: Phase 3 enable control
    - factory_reset_cmd: Platform requests factory reset
    """

    def __init__(
        self,
        platform_url: str,
        robot_id: str,
        robot_secret: str,
        on_launch_app: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_factory_reset: Optional[Callable[[], None]] = None,
        enable_ros2: bool = False
    ):
        self.platform_url = platform_url.rstrip('/')
        self.robot_id = robot_id
        self.robot_secret = robot_secret
        self.on_launch_app = on_launch_app
        self.on_factory_reset = on_factory_reset
        self.enable_ros2 = enable_ros2

        self.connected = False
        self.authenticated = False
        self._running = False
        self._rtt_ms: Optional[float] = None
        self._auth_event = threading.Event()
        self._auth_success = False
        self._auth_message = ""

        # Current app session (only one at a time)
        self._current_session: Optional[Dict[str, Any]] = None

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

    def _compute_signature(self, nonce: str) -> str:
        """Compute HMAC-SHA256 signature for challenge-response auth."""
        signature = hmac.new(
            self.robot_secret.encode('utf-8'),
            nonce.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        return signature

    def _register_handlers(self):
        """Register Socket.IO event handlers for /robot-control namespace."""

        @self.sio.on('connect', namespace='/robot-control')
        def on_connect():
            print(f"Connected to {self.platform_url}/robot-control")
            self.connected = True

            # Step 1: Send authenticate_cmd with robot_id
            self.sio.emit('authenticate_cmd', {
                'robot_id': self.robot_id
            }, namespace='/robot-control')

        @self.sio.on('disconnect', namespace='/robot-control')
        def on_disconnect():
            print("Disconnected from server")
            self.connected = False
            self.authenticated = False
            self._running = False

        @self.sio.on('authenticate_challenge', namespace='/robot-control')
        def on_auth_challenge(data):
            """Step 2: Receive nonce and respond with signature."""
            if data.get('success') is False:
                # Robot not found or other error
                self._auth_success = False
                self._auth_message = data.get('message', 'Authentication failed')
                print(f"Authentication failed: {self._auth_message}")
                self._auth_event.set()
                return

            nonce = data.get('nonce')
            if not nonce:
                self._auth_success = False
                self._auth_message = "No nonce received"
                self._auth_event.set()
                return

            # Compute HMAC-SHA256 signature
            signature = self._compute_signature(nonce)

            # Step 3: Send authenticate_response with signature
            self.sio.emit('authenticate_response', {
                'signature': signature
            }, namespace='/robot-control')

        @self.sio.on('authenticate_result', namespace='/robot-control')
        def on_auth_result(data):
            """Step 4: Handle final authentication result."""
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
            """Handle ping response for RTT calculation."""
            t4 = time.time() * 1000  # Current time in ms
            t1 = data.get('t1', t4)
            t2 = data.get('t2', t4)
            t3 = data.get('t3', t4)

            # RTT = (t4 - t1) - (t3 - t2)
            self._rtt_ms = int((t4 - t1) - (t3 - t2))

        # =====================================================================
        # Three-Phase App Launch Protocol
        # =====================================================================

        @self.sio.on('establish_app_session_cmd', namespace='/robot-control')
        def on_establish_app_session(data):
            """Phase 1: Handle establish app session command from platform."""
            cmd_id = data.get('cmd_id')
            session_id = data.get('session_id')
            app_id = data.get('app_id')

            print(f"[Phase 1] App session request: {app_id}")

            # Store current session
            self._current_session = {
                'session_id': session_id,
                'app_id': app_id,
                'session_token': data.get('session_token'),
                'app_ws_url': data.get('app_ws_url')
            }

            if self.on_launch_app:
                try:
                    self.on_launch_app(data)
                except Exception as e:
                    self.sio.emit('establish_app_session_response', {
                        'cmd_id': cmd_id,
                        'session_id': session_id,
                        'status': 'failed',
                        'error': 'launch_error',
                        'error_message': str(e)
                    }, namespace='/robot-control')
                    return

            # Send success response
            self.sio.emit('establish_app_session_response', {
                'cmd_id': cmd_id,
                'session_id': session_id,
                'status': 'success'
            }, namespace='/robot-control')

        @self.sio.on('setup_app_cmd', namespace='/robot-control')
        def on_setup_app(data):
            """Phase 2: Handle app setup command."""
            cmd_id = data.get('cmd_id')
            session_id = data.get('session_id')

            print(f"[Phase 2] App setup: {session_id}")

            # CLI doesn't need special setup, respond success
            self.sio.emit('setup_app_response', {
                'cmd_id': cmd_id,
                'session_id': session_id,
                'status': 'success'
            }, namespace='/robot-control')

        @self.sio.on('enable_remote_control_cmd', namespace='/robot-control')
        def on_enable_remote_control(data):
            """Phase 3: Handle enable remote control command."""
            cmd_id = data.get('cmd_id')
            session_id = data.get('session_id')

            print(f"[Phase 3] Remote control enabled: {session_id}")

            self.sio.emit('enable_remote_control_response', {
                'cmd_id': cmd_id,
                'session_id': session_id,
                'status': 'success'
            }, namespace='/robot-control')

            print("App session ready - remote control enabled")

        @self.sio.on('terminate_app_cmd', namespace='/robot-control')
        def on_terminate_app(data):
            """Handle app termination command from platform."""
            cmd_id = data.get('cmd_id')
            session_id = data.get('session_id')

            print(f"App session terminated: {session_id}")
            self._current_session = None

            self.sio.emit('terminate_app_response', {
                'cmd_id': cmd_id,
                'session_id': session_id,
                'status': 'success'
            }, namespace='/robot-control')

        # =====================================================================
        # Movement Commands (from app via relay)
        # =====================================================================

        @self.sio.on('move_cmd', namespace='/robot-control')
        def on_move_cmd(data):
            """Handle move command - forward to ROS2."""
            linear = data.get('linear', {})
            angular = data.get('angular', {})

            linear_x = float(linear.get('x', 0))
            angular_z = float(angular.get('z', 0))

            if self.ros2_bridge:
                self.ros2_bridge.publish_cmd_vel(linear_x, angular_z)
                print(f"[ROS2] /cmd_vel: linear={linear_x:.2f}, angular={angular_z:.2f}")
            else:
                print(f"[Move] Received (ROS2 not enabled): linear={linear_x:.2f}, angular={angular_z:.2f}")

        @self.sio.on('stop_cmd', namespace='/robot-control')
        def on_stop_cmd(data):
            """Handle stop command - stop robot immediately."""
            if self.ros2_bridge:
                self.ros2_bridge.publish_cmd_vel(0, 0)
                print("[ROS2] Stop command - velocities set to zero")
            else:
                print("[Stop] Received (ROS2 not enabled)")

        # =====================================================================
        # Factory Reset
        # =====================================================================

        @self.sio.on('factory_reset_cmd', namespace='/robot-control')
        def on_factory_reset(data):
            """Handle factory reset command from platform."""
            cmd_id = data.get('cmd_id')
            reason = data.get('reason', 'platform_initiated')

            print(f"Factory reset requested: {reason}")

            if self.on_factory_reset:
                try:
                    self.on_factory_reset()
                    self.sio.emit('factory_reset_response', {
                        'cmd_id': cmd_id,
                        'success': True,
                        'message': 'Factory reset initiated'
                    }, namespace='/robot-control')
                except Exception as e:
                    self.sio.emit('factory_reset_response', {
                        'cmd_id': cmd_id,
                        'success': False,
                        'error': 'reset_failed',
                        'message': str(e)
                    }, namespace='/robot-control')
            else:
                # No handler, just acknowledge
                self.sio.emit('factory_reset_response', {
                    'cmd_id': cmd_id,
                    'success': True,
                    'message': 'Factory reset acknowledged'
                }, namespace='/robot-control')

            # Disconnect after factory reset
            self._running = False
            self.sio.disconnect()

        @self.sio.on('connect_error', namespace='/robot-control')
        def on_connect_error(data):
            print(f"Connection error: {data}")
            self._running = False
            self._auth_event.set()

    def _start_heartbeat(self):
        """Start heartbeat thread to send periodic ping_cmd."""
        def heartbeat_loop():
            while self._running and self.authenticated:
                time.sleep(30)
                if self._running and self.authenticated:
                    t1 = int(time.time() * 1000)  # Milliseconds
                    self.sio.emit('ping_cmd', {'t1': t1}, namespace='/robot-control')

        thread = threading.Thread(target=heartbeat_loop, daemon=True)
        thread.start()

    def _start_ros2_bridge(self):
        """Start ROS2 bridge for publishing /cmd_vel and receiving sensor data."""
        if not is_ros2_available():
            print("[ROS2] ROS2 not available. Install rclpy to enable.")
            return

        def on_pose(pose_data):
            """Callback when ROS2 receives pose from /odom."""
            if self.authenticated and self._current_session:
                self.sio.emit('pose_data', pose_data, namespace='/robot-control')

        def on_battery(battery_data):
            """Callback when ROS2 receives battery state."""
            if self.authenticated:
                self.sio.emit('battery_data', battery_data, namespace='/robot-control')

        self.ros2_bridge = ROS2Bridge(on_pose=on_pose, on_battery=on_battery)
        self.ros2_bridge.start()
        print("[ROS2] Bridge started - listening to /odom, /battery_state")

    def connect(self) -> bool:
        """
        Establish Socket.IO connection and authenticate.

        Returns True if connection and auth successful, False otherwise.
        """
        self._running = True
        self._auth_event.clear()

        try:
            # Connect to Socket.IO server with /robot-control namespace
            self.sio.connect(
                self.platform_url,
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
        """Wait for connection to end (blocking)."""
        try:
            self.sio.wait()
        except KeyboardInterrupt:
            pass

    def disconnect(self):
        """Disconnect from server."""
        self._running = False
        if self.ros2_bridge:
            self.ros2_bridge.stop()
        if self.sio.connected:
            self.sio.disconnect()

    def stop(self):
        """Stop the connection (alias for disconnect)."""
        self.disconnect()

    @property
    def rtt_ms(self) -> Optional[float]:
        """Get last measured RTT in milliseconds."""
        return self._rtt_ms

    @property
    def current_session(self) -> Optional[Dict[str, Any]]:
        """Get current app session info."""
        return self._current_session


def connect_robot(
    platform_url: str,
    robot_id: str,
    robot_secret: str,
    enable_ros2: bool = False,
    on_factory_reset: Optional[Callable[[], None]] = None
) -> None:
    """
    Connect robot to Platform and stay online (blocking).

    This is the main entry point for `remake connect`.

    Args:
        platform_url: WebSocket URL (e.g., wss://apps.remake.ai)
        robot_id: Robot identifier
        robot_secret: Robot authentication secret
        enable_ros2: If True, start ROS2 bridge to publish /cmd_vel
        on_factory_reset: Callback for factory reset (clear credentials)
    """
    connection = RobotConnection(
        platform_url=platform_url,
        robot_id=robot_id,
        robot_secret=robot_secret,
        enable_ros2=enable_ros2,
        on_factory_reset=on_factory_reset
    )

    if connection.connect():
        print("Waiting for app session... (Press Ctrl+C to disconnect)")
        try:
            connection.wait()
        except KeyboardInterrupt:
            print("\nDisconnecting...")
        finally:
            connection.disconnect()
    else:
        print("Failed to connect")

    print("Disconnected")
