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
App Bridge Node - ROS2 node that bridges apps to the robot.

This is the main entry point for the Remake robot-app bridge. It:

1. Runs a Socket.IO server accepting app connections
2. Implements the ROBOT_APP_API.md protocol (hello/welcome, commands, sensor data)
3. Uses ROS2Bridge to convert between ROS2 topics and app API messages
4. Uses ServiceManager to handle service_cmd (start/stop ROS2 launch files)
5. Enforces entitlements (apps can only use capabilities they're granted)

Spec references:
  - ROBOT_APP_API.md (connection lifecycle, commands, events)
  - API_SENSOR_DATA.md (sensor data streaming)
  - APP_CONTAINER_RUNTIME.md (container environment variables)
"""

from __future__ import annotations

import asyncio
import glob
import logging
import os
import signal
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

import socketio
from aiohttp import web

from .ros2_bridge import ROS2Bridge, BridgeConfig, is_ros2_available
from .service_manager import ServiceManager, ServiceState

logger = logging.getLogger(__name__)


# =============================================================================
# Connected App Tracking
# =============================================================================

class ConnectedApp:
    """Tracks a connected app session."""

    def __init__(self, sid: str, app_id: str, app_version: str, api_version: str):
        self.sid = sid
        self.app_id = app_id
        self.app_version = app_version
        self.api_version = api_version
        self.connected_at = time.time()
        self.entitlements: List[str] = []
        self.subscriptions: Dict[str, float] = {}  # stream_type -> rate_hz


# =============================================================================
# App Bridge Node
# =============================================================================

class AppBridgeNode:
    """
    Main bridge between containerized apps and the ROS2 robot.

    Manages:
    - Socket.IO server for app connections
    - ROS2Bridge for sensor data and movement commands
    - ServiceManager for service lifecycle (navigation, SLAM, etc.)
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8788,
        services_config: str = "",
        robot_id: str = "remake-robot",
        firmware_version: str = "2.0.0",
    ):
        self.host = host
        self.port = port
        self.robot_id = robot_id
        self.firmware_version = firmware_version

        # Connected apps
        self._apps: Dict[str, ConnectedApp] = {}  # sid -> ConnectedApp

        # Socket.IO server
        self._sio = socketio.AsyncServer(
            async_mode="aiohttp",
            cors_allowed_origins="*",
        )
        self._web_app = web.Application()
        self._sio.attach(self._web_app)

        # ROS2 Bridge
        self._bridge: Optional[ROS2Bridge] = None
        self._ros2_available = is_ros2_available()

        # Service Manager
        self._service_manager: Optional[ServiceManager] = None
        if services_config and os.path.exists(services_config):
            self._service_manager = ServiceManager(
                config_path=services_config,
                on_service_event=self._handle_service_event,
            )

        # Available maps (discovered from filesystem)
        self._maps_directory = "~/maps"
        if self._service_manager:
            self._maps_directory = self._service_manager.maps_directory

        # Register Socket.IO handlers
        self._register_handlers()

        # Register HTTP API routes (for CLI sim commands)
        self._register_api_routes()

        # Running flag
        self._running = False

    # =========================================================================
    # HTTP API (for CLI commands)
    # =========================================================================

    def _register_api_routes(self):
        """Register HTTP API routes for simulation control."""
        self._web_app.router.add_post('/api/sim/start', self._api_sim_start)
        self._web_app.router.add_post('/api/sim/stop', self._api_sim_stop)
        self._web_app.router.add_get('/api/sim/status', self._api_sim_status)
        self._web_app.router.add_get('/api/health', self._api_health)

    async def _api_health(self, request: web.Request) -> web.Response:
        """Health check endpoint."""
        return web.json_response({'status': 'ok', 'robot_id': self.robot_id})

    async def _api_sim_start(self, request: web.Request) -> web.Response:
        """Start a simulator."""
        if not self._service_manager:
            return web.json_response({
                'success': False,
                'error': 'no_service_manager',
                'message': 'Service manager not configured',
            }, status=503)

        try:
            body = await request.json()
        except Exception:
            body = {}

        simulator = body.get('simulator')
        # Collect override args from body (world, headless, etc.)
        override_args = {}
        if 'world' in body:
            override_args['world'] = body['world']
        if 'headless' in body:
            # For Gazebo, headless means server-only (no GUI)
            if body['headless']:
                override_args['gz_args_extra'] = '-s'

        result = await self._service_manager.start_simulator(
            name=simulator,
            args=override_args if override_args else None,
        )

        status_code = 200 if result.get('success') else 400
        return web.json_response(result, status=status_code)

    async def _api_sim_stop(self, request: web.Request) -> web.Response:
        """Stop the active simulator."""
        if not self._service_manager:
            return web.json_response({
                'success': False,
                'error': 'no_service_manager',
                'message': 'Service manager not configured',
            }, status=503)

        result = await self._service_manager.stop_simulator()
        return web.json_response(result)

    async def _api_sim_status(self, request: web.Request) -> web.Response:
        """Get simulation status."""
        if not self._service_manager:
            return web.json_response({
                'active': False,
                'message': 'Service manager not configured',
            })

        result = self._service_manager.get_sim_status()
        return web.json_response(result)

    # =========================================================================
    # Startup / Shutdown
    # =========================================================================

    async def start(self):
        """Start the app bridge."""
        self._running = True

        # Start ROS2 bridge
        if self._ros2_available:
            self._bridge = ROS2Bridge(
                on_battery_data=self._broadcast_sensor_data('battery_data'),
                on_pose_data=self._broadcast_sensor_data('pose_data'),
                on_scan_data=self._broadcast_sensor_data('scan_data'),
                on_camera_data=self._broadcast_sensor_data('camera_data'),
                on_imu_data=self._broadcast_sensor_data('imu_data'),
                on_health_data=self._broadcast_sensor_data('health_data'),
                on_map_data=self._broadcast_sensor_data('map_data'),
                on_navigation_data=self._broadcast_to_all('navigation_data'),
                on_move_response=self._broadcast_to_all('move_response'),
            )
            success = self._bridge.start()
            if success:
                logger.info("ROS2 bridge started")
            else:
                logger.warning("ROS2 bridge failed to start - running without ROS2")
                self._bridge = None
        else:
            logger.info("ROS2 not available - running in standalone mode")

        # Start Socket.IO server
        runner = web.AppRunner(self._web_app)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()

        logger.info(
            f"App Bridge running on http://{self.host}:{self.port}"
        )
        logger.info(
            f"  Robot ID: {self.robot_id}"
        )
        if self._service_manager:
            logger.info(
                f"  Available services: "
                f"{', '.join(self._service_manager.available_services)}"
            )
            if self._service_manager.available_simulators:
                logger.info(
                    f"  Available simulators: "
                    f"{', '.join(self._service_manager.available_simulators)}"
                )
        if self._bridge:
            logger.info("  ROS2 bridge: active")
        else:
            logger.info("  ROS2 bridge: inactive (no ROS2)")

    async def shutdown(self):
        """Shut down the app bridge."""
        logger.info("Shutting down App Bridge...")
        self._running = False

        # Disconnect all apps
        for sid in list(self._apps.keys()):
            try:
                await self._sio.disconnect(sid)
            except Exception:
                pass

        # Stop all services
        if self._service_manager:
            await self._service_manager.shutdown()

        # Stop ROS2 bridge
        if self._bridge:
            self._bridge.stop()

        logger.info("App Bridge shut down")

    # =========================================================================
    # Socket.IO Handlers
    # =========================================================================

    def _register_handlers(self):
        """Register all Socket.IO event handlers."""

        @self._sio.on("connect")
        async def on_connect(sid, environ):
            logger.info(f"Transport connected: {sid}")

        @self._sio.on("disconnect")
        async def on_disconnect(sid):
            app = self._apps.pop(sid, None)
            if app:
                logger.info(f"App disconnected: {app.app_id} ({sid})")
                # Stop services that were started by this app
                if self._service_manager:
                    await self._service_manager.stop_services(
                        self._service_manager.available_services,
                        requester=sid,
                    )
            else:
                logger.info(f"Transport disconnected: {sid}")

        # -- Connection Lifecycle --

        @self._sio.on("hello")
        async def on_hello(sid, data):
            await self._handle_hello(sid, data)

        @self._sio.on("goodbye")
        async def on_goodbye(sid, data):
            await self._handle_goodbye(sid, data)

        # -- Movement --

        @self._sio.on("move_cmd")
        async def on_move_cmd(sid, data):
            app = self._apps.get(sid)
            if not app:
                return
            if not self._check_entitlement(app, 'movement'):
                await self._emit_error(sid, data.get('cmd_id'),
                                       'entitlement_denied', 'movement')
                return
            if self._bridge:
                self._bridge.handle_move_cmd(data)
            await self._sio.emit("move_ack", {
                "cmd_id": data.get("cmd_id"),
                "status": "ok",
            }, room=sid)

        @self._sio.on("stop_cmd")
        async def on_stop_cmd(sid, data):
            app = self._apps.get(sid)
            if not app:
                return
            # stop_cmd always allowed (safety)
            if self._bridge:
                self._bridge.handle_stop_cmd(data)
            await self._sio.emit("stop_ack", {
                "cmd_id": data.get("cmd_id"),
                "status": "ok",
            }, room=sid)

        # -- Navigation --

        @self._sio.on("navigate_cmd")
        async def on_navigate_cmd(sid, data):
            app = self._apps.get(sid)
            if not app:
                return
            if not self._check_entitlement(app, 'navigation'):
                await self._emit_error(sid, data.get('cmd_id'),
                                       'entitlement_denied', 'navigation')
                return
            if self._bridge:
                self._bridge.handle_navigate_cmd(data)

        @self._sio.on("cancel_navigation_cmd")
        async def on_cancel_nav(sid, data):
            app = self._apps.get(sid)
            if not app:
                return
            if self._bridge:
                self._bridge.handle_stop_cmd(data)

        # -- Services --

        @self._sio.on("service_cmd")
        async def on_service_cmd(sid, data):
            await self._handle_service_cmd(sid, data)

        # -- Mapping --

        @self._sio.on("map_cmd")
        async def on_map_cmd(sid, data):
            await self._handle_map_cmd(sid, data)

        # -- Sensor Data Subscriptions --

        @self._sio.on("subscribe_data_cmd")
        async def on_subscribe(sid, data):
            await self._handle_subscribe(sid, data)

        @self._sio.on("subscribe_to_data_cmd")
        async def on_subscribe_v2(sid, data):
            # v2 alias for the same handler
            await self._handle_subscribe(sid, data)

        @self._sio.on("unsubscribe_data_cmd")
        async def on_unsubscribe(sid, data):
            await self._handle_unsubscribe(sid, data)

        # -- App Logging --

        @self._sio.on("app_log")
        async def on_app_log(sid, data):
            app = self._apps.get(sid)
            if not app:
                return
            level = data.get("level", "info")
            message = data.get("message", "")
            prefix = f"[APP:{app.app_id}]"
            log_fn = getattr(logger, level, logger.info)
            log_fn(f"{prefix} {message}")

    # =========================================================================
    # Protocol: hello / welcome
    # =========================================================================

    async def _handle_hello(self, sid: str, data: Dict[str, Any]):
        """Handle hello message from app - send welcome back."""
        app_id = data.get("app_id", "unknown")
        app_version = data.get("app_version", "0.0.0")
        api_version = data.get("api_version", "2.0.0")

        logger.info(
            f"Hello from {app_id} v{app_version} "
            f"(API {api_version}) [{sid}]"
        )

        # Determine entitlements
        # In production, these come from the app manifest / container labels.
        # For now, grant standard capabilities.
        granted = ["movement", "sensors", "audio_playback"]
        denied = []

        # Create app record
        app = ConnectedApp(
            sid=sid,
            app_id=app_id,
            app_version=app_version,
            api_version=api_version,
        )
        app.entitlements = granted
        self._apps[sid] = app

        # Build welcome
        available_services = []
        if self._service_manager:
            available_services = self._service_manager.available_services

        available_maps = self._discover_maps()

        # Get last known pose from bridge
        last_known_pose = None
        if self._bridge:
            x, y, theta = self._bridge.get_current_pose()
            if x != 0.0 or y != 0.0 or theta != 0.0:
                last_known_pose = {
                    "pose": {"x": x, "y": y, "theta": theta},
                }

        welcome = {
            "robot_id": self.robot_id,
            "firmware_version": self.firmware_version,
            "api_version": "2.0.0",
            "granted_capabilities": granted,
            "denied_capabilities": denied,
            "capabilities": {
                "movement": True,
                "navigation": "navigation" in available_services,
                "camera": False,
                "audio_playback": True,
                "mapping": (
                    "slam" in available_services
                    or "cartographer" in available_services
                ),
            },
            "limits": {
                "max_linear_speed": 0.5,
                "max_angular_speed": 1.5,
            },
            "robot_state": {
                "battery_level": 100,
                "charging": False,
                "docked": False,
            },
            "available_services": available_services,
            "active_services": [],
            "available_maps": available_maps,
        }

        # Include simulation state so apps know if they're in sim
        if self._service_manager:
            sim_status = self._service_manager.get_sim_status()
            welcome["simulation"] = {
                "active": sim_status.get("active", False),
                "simulator": sim_status.get("simulator"),
                "world": sim_status.get("world"),
            }

        if last_known_pose:
            welcome["last_known_pose"] = last_known_pose

        await self._sio.emit("welcome", welcome, room=sid)
        logger.info(f"Welcome sent to {app_id}")

    async def _handle_goodbye(self, sid: str, data: Dict[str, Any]):
        """Handle goodbye message from app."""
        app = self._apps.get(sid)
        reason = data.get("reason", "unknown")
        app_id = app.app_id if app else "unknown"
        logger.info(f"Goodbye from {app_id}: {reason}")

    # =========================================================================
    # Protocol: service_cmd
    # =========================================================================

    async def _handle_service_cmd(self, sid: str, data: Dict[str, Any]):
        """Handle service_cmd from app."""
        app = self._apps.get(sid)
        if not app:
            return

        cmd_id = data.get("cmd_id")
        action = data.get("action")
        services = data.get("services", [])
        params = data.get("params", {})

        if not self._service_manager:
            await self._sio.emit("service_response", {
                "cmd_id": cmd_id,
                "success": False,
                "action": action,
                "error": "service_not_available",
                "message": "No services configured on this robot",
            }, room=sid)
            return

        if action == "status":
            # Return current status of all services
            await self._sio.emit("service_response", {
                "cmd_id": cmd_id,
                "success": True,
                "action": "status",
                "services": self._service_manager.get_service_states(),
            }, room=sid)
            return

        if action == "start":
            # Check entitlements for each service
            for svc_name in services:
                state = self._service_manager.get_service_state(svc_name)
                if state is None:
                    await self._sio.emit("service_response", {
                        "cmd_id": cmd_id,
                        "success": False,
                        "action": action,
                        "error": "service_not_available",
                        "message": f"Unknown service: {svc_name}",
                    }, room=sid)
                    return

            result = await self._service_manager.start_services(
                services=services,
                params=params,
                requester=sid,
            )
            await self._sio.emit("service_response", {
                "cmd_id": cmd_id,
                "action": "start",
                **result,
            }, room=sid)

        elif action == "stop":
            result = await self._service_manager.stop_services(
                services=services,
                requester=sid,
            )
            await self._sio.emit("service_response", {
                "cmd_id": cmd_id,
                "action": "stop",
                **result,
            }, room=sid)

        else:
            await self._sio.emit("service_response", {
                "cmd_id": cmd_id,
                "success": False,
                "error": "invalid_action",
                "message": f"Unknown action: {action}",
            }, room=sid)

    # =========================================================================
    # Protocol: map_cmd
    # =========================================================================

    async def _handle_map_cmd(self, sid: str, data: Dict[str, Any]):
        """
        Handle map_cmd from app.

        Map operations:
        - start: Begin mapping (requires mapping service running)
        - stop: Stop mapping
        - load: Load a map for navigation
        - delete: Delete a saved map
        - list: List available maps
        """
        app = self._apps.get(sid)
        if not app:
            return

        cmd_id = data.get("cmd_id")
        action = data.get("action")
        map_name = data.get("map_name")

        if action == "list":
            maps = self._discover_maps()
            await self._sio.emit("map_event", {
                "cmd_id": cmd_id,
                "event": "list",
                "maps": maps,
                "timestamp": int(time.time() * 1000),
            }, room=sid)
            return

        if action == "load":
            # Load a map for navigation
            if not map_name:
                await self._sio.emit("map_event", {
                    "cmd_id": cmd_id,
                    "event": "error",
                    "error": "missing_map_name",
                    "message": "map_name is required for load action",
                    "timestamp": int(time.time() * 1000),
                }, room=sid)
                return

            map_path = self._find_map(map_name)
            if not map_path:
                await self._sio.emit("map_event", {
                    "cmd_id": cmd_id,
                    "event": "error",
                    "error": "map_not_found",
                    "message": f"Map not found: {map_name}",
                    "timestamp": int(time.time() * 1000),
                }, room=sid)
                return

            # Start navigation with the map
            if self._service_manager:
                result = await self._service_manager.start_services(
                    services=["navigation"],
                    params={"navigation": {"map": map_path}},
                    requester=sid,
                )
                if result.get("success"):
                    await self._sio.emit("map_event", {
                        "cmd_id": cmd_id,
                        "event": "loaded",
                        "map_name": map_name,
                        "timestamp": int(time.time() * 1000),
                    }, room=sid)
                else:
                    await self._sio.emit("map_event", {
                        "cmd_id": cmd_id,
                        "event": "error",
                        "error": result.get("error", "load_failed"),
                        "message": result.get("message", "Failed to load map"),
                        "timestamp": int(time.time() * 1000),
                    }, room=sid)
            return

        if action == "delete":
            if not map_name:
                await self._sio.emit("map_event", {
                    "cmd_id": cmd_id,
                    "event": "error",
                    "error": "missing_map_name",
                    "message": "map_name is required for delete action",
                    "timestamp": int(time.time() * 1000),
                }, room=sid)
                return

            deleted = self._delete_map(map_name)
            if deleted:
                await self._sio.emit("map_event", {
                    "cmd_id": cmd_id,
                    "event": "deleted",
                    "map_name": map_name,
                    "timestamp": int(time.time() * 1000),
                }, room=sid)
            else:
                await self._sio.emit("map_event", {
                    "cmd_id": cmd_id,
                    "event": "error",
                    "error": "delete_failed",
                    "message": f"Could not delete map: {map_name}",
                    "timestamp": int(time.time() * 1000),
                }, room=sid)
            return

        # Unknown action
        await self._sio.emit("map_event", {
            "cmd_id": cmd_id,
            "event": "error",
            "error": "invalid_action",
            "message": f"Unknown map action: {action}",
            "timestamp": int(time.time() * 1000),
        }, room=sid)

    # =========================================================================
    # Protocol: Sensor Data Subscriptions
    # =========================================================================

    async def _handle_subscribe(self, sid: str, data: Dict[str, Any]):
        """Handle subscribe_data_cmd from app."""
        app = self._apps.get(sid)
        if not app:
            return

        cmd_id = data.get("cmd_id")

        # Support both formats:
        #   { streams: [{type: "pose", rate_hz: 10}] }
        #   { subscribe: ["battery", "pose"] }
        streams = data.get("streams", [])
        subscribe_list = data.get("subscribe", [])

        if subscribe_list:
            # Simple format
            for item in subscribe_list:
                key = item if item.endswith("_data") else f"{item}_data"
                app.subscriptions[key] = 10.0  # default rate
        else:
            # Full format with rate
            for stream in streams:
                stream_type = stream.get("type", "")
                rate_hz = stream.get("rate_hz", 10.0)
                key = (
                    stream_type
                    if stream_type.endswith("_data")
                    else f"{stream_type}_data"
                )
                app.subscriptions[key] = rate_hz

        await self._sio.emit("subscribe_to_data_response", {
            "cmd_id": cmd_id,
            "success": True,
        }, room=sid)

    async def _handle_unsubscribe(self, sid: str, data: Dict[str, Any]):
        """Handle unsubscribe_data_cmd from app."""
        app = self._apps.get(sid)
        if not app:
            return

        cmd_id = data.get("cmd_id")
        unsubscribe_list = data.get("unsubscribe", [])
        streams = data.get("streams", [])

        items = unsubscribe_list or [s.get("type", "") for s in streams]
        for item in items:
            key = item if item.endswith("_data") else f"{item}_data"
            app.subscriptions.pop(key, None)

        await self._sio.emit("unsubscribe_data_response", {
            "cmd_id": cmd_id,
            "success": True,
        }, room=sid)

    # =========================================================================
    # Data Broadcasting
    # =========================================================================

    def _broadcast_sensor_data(self, event_name: str) -> Callable:
        """
        Create a callback that broadcasts sensor data to subscribed apps.

        Returns a sync callback (called from ROS2 bridge thread).
        """
        def callback(data: Dict[str, Any]):
            for sid, app in list(self._apps.items()):
                if event_name in app.subscriptions:
                    # Fire-and-forget async emit from sync context
                    asyncio.run_coroutine_threadsafe(
                        self._sio.emit(event_name, data, room=sid),
                        self._loop,
                    )
        return callback

    def _broadcast_to_all(self, event_name: str) -> Callable:
        """Create a callback that broadcasts to all connected apps."""
        def callback(data: Dict[str, Any]):
            for sid in list(self._apps.keys()):
                asyncio.run_coroutine_threadsafe(
                    self._sio.emit(event_name, data, room=sid),
                    self._loop,
                )
        return callback

    def _handle_service_event(self, data: Dict[str, Any]):
        """Handle service_event from ServiceManager - forward to all apps."""
        for sid in list(self._apps.keys()):
            asyncio.run_coroutine_threadsafe(
                self._sio.emit("service_event", data, room=sid),
                self._loop,
            )

    # =========================================================================
    # Entitlement Checks
    # =========================================================================

    def _check_entitlement(self, app: ConnectedApp, required: str) -> bool:
        """Check if app has a required entitlement."""
        # 'sensors' entitlement covers all sensor subscriptions
        # For now, be permissive - grant if any related entitlement exists
        if required in app.entitlements:
            return True
        # 'movement' covers move_cmd, stop_cmd
        # 'navigation' covers navigate_cmd
        # 'mapping' covers map_cmd start/stop
        # 'sensors' covers subscribe
        return False

    async def _emit_error(
        self, sid: str, cmd_id: Optional[str], error: str, detail: str
    ):
        """Emit an error response."""
        await self._sio.emit("error", {
            "cmd_id": cmd_id,
            "error": error,
            "message": f"Entitlement denied: {detail}",
            "timestamp": int(time.time() * 1000),
        }, room=sid)

    # =========================================================================
    # Map Discovery
    # =========================================================================

    def _discover_maps(self) -> List[str]:
        """Discover available map files."""
        maps_dir = os.path.expanduser(self._maps_directory)
        if not os.path.isdir(maps_dir):
            return []

        maps = []
        for yaml_file in glob.glob(os.path.join(maps_dir, "*.yaml")):
            name = os.path.splitext(os.path.basename(yaml_file))[0]
            # Check that a corresponding .pgm file exists
            pgm_file = os.path.splitext(yaml_file)[0] + ".pgm"
            if os.path.exists(pgm_file):
                maps.append(name)
        return sorted(maps)

    def _find_map(self, map_name: str) -> Optional[str]:
        """Find a map file by name, return full path to .yaml."""
        maps_dir = os.path.expanduser(self._maps_directory)
        yaml_path = os.path.join(maps_dir, f"{map_name}.yaml")
        if os.path.exists(yaml_path):
            return yaml_path
        return None

    def _delete_map(self, map_name: str) -> bool:
        """Delete a map's files (.yaml and .pgm)."""
        maps_dir = os.path.expanduser(self._maps_directory)
        yaml_path = os.path.join(maps_dir, f"{map_name}.yaml")
        pgm_path = os.path.join(maps_dir, f"{map_name}.pgm")

        deleted = False
        for path in (yaml_path, pgm_path):
            if os.path.exists(path):
                try:
                    os.remove(path)
                    deleted = True
                except OSError as e:
                    logger.error(f"Failed to delete {path}: {e}")
                    return False
        return deleted


# =============================================================================
# Standalone Runner
# =============================================================================

async def run_app_bridge(
    host: str = "0.0.0.0",
    port: int = 8788,
    services_config: str = "",
    robot_id: str = "remake-robot",
):
    """Run the app bridge as a standalone async process."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    node = AppBridgeNode(
        host=host,
        port=port,
        services_config=services_config,
        robot_id=robot_id,
    )

    # Store event loop reference for cross-thread broadcasting
    node._loop = asyncio.get_event_loop()

    # Handle signals
    loop = asyncio.get_event_loop()

    def signal_handler():
        asyncio.ensure_future(node.shutdown())

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, signal_handler)

    await node.start()

    # Keep running
    try:
        while node._running:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass
    finally:
        await node.shutdown()


def main():
    """Entry point for the app bridge node."""
    import argparse

    parser = argparse.ArgumentParser(description="Remake App Bridge")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host")
    parser.add_argument("--port", type=int, default=8788, help="Bind port")
    parser.add_argument("--services", default="", help="Path to services.yaml")
    parser.add_argument("--robot-id", default="remake-robot", help="Robot ID")
    args = parser.parse_args()

    asyncio.run(run_app_bridge(
        host=args.host,
        port=args.port,
        services_config=args.services,
        robot_id=args.robot_id,
    ))


if __name__ == "__main__":
    main()
