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
Service Manager - Maps abstract service_cmd requests to ROS2 launch subprocesses.

Reads a services.yaml config that defines how to start/stop each service
for the specific robot. Handles dependency resolution, conflict detection,
and subprocess lifecycle management.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

import yaml

logger = logging.getLogger(__name__)


class ServiceState(Enum):
    """Service lifecycle states."""
    STOPPED = "stopped"
    STARTING = "starting"
    READY = "ready"
    STOPPING = "stopping"
    ERROR = "error"


@dataclass
class ServiceDefinition:
    """A service as defined in services.yaml."""
    name: str
    description: str
    type: str  # "launch" or "run"
    package: str
    launch_file: Optional[str] = None
    executable: Optional[str] = None
    args: Dict[str, str] = field(default_factory=dict)
    depends_on: List[str] = field(default_factory=list)
    conflicts_with: List[str] = field(default_factory=list)
    entitlement: Optional[str] = None
    stop_timeout: int = 10
    provides: Optional[str] = None  # Virtual service this substitutes for


@dataclass
class ServiceInstance:
    """A running service instance."""
    definition: ServiceDefinition
    state: ServiceState = ServiceState.STOPPED
    process: Optional[subprocess.Popen] = None
    started_at: Optional[float] = None
    error_message: Optional[str] = None
    # Who requested this service: directly or as a dependency
    requested_by: Set[str] = field(default_factory=set)
    # Runtime args that override definition args
    runtime_args: Dict[str, str] = field(default_factory=dict)


class ServiceManager:
    """
    Manages ROS2 service subprocesses based on a YAML configuration.

    Usage:
        manager = ServiceManager('/path/to/services.yaml')
        manager.on_service_event = my_callback
        await manager.start_services(['navigation'], params={...})
        await manager.stop_services(['navigation'])
        await manager.shutdown()
    """

    def __init__(
        self,
        config_path: str,
        on_service_event: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        self._config_path = config_path
        self.on_service_event = on_service_event

        # Loaded from YAML
        self._definitions: Dict[str, ServiceDefinition] = {}
        self._maps_config: Dict[str, Any] = {}
        self._robot_config: Dict[str, Any] = {}

        # Simulator definitions (from simulators section)
        self._simulator_definitions: Dict[str, ServiceDefinition] = {}
        self._default_simulator: Optional[str] = None

        # Runtime state
        self._instances: Dict[str, ServiceInstance] = {}
        self._lock = asyncio.Lock()

        # Simulation state
        self._active_simulator: Optional[str] = None
        self._sim_instance: Optional[ServiceInstance] = None

        # Load config
        self._load_config()

    def _load_config(self):
        """Load and parse services.yaml."""
        config_path = Path(self._config_path)
        if not config_path.exists():
            logger.error(f"Services config not found: {config_path}")
            return

        with open(config_path) as f:
            config = yaml.safe_load(f)

        self._robot_config = config.get('robot', {})
        self._maps_config = config.get('maps', {})

        services = config.get('services', {})
        for name, svc in services.items():
            self._definitions[name] = ServiceDefinition(
                name=name,
                description=svc.get('description', ''),
                type=svc.get('type', 'launch'),
                package=svc.get('package', ''),
                launch_file=svc.get('launch_file'),
                executable=svc.get('executable'),
                args=svc.get('args', {}),
                depends_on=svc.get('depends_on', []),
                conflicts_with=svc.get('conflicts_with', []),
                entitlement=svc.get('entitlement'),
                stop_timeout=svc.get('stop_timeout', 10),
            )
            # Initialize instance
            self._instances[name] = ServiceInstance(
                definition=self._definitions[name]
            )

        # Load simulator definitions
        simulators = config.get('simulators', {})
        self._default_simulator = simulators.pop('default', None)
        for name, sim in simulators.items():
            if not isinstance(sim, dict):
                continue
            self._simulator_definitions[name] = ServiceDefinition(
                name=name,
                description=sim.get('description', ''),
                type=sim.get('type', 'launch'),
                package=sim.get('package', ''),
                launch_file=sim.get('launch_file'),
                executable=sim.get('executable'),
                args=sim.get('args', {}),
                depends_on=[],
                conflicts_with=sim.get('conflicts_with', []),
                provides=sim.get('provides'),
                stop_timeout=sim.get('stop_timeout', 15),
            )

        logger.info(
            f"Loaded {len(self._definitions)} service definitions "
            f"and {len(self._simulator_definitions)} simulator definitions "
            f"for robot '{self._robot_config.get('id', 'unknown')}'"
        )

    @property
    def available_services(self) -> List[str]:
        """Get list of available service names."""
        return list(self._definitions.keys())

    @property
    def maps_directory(self) -> str:
        """Get the maps directory path."""
        d = self._maps_config.get('directory', '~/maps')
        return os.path.expanduser(d)

    def get_service_states(self) -> Dict[str, Dict[str, Any]]:
        """Get current state of all services."""
        result = {}
        for name, inst in self._instances.items():
            entry: Dict[str, Any] = {'state': inst.state.value}
            if inst.error_message:
                entry['error'] = inst.error_message
                entry['message'] = inst.error_message
            result[name] = entry
        return result

    def get_service_state(self, name: str) -> Optional[ServiceState]:
        """Get state of a specific service."""
        inst = self._instances.get(name)
        return inst.state if inst else None

    def is_running(self, name: str) -> bool:
        """Check if a service is running (starting or ready)."""
        inst = self._instances.get(name)
        if not inst:
            return False
        return inst.state in (ServiceState.STARTING, ServiceState.READY)

    # =========================================================================
    # Simulation
    # =========================================================================

    @property
    def available_simulators(self) -> List[str]:
        """Get list of available simulator names."""
        return list(self._simulator_definitions.keys())

    @property
    def is_sim_active(self) -> bool:
        """Check if a simulator is currently running."""
        if not self._sim_instance:
            return False
        return self._sim_instance.state in (
            ServiceState.STARTING, ServiceState.READY
        )

    def get_sim_status(self) -> Dict[str, Any]:
        """Get current simulation status."""
        if not self._active_simulator or not self._sim_instance:
            return {
                'active': False,
                'available_simulators': self.available_simulators,
                'default_simulator': self._default_simulator,
            }

        defn = self._simulator_definitions[self._active_simulator]
        result: Dict[str, Any] = {
            'active': True,
            'simulator': self._active_simulator,
            'state': self._sim_instance.state.value,
            'description': defn.description,
            'world': self._sim_instance.runtime_args.get(
                'world', defn.args.get('world', '')
            ),
            'available_simulators': self.available_simulators,
            'default_simulator': self._default_simulator,
        }
        if self._sim_instance.started_at:
            result['uptime_s'] = int(time.time() - self._sim_instance.started_at)
        if self._sim_instance.error_message:
            result['error'] = self._sim_instance.error_message
        return result

    async def start_simulator(
        self,
        name: Optional[str] = None,
        args: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Start a simulator.

        Args:
            name: Simulator name (uses default if not specified).
            args: Override args (e.g. world, headless).

        Returns:
            Response dict with success/error.
        """
        async with self._lock:
            # Resolve simulator name
            sim_name = name or self._default_simulator
            if not sim_name or sim_name not in self._simulator_definitions:
                available = ', '.join(self.available_simulators) or 'none'
                return {
                    'success': False,
                    'error': 'simulator_not_available',
                    'message': (
                        f"Unknown simulator: '{sim_name}'. "
                        f"Available: {available}"
                    ),
                }

            # Check if already running
            if self.is_sim_active:
                if self._active_simulator == sim_name:
                    return {
                        'success': True,
                        'message': f"Simulator '{sim_name}' is already running",
                        'simulator': sim_name,
                    }
                return {
                    'success': False,
                    'error': 'simulator_conflict',
                    'message': (
                        f"Simulator '{self._active_simulator}' is already running. "
                        f"Stop it first."
                    ),
                }

            sim_defn = self._simulator_definitions[sim_name]

            # Check conflicts with running services (e.g. bringup)
            for conflict in sim_defn.conflicts_with:
                if self.is_running(conflict):
                    return {
                        'success': False,
                        'error': 'service_conflict',
                        'message': (
                            f"Cannot start simulator '{sim_name}': "
                            f"service '{conflict}' is running. Stop it first."
                        ),
                    }

            # Create sim instance
            self._active_simulator = sim_name
            self._sim_instance = ServiceInstance(definition=sim_defn)

            # Merge args
            runtime_args = dict(sim_defn.args)
            if args:
                runtime_args.update(args)
            self._sim_instance.runtime_args = runtime_args
            self._sim_instance.requested_by.add('sim')

            # Start the subprocess (reuse existing infrastructure)
            success = await self._start_sim_process()
            if not success:
                error_msg = self._sim_instance.error_message or 'Unknown error'
                self._active_simulator = None
                self._sim_instance = None
                return {
                    'success': False,
                    'error': 'simulator_start_failed',
                    'message': f"Failed to start simulator '{sim_name}': {error_msg}",
                }

            world = runtime_args.get('world', '')
            logger.info(f"Simulator '{sim_name}' started (world: {world})")
            return {
                'success': True,
                'simulator': sim_name,
                'world': world,
            }

    async def stop_simulator(self) -> Dict[str, Any]:
        """Stop the active simulator and all dependent services."""
        async with self._lock:
            if not self.is_sim_active:
                return {
                    'success': True,
                    'message': 'No simulator is running',
                }

            sim_name = self._active_simulator
            sim_defn = self._simulator_definitions[sim_name]

            # First stop all services that depend on what the sim provides
            if sim_defn.provides:
                dependents = [
                    name for name, inst in self._instances.items()
                    if inst.state in (ServiceState.STARTING, ServiceState.READY)
                    and sim_defn.provides in inst.definition.depends_on
                ]
                if dependents:
                    # Use stop order to handle transitive dependencies
                    stop_order = self._resolve_stop_order(dependents)
                    for name in stop_order:
                        await self._stop_service(name)
                    logger.info(
                        f"Stopped dependent services before simulator: "
                        f"{', '.join(stop_order)}"
                    )

            # Stop the simulator process
            await self._stop_sim_process()

            stopped_name = sim_name
            self._active_simulator = None
            self._sim_instance = None

            logger.info(f"Simulator '{stopped_name}' stopped")
            return {
                'success': True,
                'simulator': stopped_name,
            }

    async def _start_sim_process(self) -> bool:
        """Start the simulator subprocess."""
        inst = self._sim_instance
        defn = inst.definition

        inst.state = ServiceState.STARTING
        inst.error_message = None
        self._emit_event('starting', {
            f'sim:{self._active_simulator}': {'state': 'starting'}
        })

        cmd = self._build_command(defn, inst.runtime_args)
        if not cmd:
            inst.state = ServiceState.ERROR
            inst.error_message = "Cannot build command for simulator"
            return False

        logger.info(f"Starting simulator: {' '.join(cmd)}")

        try:
            inst.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                preexec_fn=os.setsid,
            )
            inst.started_at = time.time()

            # Monitor in background
            asyncio.get_event_loop().create_task(
                self._monitor_sim()
            )
            return True

        except Exception as e:
            inst.state = ServiceState.ERROR
            inst.error_message = str(e)
            logger.exception(f"Failed to start simulator")
            return False

    async def _stop_sim_process(self):
        """Stop the simulator subprocess."""
        inst = self._sim_instance
        if not inst or not inst.process or inst.process.poll() is not None:
            if inst:
                inst.state = ServiceState.STOPPED
                inst.process = None
            return

        sim_name = self._active_simulator
        inst.state = ServiceState.STOPPING
        self._emit_event('stopping', {
            f'sim:{sim_name}': {'state': 'stopping'}
        })

        logger.info(f"Stopping simulator '{sim_name}' (PID {inst.process.pid})")

        try:
            pgid = os.getpgid(inst.process.pid)
            os.killpg(pgid, signal.SIGINT)

            timeout = inst.definition.stop_timeout
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None, inst.process.wait, timeout
                )
            except subprocess.TimeoutExpired:
                logger.warning(f"Simulator did not stop within {timeout}s, sending SIGTERM")
                os.killpg(pgid, signal.SIGTERM)
                try:
                    await asyncio.get_event_loop().run_in_executor(
                        None, inst.process.wait, 5
                    )
                except subprocess.TimeoutExpired:
                    logger.warning("Simulator force-killing")
                    os.killpg(pgid, signal.SIGKILL)
                    inst.process.wait(timeout=5)

        except ProcessLookupError:
            pass
        except Exception as e:
            logger.error(f"Error stopping simulator: {e}")

        inst.state = ServiceState.STOPPED
        inst.process = None
        inst.started_at = None
        self._emit_event('stopped', {
            f'sim:{sim_name}': {'state': 'stopped'}
        })

    async def _monitor_sim(self):
        """Monitor simulator subprocess for startup and crashes."""
        inst = self._sim_instance
        if not inst or not inst.process:
            return

        # Gazebo takes longer to start than typical services
        await asyncio.sleep(5.0)

        if not inst.process or inst.process.poll() is not None:
            exit_code = inst.process.returncode if inst.process else -1
            inst.state = ServiceState.ERROR
            inst.error_message = (
                f"Simulator exited during startup with code {exit_code}"
            )
            self._emit_event('error', {
                f'sim:{self._active_simulator}': {
                    'state': 'error',
                    'message': inst.error_message,
                }
            })
            logger.error(f"Simulator failed to start: {inst.error_message}")
            return

        inst.state = ServiceState.READY
        self._emit_event('ready', {
            f'sim:{self._active_simulator}': {'state': 'ready'}
        })
        logger.info(
            f"Simulator '{self._active_simulator}' is ready "
            f"(PID {inst.process.pid})"
        )

        # Continue monitoring for crashes
        while inst.state == ServiceState.READY:
            await asyncio.sleep(2.0)
            if inst.process and inst.process.poll() is not None:
                exit_code = inst.process.returncode
                if inst.state == ServiceState.READY:
                    inst.state = ServiceState.ERROR
                    inst.error_message = (
                        f"Simulator exited unexpectedly with code {exit_code}"
                    )
                    self._emit_event('error', {
                        f'sim:{self._active_simulator}': {
                            'state': 'error',
                            'message': inst.error_message,
                        }
                    })
                    logger.error(f"Simulator crashed (exit code {exit_code})")
                break

    # =========================================================================
    # Service Lifecycle
    # =========================================================================

    async def start_services(
        self,
        services: List[str],
        params: Optional[Dict[str, Dict[str, str]]] = None,
        requester: str = "app",
    ) -> Dict[str, Any]:
        """
        Start requested services and their dependencies.

        Returns a response dict for service_response.
        """
        params = params or {}

        async with self._lock:
            # Validate service names
            unknown = [s for s in services if s not in self._definitions]
            if unknown:
                return {
                    'success': False,
                    'error': 'service_not_available',
                    'message': f"Unknown services: {', '.join(unknown)}",
                }

            # Resolve dependencies (topological order)
            try:
                start_order = self._resolve_start_order(services)
            except ValueError as e:
                return {
                    'success': False,
                    'error': 'dependency_failed',
                    'message': str(e),
                }

            # Check for conflicts
            conflict = self._check_conflicts(start_order)
            if conflict:
                return {
                    'success': False,
                    'error': 'service_conflict',
                    'message': conflict,
                }

            # Start each service in order
            services_affected = []
            for name in start_order:
                inst = self._instances[name]

                if inst.state == ServiceState.READY:
                    # Already running, just track the requester
                    inst.requested_by.add(requester)
                    services_affected.append(name)
                    continue

                if inst.state == ServiceState.STARTING:
                    inst.requested_by.add(requester)
                    services_affected.append(name)
                    continue

                # Merge runtime params
                runtime_args = dict(inst.definition.args)
                if name in params:
                    runtime_args.update(params[name])
                inst.runtime_args = runtime_args

                inst.requested_by.add(requester)

                # Start the subprocess
                success = await self._start_service(name)
                if not success:
                    return {
                        'success': False,
                        'error': 'service_start_failed',
                        'message': f"Failed to start service: {name}",
                    }
                services_affected.append(name)

            return {
                'success': True,
                'services_affected': services_affected,
            }

    async def stop_services(
        self,
        services: List[str],
        requester: str = "app",
    ) -> Dict[str, Any]:
        """Stop requested services."""
        async with self._lock:
            unknown = [s for s in services if s not in self._definitions]
            if unknown:
                return {
                    'success': False,
                    'error': 'service_not_available',
                    'message': f"Unknown services: {', '.join(unknown)}",
                }

            # Determine stop order (reverse dependency - stop dependents first)
            stop_order = self._resolve_stop_order(services)

            services_affected = []
            for name in stop_order:
                inst = self._instances[name]

                # Remove this requester
                inst.requested_by.discard(requester)

                # Only stop if no other requesters
                if inst.requested_by:
                    continue

                if inst.state in (ServiceState.STOPPED, ServiceState.ERROR):
                    continue

                await self._stop_service(name)
                services_affected.append(name)

            return {
                'success': True,
                'services_affected': services_affected,
            }

    async def shutdown(self):
        """Stop all running services and simulator (during node shutdown)."""
        async with self._lock:
            running = [
                name for name, inst in self._instances.items()
                if inst.state in (ServiceState.STARTING, ServiceState.READY)
            ]
            # Stop in reverse dependency order
            stop_order = self._resolve_stop_order(running)
            for name in stop_order:
                await self._stop_service(name)

            # Stop simulator if active
            if self.is_sim_active:
                await self._stop_sim_process()
                self._active_simulator = None
                self._sim_instance = None

            logger.info("All services and simulator stopped")

    # =========================================================================
    # Internal: Subprocess Management
    # =========================================================================

    async def _start_service(self, name: str) -> bool:
        """Start a single service subprocess."""
        inst = self._instances[name]
        defn = inst.definition

        inst.state = ServiceState.STARTING
        inst.error_message = None
        self._emit_event('starting', {name: {'state': 'starting'}})

        # Build the command
        cmd = self._build_command(defn, inst.runtime_args)
        if not cmd:
            inst.state = ServiceState.ERROR
            inst.error_message = f"Cannot build command for service '{name}'"
            self._emit_event('error', {
                name: {
                    'state': 'error',
                    'error': 'invalid_config',
                    'message': inst.error_message,
                }
            })
            return False

        logger.info(f"Starting service '{name}': {' '.join(cmd)}")

        try:
            # Start subprocess
            # Use a new process group so we can signal the entire tree
            inst.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                preexec_fn=os.setsid,
            )
            inst.started_at = time.time()

            # Monitor startup in background
            asyncio.get_event_loop().create_task(
                self._monitor_service(name)
            )

            return True

        except Exception as e:
            inst.state = ServiceState.ERROR
            inst.error_message = str(e)
            self._emit_event('error', {
                name: {
                    'state': 'error',
                    'error': 'service_start_failed',
                    'message': str(e),
                }
            })
            logger.exception(f"Failed to start service '{name}'")
            return False

    async def _stop_service(self, name: str):
        """Stop a single service subprocess."""
        inst = self._instances[name]
        if not inst.process or inst.process.poll() is not None:
            inst.state = ServiceState.STOPPED
            inst.process = None
            return

        inst.state = ServiceState.STOPPING
        self._emit_event('stopping', {name: {'state': 'stopping'}})

        logger.info(f"Stopping service '{name}' (PID {inst.process.pid})")

        try:
            # Send SIGINT to the process group (ROS2 launch handles this gracefully)
            pgid = os.getpgid(inst.process.pid)
            os.killpg(pgid, signal.SIGINT)

            # Wait for graceful shutdown
            timeout = inst.definition.stop_timeout
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None, inst.process.wait, timeout
                )
            except subprocess.TimeoutExpired:
                logger.warning(
                    f"Service '{name}' did not stop within {timeout}s, "
                    f"sending SIGTERM"
                )
                os.killpg(pgid, signal.SIGTERM)
                try:
                    await asyncio.get_event_loop().run_in_executor(
                        None, inst.process.wait, 5
                    )
                except subprocess.TimeoutExpired:
                    logger.warning(f"Service '{name}' force-killing")
                    os.killpg(pgid, signal.SIGKILL)
                    inst.process.wait(timeout=5)

        except ProcessLookupError:
            pass  # Already dead
        except Exception as e:
            logger.error(f"Error stopping service '{name}': {e}")

        inst.state = ServiceState.STOPPED
        inst.process = None
        inst.started_at = None
        inst.error_message = None
        self._emit_event('stopped', {name: {'state': 'stopped'}})
        logger.info(f"Service '{name}' stopped")

    async def _monitor_service(self, name: str):
        """Monitor a service subprocess for startup and crashes."""
        inst = self._instances[name]
        if not inst.process:
            return

        # Give it a few seconds to start, then check if still alive
        await asyncio.sleep(3.0)

        if inst.process.poll() is not None:
            # Process exited during startup
            exit_code = inst.process.returncode
            # Read any output for diagnostics
            output = ""
            if inst.process.stdout:
                try:
                    raw = inst.process.stdout.read(4096)
                    if raw:
                        output = raw.decode('utf-8', errors='replace')
                except Exception:
                    pass

            inst.state = ServiceState.ERROR
            inst.error_message = (
                f"Service exited during startup with code {exit_code}"
            )
            if output:
                inst.error_message += f": {output[:200]}"

            self._emit_event('error', {
                name: {
                    'state': 'error',
                    'error': 'service_crashed',
                    'message': inst.error_message,
                }
            })
            logger.error(f"Service '{name}' failed to start: {inst.error_message}")
            return

        # Service is running - mark as ready
        inst.state = ServiceState.READY
        self._emit_event('ready', {name: {'state': 'ready'}})
        logger.info(f"Service '{name}' is ready (PID {inst.process.pid})")

        # Continue monitoring for crashes
        while inst.state == ServiceState.READY:
            await asyncio.sleep(2.0)
            if inst.process and inst.process.poll() is not None:
                exit_code = inst.process.returncode
                if inst.state == ServiceState.READY:
                    # Unexpected exit
                    inst.state = ServiceState.ERROR
                    inst.error_message = (
                        f"Service exited unexpectedly with code {exit_code}"
                    )
                    self._emit_event('error', {
                        name: {
                            'state': 'error',
                            'error': 'service_crashed',
                            'message': inst.error_message,
                        }
                    })
                    logger.error(
                        f"Service '{name}' crashed (exit code {exit_code})"
                    )
                break

    def _build_command(
        self,
        defn: ServiceDefinition,
        runtime_args: Dict[str, str],
    ) -> Optional[List[str]]:
        """Build the shell command for a service."""
        # When simulation is active, override use_sim_time for all services
        if self.is_sim_active and 'use_sim_time' in runtime_args:
            runtime_args = dict(runtime_args)  # Don't mutate the original
            runtime_args['use_sim_time'] = 'true'

        if defn.type == 'launch':
            if not defn.launch_file:
                return None
            cmd = ['ros2', 'launch', defn.package, defn.launch_file]
            # Add args as key:=value pairs
            for key, value in runtime_args.items():
                # Skip template placeholders that weren't filled
                if '{' in str(value) and '}' in str(value):
                    continue
                cmd.append(f'{key}:={value}')
            return cmd

        elif defn.type == 'run':
            if not defn.executable:
                return None
            cmd = ['ros2', 'run', defn.package, defn.executable]
            for key, value in runtime_args.items():
                if '{' in str(value) and '}' in str(value):
                    continue
                cmd.append(f'--ros-args')
                cmd.append(f'-p')
                cmd.append(f'{key}:={value}')
            return cmd

        return None

    # =========================================================================
    # Internal: Dependency Resolution
    # =========================================================================

    def _resolve_start_order(self, services: List[str]) -> List[str]:
        """
        Resolve dependencies and return topological start order.

        When a simulator is active and provides a service (e.g. bringup),
        that dependency is considered satisfied and skipped.

        Raises ValueError on circular dependencies or missing deps.
        """
        resolved = []

        # Determine which virtual services are provided by the active simulator
        provided_by_sim: Set[str] = set()
        if self.is_sim_active and self._active_simulator:
            sim_defn = self._simulator_definitions[self._active_simulator]
            if sim_defn.provides:
                provided_by_sim.add(sim_defn.provides)

        def visit(name: str, path: Set[str]):
            if name in resolved:
                return
            if name in provided_by_sim and self.is_running(name) is False:
                # This dependency is provided by the active simulator; skip it
                return
            if name in path:
                raise ValueError(
                    f"Circular dependency detected: "
                    f"{' -> '.join(path)} -> {name}"
                )
            if name not in self._definitions:
                # Check if this dep is provided by the active simulator
                if name in provided_by_sim:
                    return
                raise ValueError(f"Unknown dependency: {name}")

            path.add(name)
            for dep in self._definitions[name].depends_on:
                if dep in provided_by_sim:
                    continue  # Satisfied by simulator
                visit(dep, path)
            path.discard(name)

            resolved.append(name)

        for svc in services:
            visit(svc, set())

        return resolved

    def _resolve_stop_order(self, services: List[str]) -> List[str]:
        """
        Determine stop order: services that depend on a service
        being stopped must be stopped first.
        """
        to_stop = set(services)

        # Find dependents that are running and depend on services being stopped
        changed = True
        while changed:
            changed = False
            for name, inst in self._instances.items():
                if name in to_stop:
                    continue
                if inst.state not in (ServiceState.STARTING, ServiceState.READY):
                    continue
                # Check if any of its dependencies are being stopped
                for dep in inst.definition.depends_on:
                    if dep in to_stop:
                        to_stop.add(name)
                        changed = True
                        break

        # Topological sort (reverse of start order)
        start_order = self._resolve_start_order(list(to_stop))
        return list(reversed(start_order))

    def _check_conflicts(self, services: List[str]) -> Optional[str]:
        """
        Check for conflicts between requested services and running services.
        Also checks against the active simulator.

        Returns error message string if conflict found, None otherwise.
        """
        for name in services:
            defn = self._definitions[name]

            # Check against other services being started
            for other in services:
                if other == name:
                    continue
                if other in defn.conflicts_with:
                    return (
                        f"Service '{name}' conflicts with '{other}' "
                        f"(both requested)"
                    )

            # Check against already-running services
            for other_name, inst in self._instances.items():
                if other_name == name:
                    continue
                if other_name in services:
                    continue  # Already checked above
                if not self.is_running(other_name):
                    continue
                if other_name in defn.conflicts_with:
                    return (
                        f"Service '{name}' conflicts with "
                        f"already-running service '{other_name}'"
                    )

            # Check against active simulator
            if self.is_sim_active and self._active_simulator:
                sim_defn = self._simulator_definitions[self._active_simulator]
                if name in sim_defn.conflicts_with:
                    return (
                        f"Service '{name}' conflicts with "
                        f"active simulator '{self._active_simulator}'"
                    )

        return None

    # =========================================================================
    # Event Emission
    # =========================================================================

    def _emit_event(self, event: str, services: Dict[str, Dict[str, Any]]):
        """Emit a service_event."""
        if self.on_service_event:
            self.on_service_event({
                'event': event,
                'services': services,
                'timestamp': int(time.time() * 1000),
            })
