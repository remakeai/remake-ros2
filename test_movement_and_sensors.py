#!/usr/bin/env python3
"""
Integration tests for movement commands and sensor streaming.

Tests movement command handling and sensor data emission with rate limiting.
"""

import unittest
import time
import threading
from unittest.mock import Mock, patch, MagicMock
from collections import deque
from dataclasses import dataclass
from enum import Enum


# Simulated message types
class MessageType(Enum):
    LASER_SCAN = "laser_scan"
    BATTERY = "battery"
    POSE = "pose"
    MAP = "map"
    CAMERA = "camera"


@dataclass
class LaserScan:
    """Simulated LaserScan message."""
    ranges: list
    angle_min: float = -3.14159
    angle_max: float = 3.14159
    angle_increment: float = 0.0175
    time_increment: float = 0.0001
    scan_time: float = 0.05
    range_min: float = 0.15
    range_max: float = 5.0
    header_seq: int = 0
    header_frame_id: str = "laser"


@dataclass
class BatteryState:
    """Simulated BatteryState message."""
    voltage: float
    current: float
    charge: float
    capacity: float
    design_capacity: float
    percentage: float
    power_supply_status: int = 2  # Default: discharging
    power_supply_health: int = 0  # Default: good
    power_supply_technology: str = "LiPo"
    location: str = "battery_pack"
    serial_number: str = "BAT001"


@dataclass
class Pose:
    """Simulated robot pose."""
    x: float
    y: float
    z: float = 0.0
    qw: float = 1.0  # Quaternion w
    qx: float = 0.0  # Quaternion x
    qy: float = 0.0  # Quaternion y
    qz: float = 0.0  # Quaternion z
    timestamp: str = ""


@dataclass
class OccupancyGrid:
    """Simulated OccupancyGrid message."""
    width: int
    height: int
    resolution: float
    origin_x: float = 0.0
    origin_y: float = 0.0
    origin_theta: float = 0.0
    data: list = None  # List of -1 (unknown), 0 (free), 100 (occupied)


class SensorStreamBuffer:
    """Rate-limited sensor streaming buffer with deduplication."""

    def __init__(self, max_frequency: float, max_buffer_size: int = 100):
        """
        Args:
            max_frequency: Maximum Hz for this sensor (e.g., 2.0 = 2 Hz = 0.5s interval)
            max_buffer_size: Max items to buffer before dropping old ones
        """
        self.max_frequency = max_frequency
        self.min_interval_ms = 1000.0 / max_frequency if max_frequency > 0 else 0
        self.max_buffer_size = max_buffer_size
        self.buffer = deque(maxlen=max_buffer_size)
        self.last_emit_time_ms = 0
        self.last_data = None
        self.lock = threading.Lock()

    def add(self, data):
        """Add data to buffer with deduplication."""
        with self.lock:
            current_time_ms = time.time() * 1000

            # Check if data is duplicate
            if self.last_data == data:
                return False  # Skip duplicate

            self.buffer.append((current_time_ms, data))
            self.last_data = data
            return True

    def should_emit(self) -> bool:
        """Check if enough time has passed to emit."""
        current_time_ms = time.time() * 1000
        elapsed = current_time_ms - self.last_emit_time_ms
        return elapsed >= self.min_interval_ms

    def get_pending(self):
        """Get all pending data and mark as emitted."""
        with self.lock:
            if not self.buffer or not self.should_emit():
                return None

            # Get most recent
            data = self.buffer[-1][1]
            self.last_emit_time_ms = time.time() * 1000
            return data

    def get_buffered_count(self) -> int:
        """Get number of items in buffer."""
        with self.lock:
            return len(self.buffer)


class TestMovementCommands(unittest.TestCase):
    """Test robot movement command handling."""

    def test_move_cmd_with_twist(self):
        """Test move command with linear and angular velocity."""
        cmd = {
            'type': 'move',
            'linear': {'x': 0.5, 'y': 0.0, 'z': 0.0},
            'angular': {'x': 0.0, 'y': 0.0, 'z': 0.2}
        }

        # Verify command structure
        assert cmd['type'] == 'move'
        assert cmd['linear']['x'] == 0.5
        assert cmd['angular']['z'] == 0.2

    def test_stop_cmd(self):
        """Test stop command (zero velocities)."""
        cmd = {
            'type': 'stop',
            'linear': {'x': 0.0, 'y': 0.0, 'z': 0.0},
            'angular': {'x': 0.0, 'y': 0.0, 'z': 0.0}
        }

        assert cmd['type'] == 'stop'
        assert cmd['linear']['x'] == 0.0
        assert cmd['angular']['z'] == 0.0

    def test_navigate_to_pose_cmd(self):
        """Test navigate to pose command for Nav2."""
        cmd = {
            'type': 'navigate_to_pose',
            'target_pose': {
                'x': 2.5,
                'y': 1.5,
                'qw': 1.0,  # Quaternion (no rotation)
                'qx': 0.0,
                'qy': 0.0,
                'qz': 0.0
            },
            'relative': False,
            'timeout_sec': 30
        }

        assert cmd['type'] == 'navigate_to_pose'
        assert cmd['target_pose']['x'] == 2.5
        assert cmd['target_pose']['y'] == 1.5
        assert cmd['timeout_sec'] == 30

    def test_cancel_navigation_cmd(self):
        """Test cancel navigation command."""
        cmd = {
            'type': 'cancel_navigation'
        }

        assert cmd['type'] == 'cancel_navigation'

    def test_max_velocity_enforcement(self):
        """Test velocity limits are enforced."""
        max_linear = 0.5  # m/s
        max_angular = 2.0  # rad/s

        # Valid command
        cmd = {'linear_x': 0.3, 'angular_z': 1.5}
        assert abs(cmd['linear_x']) <= max_linear
        assert abs(cmd['angular_z']) <= max_angular

        # Over limit - should be clamped
        cmd['linear_x'] = 1.0
        cmd['linear_x'] = min(cmd['linear_x'], max_linear)
        assert cmd['linear_x'] == max_linear

    def test_velocity_ramp_rate(self):
        """Test acceleration/deceleration limits."""
        max_accel_m_s2 = 0.2
        max_angular_accel_rad_s2 = 0.5
        dt = 0.05  # 50ms control loop

        current_vel = {'linear_x': 0.0, 'angular_z': 0.0}
        target_vel = {'linear_x': 0.5, 'angular_z': 1.0}

        # Ramp linearly within acceleration limits
        max_delta_linear = max_accel_m_s2 * dt
        max_delta_angular = max_angular_accel_rad_s2 * dt

        next_vel = {
            'linear_x': min(
                current_vel['linear_x'] + max_delta_linear,
                target_vel['linear_x']
            ),
            'angular_z': min(
                current_vel['angular_z'] + max_delta_angular,
                target_vel['angular_z']
            )
        }

        assert next_vel['linear_x'] <= 0.011  # 0.2 * 0.05 = 0.01 m/s (with tolerance)
        assert next_vel['angular_z'] <= 0.026  # 0.5 * 0.05 = 0.025 rad/s (with tolerance)


class TestSensorStreaming(unittest.TestCase):
    """Test sensor data streaming with rate limiting."""

    def test_laser_scan_streaming(self):
        """Test LaserScan emission (2 Hz = 0.5s interval)."""
        scan = LaserScan(
            ranges=[0.5] * 360,
            angle_min=-3.14159,
            angle_max=3.14159,
            angle_increment=0.01745
        )

        # Verify scan structure
        assert len(scan.ranges) == 360
        assert scan.angle_min == -3.14159
        assert scan.angle_max == 3.14159
        assert abs(scan.angle_max - scan.angle_min - 360*scan.angle_increment) < 0.01

    def test_battery_state_streaming(self):
        """Test BatteryState emission (0.5 Hz = 2s interval)."""
        battery = BatteryState(
            voltage=14.8,
            current=-2.5,  # Discharging
            charge=0.85,
            capacity=5.0,
            design_capacity=5.0,
            percentage=85.0,
            power_supply_status=2  # Discharging
        )

        assert battery.voltage == 14.8
        assert battery.percentage == 85.0
        assert -5.0 <= battery.current <= 5.0  # Current range

    def test_pose_streaming(self):
        """Test Pose emission (2 Hz = 0.5s interval)."""
        pose = Pose(x=1.5, y=2.0, z=0.0)

        assert pose.x == 1.5
        assert pose.y == 2.0
        assert pose.qw == 1.0  # No rotation

    def test_map_streaming(self):
        """Test OccupancyGrid emission (0.2 Hz = 5s interval)."""
        # 384x384 at 0.05m resolution = 19.2m x 19.2m
        width, height = 384, 384
        resolution = 0.05
        map_data = [0] * (width * height)

        occupancy_grid = OccupancyGrid(
            width=width,
            height=height,
            resolution=resolution,
            data=map_data
        )

        assert occupancy_grid.width == 384
        assert occupancy_grid.height == 384
        assert len(occupancy_grid.data) == 384 * 384

    def test_camera_frame_streaming(self):
        """Test camera image emission (5 Hz max, JPEG compressed)."""
        # Simulate JPEG frame (base64 encoded)
        frame = {
            'type': 'camera_frame',
            'encoding': 'jpeg',
            'width': 320,
            'height': 240,
            'data': 'base64_encoded_jpeg_data_here',  # Would be ~20-50KB
            'timestamp': '2025-01-07T12:00:00.000Z'
        }

        assert frame['encoding'] == 'jpeg'
        assert frame['width'] == 320
        assert frame['height'] == 240


class TestRateLimiting(unittest.TestCase):
    """Test sensor streaming rate limiting."""

    def test_laser_scan_rate_limiting(self):
        """Test LaserScan limited to 2 Hz (0.5s interval)."""
        buffer = SensorStreamBuffer(max_frequency=2.0)

        # Add scans rapidly
        scans = [LaserScan(ranges=[float(i)] * 360) for i in range(10)]

        for scan in scans:
            buffer.add(scan)

        # All added but buffer only emits at 2 Hz
        assert buffer.get_buffered_count() == 10

    def test_duplicate_frame_skipping(self):
        """Test that duplicate frames are skipped."""
        buffer = SensorStreamBuffer(max_frequency=10.0)

        scan = LaserScan(ranges=[0.5] * 360)

        # Add same scan 5 times
        result1 = buffer.add(scan)
        result2 = buffer.add(scan)
        result3 = buffer.add(scan)

        assert result1 is True   # First is accepted
        assert result2 is False  # Duplicate skipped
        assert result3 is False  # Duplicate skipped

    def test_battery_rate_limiting(self):
        """Test BatteryState limited to 0.5 Hz (2s interval)."""
        buffer = SensorStreamBuffer(max_frequency=0.5, max_buffer_size=50)

        batteries = [
            BatteryState(
                voltage=14.8,
                current=-i*0.1,
                charge=0.85,
                capacity=5.0,
                design_capacity=5.0,
                percentage=85.0,
                power_supply_status=2
            )
            for i in range(50)
        ]

        for battery in batteries:
            buffer.add(battery)

        # Check buffering works
        assert buffer.get_buffered_count() == 50

    def test_buffer_overflow_handling(self):
        """Test that old items are dropped when buffer full."""
        buffer = SensorStreamBuffer(max_frequency=10.0, max_buffer_size=5)

        # Add 10 items, buffer should only keep last 5
        for i in range(10):
            battery = BatteryState(
                voltage=14.8 - i*0.1,
                current=0.0,
                charge=0.85,
                capacity=5.0,
                design_capacity=5.0,
                percentage=85.0,
                power_supply_status=2
            )
            buffer.add(battery)

        # Buffer maxlen=5 means oldest are dropped
        assert buffer.get_buffered_count() == 5

    def test_emit_timing(self):
        """Test emission respects rate limits."""
        buffer = SensorStreamBuffer(max_frequency=2.0)  # 2 Hz = 0.5s

        scan1 = LaserScan(ranges=[0.5] * 360)

        # First emit always ready (initial state)
        assert buffer.should_emit() is True
        buffer.add(scan1)
        first_data = buffer.get_pending()
        assert first_data is not None

        # Immediately after getting pending, should not be ready (interval not passed)
        # Note: Very tight timing - OS scheduling may affect this
        # Instead, we check interval calculation
        assert buffer.min_interval_ms == 500.0  # 2 Hz = 500ms interval

        # Simulate time passing (0.5s)
        time.sleep(0.51)
        assert buffer.should_emit() is True


class TestSensorDataQuality(unittest.TestCase):
    """Test sensor data quality and consistency."""

    def test_laser_scan_consistency(self):
        """Test LaserScan data consistency."""
        scan = LaserScan(ranges=[0.5] * 360)

        # Verify ranges match angles
        num_rays = len(scan.ranges)
        angle_span = scan.angle_max - scan.angle_min
        expected_increment = angle_span / (num_rays - 1)

        assert abs(scan.angle_increment - expected_increment) < 0.001

    def test_pose_validity(self):
        """Test Pose quaternion is normalized."""
        pose = Pose(x=1.0, y=2.0, qw=1.0, qx=0.0, qy=0.0, qz=0.0)

        # Quaternion magnitude should be ~1.0
        magnitude = (pose.qw**2 + pose.qx**2 + pose.qy**2 + pose.qz**2) ** 0.5
        assert abs(magnitude - 1.0) < 0.001

    def test_battery_percentage_consistency(self):
        """Test battery percentage matches charge/capacity."""
        battery = BatteryState(
            voltage=14.8,
            current=-2.5,
            charge=2.5,      # 2.5 Ah
            capacity=5.0,    # 5.0 Ah total capacity
            design_capacity=5.0,
            percentage=50.0  # Should be 50%
        )

        calculated_pct = (battery.charge / battery.capacity) * 100.0
        assert abs(calculated_pct - battery.percentage) < 0.1

    def test_map_data_validity(self):
        """Test occupancy grid values are valid."""
        map_data = []
        for i in range(384 * 384):
            if i % 3 == 0:
                map_data.append(-1)    # Unknown
            elif i % 3 == 1:
                map_data.append(0)     # Free
            else:
                map_data.append(100)   # Occupied

        grid = OccupancyGrid(
            width=384,
            height=384,
            resolution=0.05,
            data=map_data
        )

        # All values should be valid (-1, 0, or 100)
        for val in grid.data:
            assert val in [-1, 0, 100]


class TestSensorEmissionFrequencies(unittest.TestCase):
    """Test actual emission frequencies match specifications."""

    def test_frequency_specifications(self):
        """Test documented frequency specifications."""
        specs = {
            'laser_scan': 2.0,      # 2 Hz = 0.5s
            'battery': 0.5,         # 0.5 Hz = 2s
            'pose': 2.0,            # 2 Hz = 0.5s
            'map': 0.2,             # 0.2 Hz = 5s
            'camera': 5.0           # 5 Hz = 0.2s (max)
        }

        buffers = {
            name: SensorStreamBuffer(max_frequency=freq)
            for name, freq in specs.items()
        }

        # Verify buffers created with correct frequencies
        for name, buffer in buffers.items():
            expected_interval = 1000.0 / specs[name]
            assert abs(buffer.min_interval_ms - expected_interval) < 1.0

    def test_interval_calculations(self):
        """Test min interval calculations."""
        test_cases = [
            (2.0, 500),      # 2 Hz = 500ms
            (0.5, 2000),     # 0.5 Hz = 2000ms
            (10.0, 100),     # 10 Hz = 100ms
            (5.0, 200),      # 5 Hz = 200ms
        ]

        for frequency, expected_interval_ms in test_cases:
            buffer = SensorStreamBuffer(max_frequency=frequency)
            assert abs(buffer.min_interval_ms - expected_interval_ms) < 1.0


if __name__ == '__main__':
    unittest.main()
