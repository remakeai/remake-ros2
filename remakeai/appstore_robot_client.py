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
Remake.ai platform Robot Client
Connects Kaia.ai robots to the Remake.ai platform using Socket.IO
"""
import asyncio
import socketio
import logging
import time
import sys
import os
import hmac
import hashlib
from robot_client_ros2 import RobotClientROS2

class AppstoreRobotClient(RobotClientROS2):
    """Robot client that connects to Remake.ai platform via Socket.IO"""

    def __init__(self, robot_id, robot_secret, specification=None, appstore_url="http://localhost:5000"):
        """
        Initialize platform Robot Client

        Args:
            robot_id: Robot ID from platform UI (UUID)
            robot_secret: Secret token from platform UI (plain text, will be sent for bcrypt verification)
            specification: Robot specification dictionary
            appstore_url: Platform backend URL (default: https://apps.remake.ai)
        """
        # Initialize parent ROS2 client
        super().__init__(specification)

        self.robot_id = robot_id
        self.robot_secret = robot_secret
        self.appstore_url = appstore_url
        self.authenticated = False

        # Create Socket.IO client
        self.sio = socketio.AsyncClient(
            logger=False,
            engineio_logger=False,
            reconnection=True,
            reconnection_attempts=0,  # Infinite retries
            reconnection_delay=3,
            reconnection_delay_max=10
        )

        # Register Socket.IO event handlers
        self._register_socketio_handlers()

        # Heartbeat task
        self.heartbeat_task = None

        self.get_logger().info(f"🤖 Platform Robot Client initialized for robot: {robot_id}")

    def _register_socketio_handlers(self):
        """Register Socket.IO event handlers on the /robot-control namespace"""

        @self.sio.on('connect', namespace='/robot-control')
        async def on_connect():
            self.get_logger().info("✅ Connected to namespace - authenticating...")
            # Send authentication with just robot_id (new flow)
            await self.sio.emit('authenticate_cmd', {
                'robot_id': self.robot_id,
                'robot_secret': self.robot_secret
            }, namespace='/robot-control')

        @self.sio.on('authenticate_challenge', namespace='/robot-control')
        async def on_authenticate_challenge(data):
            """Handle authentication challenge (new challenge-response flow)"""
            nonce = data.get('nonce')
            self.get_logger().info(f"🔐 Received authentication challenge with nonce")

            # Generate HMAC-SHA256 signature
            signature = hmac.new(
                self.robot_secret.encode(),
                nonce.encode(),
                hashlib.sha256
            ).hexdigest()

            # Send response with signature
            await self.sio.emit('authenticate_response', {
                'robot_id': self.robot_id,
                'signature': signature
            }, namespace='/robot-control')

            self.get_logger().debug("🔐 Sent authentication response with signature")

        @self.sio.on('authenticate_response', namespace='/robot-control')
        async def on_authenticate_response(data):
            """Handle authentication result from server"""
            success = data.get('success', False)
            message = data.get('message', '')

            if success:
                self.get_logger().info(f"✅ Authentication successful: {message}")
                self.authenticated = True
                self.running = True

                # Set remote control status as connected
                self.set_remote_control_status(True)

                # Start heartbeat
                if self.heartbeat_task is None or self.heartbeat_task.done():
                    self.heartbeat_task = asyncio.create_task(self._heartbeat_loop())

                # Send robot specification
                await self.send_robot_specification()
            else:
                self.get_logger().error(f"❌ Authentication failed: {message}")
                self.authenticated = False
                self.running = False
                # Don't disconnect - Socket.IO will handle reconnection

        @self.sio.on('disconnect', namespace='/robot-control')
        async def on_disconnect():
            self.get_logger().warning("🔌 Disconnected from platform")
            self.authenticated = False
            self.running = False

            # Set remote control status as disconnected
            self.set_remote_control_status(False)

            # Cancel heartbeat
            if self.heartbeat_task and not self.heartbeat_task.done():
                self.heartbeat_task.cancel()

        @self.sio.on('ping_response', namespace='/robot-control')
        async def on_ping_response(data):
            """Response to ping heartbeat"""
            self.get_logger().debug(f"💓 Received ping_response from platform")

        @self.sio.on('ping_cmd', namespace='/robot-control')
        async def on_ping_cmd(data):
            """Handle ping command from server (server-initiated ping)"""
            t1 = data.get('t1')
            t2 = time.time()

            # Respond with ping_response
            await self.sio.emit('ping_response', {
                't1': t1,
                't2': t2,
                't3': time.time()
            }, namespace='/robot-control')

            self.get_logger().debug("💓 Responded to ping_cmd from appstore")

        @self.sio.on('launch_app', namespace='/robot-control')
        async def on_launch_app(data):
            """Handle app launch command from platform"""
            self.get_logger().info(f"🚀 Received launch_app command: {data}")

            session_id = data.get('session_id')
            app_id = data.get('app_id')
            session_token = data.get('session_token')
            connection_ticket = data.get('connection_ticket')

            # TODO: Implement actual app launch logic here
            # For now, just acknowledge success
            await self.sio.emit('launch_status', {
                'session_id': session_id,
                'status': 'success',
                'message': f'App {app_id} launched successfully'
            }, namespace='/robot-control')

            self.get_logger().info(f"✅ App {app_id} launch acknowledged (session: {session_id})")

        @self.sio.on('error', namespace='/robot-control')
        async def on_error(data):
            """Handle error messages from platform"""
            self.get_logger().error(f"❌ Error from platform: {data.get('message', 'Unknown error')}")

        @self.sio.on('get_robot_description_cmd', namespace='/robot-control')
        async def on_get_robot_description(data):
            """Handle request for robot description/specification"""
            self.get_logger().info("📋 Received get_robot_description_cmd, sending specification")

            # Send robot specification as response
            robot_spec = self.specification.copy()
            robot_spec["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")
            robot_spec["robot_id"] = self.robot_id

            await self.sio.emit('get_robot_description_response', {
                'robot_id': self.robot_id,
                'specification': robot_spec
            }, namespace='/robot-control')

        @self.sio.on('twist_command', namespace='/robot-control')
        async def on_twist_command(data):
            """Handle twist (velocity) command from app via platform"""
            linear_x = data.get('linear_x', 0.0)
            angular_z = data.get('angular_z', 0.0)
            self.get_logger().debug(f"🎮 Received twist_command: linear={linear_x}, angular={angular_z}")
            # Route to internal message callback system
            await self.set_velocity({'linear_x': linear_x, 'angular_z': angular_z})

        @self.sio.on('navigate_cmd', namespace='/robot-control')
        async def on_navigate_cmd(data):
            """Handle navigation command from app via platform"""
            self.get_logger().info(f"🧭 Received navigate_cmd: {data}")

            # Convert yaw to quaternion if provided
            import math
            yaw = float(data.get('yaw', 0.0))
            qz = math.sin(yaw / 2.0)
            qw = math.cos(yaw / 2.0)

            # Format command for navigate_to_pose
            command = {
                'pose': {
                    'x': float(data.get('x', 0.0)),
                    'y': float(data.get('y', 0.0)),
                    'z': 0.0,
                    'qx': 0.0,
                    'qy': 0.0,
                    'qz': qz,
                    'qw': qw,
                    'frame_id': 'map'
                },
                'relative': data.get('relative', False)
            }
            await self.navigate_to_pose(command)

    async def connect_to_appstore(self):
        """Connect to the Remake.ai platform"""
        try:
            self.get_logger().info(f"🔗 Connecting to Platform at {self.appstore_url}/robot-control")

            # Connect to the /robot-control namespace
            await self.sio.connect(
                self.appstore_url,
                namespaces=['/robot-control'],
                transports=['websocket', 'polling']
            )

            # Keep connection alive (connect handler will send authentication)
            await self.sio.wait()

        except Exception as e:
            self.get_logger().error(f"❌ Connection error: {e}")
            raise

    async def _heartbeat_loop(self):
        """Send periodic heartbeat pings to platform"""
        try:
            while self.authenticated and self.sio.connected:
                self.get_logger().debug("💓 Sending ping_cmd to platform")
                # Send ping with timestamp
                await self.sio.emit('ping_cmd', {
                    't1': time.time()
                }, namespace='/robot-control')
                await asyncio.sleep(30)  # Ping every 30 seconds
        except asyncio.CancelledError:
            self.get_logger().debug("💔 Heartbeat loop cancelled")

    async def send_robot_specification(self):
        """Send robot specification to platform"""
        try:
            if not self.authenticated:
                self.get_logger().warning("⚠️ Not authenticated, skipping robot specification")
                return

            robot_spec = self.specification.copy()
            robot_spec["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")
            robot_spec["robot_id"] = self.robot_id

            self.get_logger().info("📋 Sending robot specification to platform")

            # Send as custom event (platform can listen for this)
            await self.sio.emit('robot_specification', robot_spec, namespace='/robot-control')

        except Exception as e:
            self.get_logger().error(f"❌ Error sending robot specification: {e}")

    async def forward_data(self, data):
        """Override: Forward data to Socket.IO instead of WebSocket"""
        try:
            if self.authenticated and self.sio.connected:
                # Add robot_id to all messages
                data['robot_id'] = self.robot_id

                # Send data to platform via Socket.IO
                event_type = data.get('type', 'robot_data')
                await self.sio.emit(event_type, data)

                self.get_logger().debug(f"📡 Forwarded {event_type} to platform")
        except Exception as e:
            self.get_logger().error(f"❌ Error forwarding data: {e}")

    def is_connected(self):
        """Check if connected and authenticated to platform"""
        return self.authenticated and self.sio.connected

    async def disconnect(self):
        """Disconnect from platform gracefully"""
        try:
            self.get_logger().info("🛑 Disconnecting from platform...")

            # Cancel heartbeat
            if self.heartbeat_task and not self.heartbeat_task.done():
                self.heartbeat_task.cancel()

            # Set remote control status as disconnected
            self.set_remote_control_status(False)

            # Disconnect Socket.IO
            if self.sio.connected:
                await self.sio.disconnect()

            self.get_logger().info("✅ Disconnected from platform")

        except Exception as e:
            self.get_logger().error(f"❌ Error during disconnect: {e}")

    def cleanup_and_exit(self):
        """Cleanup method for graceful shutdown"""
        try:
            self.get_logger().info("🛑 Shutting down platform robot client...")

            # Set remote control status as disconnected
            self.set_remote_control_status(False)

            # Create event loop if needed and disconnect
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(self.disconnect())
                else:
                    loop.run_until_complete(self.disconnect())
            except:
                pass

            # Call parent cleanup
            super().cleanup_and_exit()

            self.get_logger().info("✅ Cleanup completed")

        except Exception as e:
            self.get_logger().error(f"❌ Error during cleanup: {e}")
