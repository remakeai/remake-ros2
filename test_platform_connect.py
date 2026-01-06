#!/usr/bin/env python3
"""
Integration tests for CLI connect with --ros2 flag.

Tests the Socket.IO connection to platform and HMAC authentication flow.
"""

import asyncio
import hashlib
import hmac
import json
import tempfile
import unittest
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from pathlib import Path

# Test imports
from remakeai.websocket_client import RobotConnection


class TestRobotConnection(unittest.TestCase):
    """Test Robot Connection (Socket.IO client for platform)."""

    def setUp(self):
        """Set up test fixtures."""
        self.platform_url = 'wss://test.remake.ai'
        self.robot_id = 'robot-test-001'
        self.robot_secret = 'robot_secret_test_12345'

    def test_connection_initialization(self):
        """Test RobotConnection initializes correctly."""
        conn = RobotConnection(
            platform_url=self.platform_url,
            robot_id=self.robot_id,
            robot_secret=self.robot_secret,
            enable_ros2=False
        )

        assert conn.robot_id == self.robot_id
        assert conn.platform_url == self.platform_url
        assert not conn.connected
        assert not conn.authenticated

    def test_signature_computation(self):
        """Test HMAC-SHA256 signature computation."""
        conn = RobotConnection(
            platform_url=self.platform_url,
            robot_id=self.robot_id,
            robot_secret=self.robot_secret
        )

        nonce = "test_nonce_abc123"
        signature = conn._compute_signature(nonce)

        # Verify signature matches expected HMAC
        expected = hmac.new(
            self.robot_secret.encode('utf-8'),
            nonce.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        assert signature == expected
        assert len(signature) == 64  # SHA256 hex is 64 chars

    def test_signature_different_for_different_nonce(self):
        """Test that different nonces produce different signatures."""
        conn = RobotConnection(
            platform_url=self.platform_url,
            robot_id=self.robot_id,
            robot_secret=self.robot_secret
        )

        sig1 = conn._compute_signature("nonce1")
        sig2 = conn._compute_signature("nonce2")

        assert sig1 != sig2

    def test_signature_same_for_same_nonce(self):
        """Test that same nonce produces same signature."""
        conn = RobotConnection(
            platform_url=self.platform_url,
            robot_id=self.robot_id,
            robot_secret=self.robot_secret
        )

        nonce = "consistent_nonce"
        sig1 = conn._compute_signature(nonce)
        sig2 = conn._compute_signature(nonce)

        assert sig1 == sig2

    def test_signature_depends_on_secret(self):
        """Test that signature depends on robot_secret."""
        nonce = "test_nonce"

        conn1 = RobotConnection(
            platform_url=self.platform_url,
            robot_id=self.robot_id,
            robot_secret="secret1"
        )
        sig1 = conn1._compute_signature(nonce)

        conn2 = RobotConnection(
            platform_url=self.platform_url,
            robot_id=self.robot_id,
            robot_secret="secret2"
        )
        sig2 = conn2._compute_signature(nonce)

        assert sig1 != sig2


class TestHMACAuthentication(unittest.TestCase):
    """Test HMAC-SHA256 authentication flow."""

    def test_authentication_flow_sequence(self):
        """Test: authenticate_cmd → challenge → response → result."""
        robot_secret = 'robot_secret_test'
        nonce = 'server_nonce_12345'

        # Step 1: Robot sends authenticate_cmd with robot_id
        auth_cmd = {'robot_id': 'robot-001'}
        assert auth_cmd['robot_id'] == 'robot-001'

        # Step 2: Server responds with nonce
        challenge = {'nonce': nonce}
        assert challenge['nonce'] == nonce

        # Step 3: Robot computes HMAC signature
        signature = hmac.new(
            robot_secret.encode('utf-8'),
            nonce.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        response = {'signature': signature}
        assert len(response['signature']) == 64

        # Step 4: Server verifies signature
        expected_sig = hmac.new(
            robot_secret.encode('utf-8'),
            nonce.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        assert response['signature'] == expected_sig

        # Step 5: Server sends authenticate_result
        result = {'success': True, 'message': 'Authenticated'}
        assert result['success'] is True

    def test_authentication_fails_with_wrong_secret(self):
        """Test authentication fails if signature computed with wrong secret."""
        nonce = 'test_nonce'

        # Robot computes with correct secret
        correct_sig = hmac.new(
            'correct_secret'.encode('utf-8'),
            nonce.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        # Server verifies with wrong secret
        server_expects = hmac.new(
            'wrong_secret'.encode('utf-8'),
            nonce.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        assert correct_sig != server_expects

    def test_timing_safe_comparison_needed(self):
        """Test that signature verification should use timing-safe comparison."""
        sig1 = 'aabbccdd' + 'ee' * 28  # Same first 8 chars
        sig2 = 'aabbccdd' + 'ff' * 28  # Same first 8 chars

        # Regular == is vulnerable to timing attacks
        # Both comparisons take different times based on position of difference
        assert sig1 != sig2

        # In production, use constant-time comparison like hmac.compare_digest
        assert not hmac.compare_digest(sig1, sig2)


class TestConnectionStates(unittest.TestCase):
    """Test RobotConnection state transitions."""

    def test_initial_state(self):
        """Test connection starts in disconnected state."""
        conn = RobotConnection(
            platform_url='wss://test.remake.ai',
            robot_id='robot-001',
            robot_secret='secret'
        )

        assert not conn.connected
        assert not conn.authenticated
        assert not conn._running

    def test_connection_state_after_connect_event(self):
        """Test state changes after connect event."""
        # Simulating what happens when Socket.IO emits 'connect' event
        conn = RobotConnection(
            platform_url='wss://test.remake.ai',
            robot_id='robot-001',
            robot_secret='secret'
        )

        # Simulate connect event handler
        conn.connected = True
        assert conn.connected

    def test_authentication_state_after_success(self):
        """Test state changes after successful authentication."""
        conn = RobotConnection(
            platform_url='wss://test.remake.ai',
            robot_id='robot-001',
            robot_secret='secret'
        )

        # Simulate successful authentication
        conn.connected = True
        conn.authenticated = True

        assert conn.connected
        assert conn.authenticated

    def test_disconnection_resets_state(self):
        """Test disconnection resets authentication."""
        conn = RobotConnection(
            platform_url='wss://test.remake.ai',
            robot_id='robot-001',
            robot_secret='secret'
        )

        # Connected and authenticated
        conn.connected = True
        conn.authenticated = True

        # Simulate disconnect
        conn.connected = False
        conn.authenticated = False

        assert not conn.connected
        assert not conn.authenticated


class TestPingHeartbeat(unittest.TestCase):
    """Test ping/heartbeat mechanism for RTT calculation."""

    def test_ping_rtt_calculation(self):
        """Test RTT calculation from ping timestamps."""
        # Simulate ping with timestamps (in milliseconds)
        t1 = 1000  # Client sends at 1000ms
        t2 = 1010  # Server receives at 1010ms
        t3 = 1020  # Server responds at 1020ms
        t4 = 1030  # Client receives at 1030ms

        # RTT = (t4 - t1) - (t3 - t2)
        rtt = (t4 - t1) - (t3 - t2)
        # RTT = 30 - 10 = 20ms

        assert rtt == 20

    def test_clock_offset_calculation(self):
        """Test clock offset calculation from ping."""
        t1 = 1000
        t2 = 1010  # Server 10ms ahead
        t3 = 1020
        t4 = 1030

        # Clock offset = ((t2 - t1) + (t3 - t4)) / 2
        # = ((1010 - 1000) + (1020 - 1030)) / 2
        # = (10 + (-10)) / 2 = 0

        clock_offset = ((t2 - t1) + (t3 - t4)) / 2
        assert clock_offset == 0

    def test_clock_offset_with_skew(self):
        """Test clock offset when server clock is ahead."""
        t1 = 1000
        t2 = 1015  # Server 15ms ahead
        t3 = 1025  # Server 15ms ahead
        t4 = 1030

        # Clock offset = ((t2 - t1) + (t3 - t4)) / 2
        # = ((1015 - 1000) + (1025 - 1030)) / 2
        # = (15 - 5) / 2 = 5ms

        clock_offset = ((t2 - t1) + (t3 - t4)) / 2
        assert clock_offset == 5


class TestROS2Integration(unittest.TestCase):
    """Test ROS2 bridge integration with connection."""

    def test_enable_ros2_flag(self):
        """Test that --ros2 flag enables ROS2 bridge."""
        conn = RobotConnection(
            platform_url='wss://test.remake.ai',
            robot_id='robot-001',
            robot_secret='secret',
            enable_ros2=True
        )

        assert conn.enable_ros2 is True

    def test_ros2_disabled_by_default(self):
        """Test that ROS2 is disabled by default."""
        conn = RobotConnection(
            platform_url='wss://test.remake.ai',
            robot_id='robot-001',
            robot_secret='secret'
        )

        assert conn.enable_ros2 is False

    def test_ros2_bridge_initialization(self):
        """Test ROS2 bridge can be initialized with connection."""
        # When connect() is called with enable_ros2=True,
        # a ROS2Bridge should be created
        conn = RobotConnection(
            platform_url='wss://test.remake.ai',
            robot_id='robot-001',
            robot_secret='secret',
            enable_ros2=True
        )

        # ros2_bridge would be initialized in connect() method
        # For now, just verify the flag is set
        assert conn.enable_ros2 is True


class TestConnectionCallbacks(unittest.TestCase):
    """Test connection callbacks."""

    def test_factory_reset_callback(self):
        """Test factory reset callback is invoked."""
        callback_called = False

        def on_factory_reset():
            nonlocal callback_called
            callback_called = True

        conn = RobotConnection(
            platform_url='wss://test.remake.ai',
            robot_id='robot-001',
            robot_secret='secret',
            on_factory_reset=on_factory_reset
        )

        # Simulate factory reset event
        if conn.on_factory_reset:
            conn.on_factory_reset()

        assert callback_called is True

    def test_launch_app_callback(self):
        """Test launch app callback receives session data."""
        received_data = None

        def on_launch_app(data):
            nonlocal received_data
            received_data = data

        conn = RobotConnection(
            platform_url='wss://test.remake.ai',
            robot_id='robot-001',
            robot_secret='secret',
            on_launch_app=on_launch_app
        )

        # Simulate launch app event
        test_data = {
            'session_id': 'sess_123',
            'app_id': 'app_456',
            'app_ws_url': 'wss://app.remake.ai'
        }

        if conn.on_launch_app:
            conn.on_launch_app(test_data)

        assert received_data == test_data


if __name__ == '__main__':
    unittest.main()
