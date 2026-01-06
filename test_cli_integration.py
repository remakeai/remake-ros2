#!/usr/bin/env python3
"""
Integration tests for CLI login and pair commands.

Tests the basic authentication flow without requiring a real platform.
"""

import os
import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent))

from remakeai.cli_config import (
    load_config, get_auth_token, get_auth, set_auth, clear_auth, is_authenticated,
    get_robots, add_robot, remove_robot, clear_robots, get_robot,
    get_platform_url, set_platform_url, get_websocket_url,
    get_setting, set_setting, get_all_settings, reset_settings,
    DEFAULT_SETTINGS
)


class TestCLIAuth(unittest.TestCase):
    """Test CLI authentication and credential storage."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_config_dir = tempfile.mkdtemp()
        os.environ['HOME'] = self.test_config_dir
        os.environ['USERPROFILE'] = self.test_config_dir
        clear_auth()
        clear_robots()

    def tearDown(self):
        """Clean up test fixtures."""
        clear_auth()
        clear_robots()

    def test_login_saves_token(self):
        """Test that login saves authentication token."""
        token = "cli_test_token_12345"
        set_auth(
            token=token,
            email="test@example.com",
            expires_at="2025-01-08T12:00:00Z"
        )

        # Verify token was saved
        assert is_authenticated()
        assert get_auth_token() == token

    def test_login_saves_email(self):
        """Test that login saves user email."""
        set_auth(
            token="test_token",
            email="test@example.com"
        )

        config = load_config()
        assert config.get('auth', {}).get('email') == "test@example.com"

    def test_logout_clears_credentials(self):
        """Test that logout clears stored credentials."""
        set_auth(token="test_token", email="test@example.com")
        assert is_authenticated()

        clear_auth()
        assert not is_authenticated()
        assert get_auth_token() is None

    def test_multiple_login_overwrites(self):
        """Test that logging in with different account overwrites credentials."""
        set_auth(token="token1", email="user1@example.com")
        assert get_auth_token() == "token1"

        set_auth(token="token2", email="user2@example.com")
        assert get_auth_token() == "token2"

        config = load_config()
        assert config.get('auth', {}).get('email') == "user2@example.com"


class TestCLIPairing(unittest.TestCase):
    """Test CLI robot pairing."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_config_dir = tempfile.mkdtemp()
        os.environ['HOME'] = self.test_config_dir
        os.environ['USERPROFILE'] = self.test_config_dir
        clear_robots()

    def tearDown(self):
        """Clean up test fixtures."""
        clear_robots()

    def test_pair_saves_robot(self):
        """Test that pairing saves robot to local config."""
        robot_data = {
            'id': 'robot-test-001',
            'name': 'Test Robot',
            'secret': 'robot_secret_abc123',
            'device_id': '00:11:22:33:44:55',
            'product_id': 'vacuum_pro'
        }

        add_robot(robot_data)

        # Verify robot was saved
        saved_robot = get_robot(robot_id='robot-test-001')
        assert saved_robot is not None
        assert saved_robot['id'] == 'robot-test-001'
        assert saved_robot['name'] == 'Test Robot'
        assert saved_robot['secret'] == 'robot_secret_abc123'

    def test_get_robots_returns_list(self):
        """Test that get_robots returns list of paired robots."""
        # Add multiple robots
        add_robot({
            'id': 'robot-001',
            'name': 'Robot 1',
            'secret': 'secret1'
        })
        add_robot({
            'id': 'robot-002',
            'name': 'Robot 2',
            'secret': 'secret2'
        })

        robots = get_robots()
        assert len(robots) == 2
        assert robots[0]['id'] == 'robot-001'
        assert robots[1]['id'] == 'robot-002'

    def test_get_robot_by_name(self):
        """Test retrieving robot by name."""
        add_robot({
            'id': 'robot-test-001',
            'name': 'MyRobot',
            'secret': 'secret123'
        })

        robot = get_robot(name='MyRobot')
        assert robot is not None
        assert robot['id'] == 'robot-test-001'

    def test_remove_robot(self):
        """Test removing a paired robot."""
        add_robot({
            'id': 'robot-test-001',
            'name': 'Test Robot',
            'secret': 'secret123'
        })

        assert len(get_robots()) == 1

        remove_robot(robot_id='robot-test-001')
        assert len(get_robots()) == 0

    def test_clear_all_robots(self):
        """Test clearing all paired robots."""
        add_robot({'id': 'robot-001', 'name': 'Robot 1', 'secret': 's1'})
        add_robot({'id': 'robot-002', 'name': 'Robot 2', 'secret': 's2'})

        assert len(get_robots()) == 2

        clear_robots()
        assert len(get_robots()) == 0


class TestCLIConfig(unittest.TestCase):
    """Test CLI configuration management."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_config_dir = tempfile.mkdtemp()
        os.environ['HOME'] = self.test_config_dir
        os.environ['USERPROFILE'] = self.test_config_dir
        reset_settings()

    def tearDown(self):
        """Clean up test fixtures."""
        reset_settings()

    def test_get_default_settings(self):
        """Test that default settings are available."""
        settings = get_all_settings()
        assert settings.get('platform_url') is not None
        assert settings.get('asset_quota_mb') is not None

    def test_set_and_get_setting(self):
        """Test setting and retrieving a configuration value."""
        set_setting('asset_quota_mb', '500')
        value = get_setting('asset_quota_mb')
        assert value == 500  # Correctly stored as integer

    def test_platform_url_configuration(self):
        """Test setting platform URL."""
        test_url = 'https://custom.remake.ai'
        set_platform_url(test_url)

        assert get_platform_url() == test_url

    def test_websocket_url_generation(self):
        """Test WebSocket URL is generated from platform URL."""
        set_platform_url('https://apps.remake.ai')
        ws_url = get_websocket_url()

        assert ws_url.startswith('wss://')
        assert 'apps.remake.ai' in ws_url


class TestCLIStatus(unittest.TestCase):
    """Test CLI status command."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_config_dir = tempfile.mkdtemp()
        os.environ['HOME'] = self.test_config_dir
        os.environ['USERPROFILE'] = self.test_config_dir
        clear_auth()
        clear_robots()

    def tearDown(self):
        """Clean up test fixtures."""
        clear_auth()
        clear_robots()

    def test_status_shows_authentication(self):
        """Test that status shows authentication state."""
        # Not authenticated
        assert not is_authenticated()

        # After login
        set_auth(token='test_token', email='test@example.com')
        assert is_authenticated()

    def test_status_shows_paired_robots(self):
        """Test that status shows paired robots."""
        # No robots
        assert len(get_robots()) == 0

        # After pairing
        add_robot({
            'id': 'robot-test-001',
            'name': 'Test Robot',
            'secret': 'secret123'
        })
        assert len(get_robots()) == 1


class TestAuthFlow(unittest.TestCase):
    """Test complete authentication flow: login → pair → connect."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_config_dir = tempfile.mkdtemp()
        os.environ['HOME'] = self.test_config_dir
        os.environ['USERPROFILE'] = self.test_config_dir
        clear_auth()
        clear_robots()

    def tearDown(self):
        """Clean up test fixtures."""
        clear_auth()
        clear_robots()

    def test_complete_auth_flow(self):
        """Test: login → pair → verify ready for connect."""
        # Step 1: Login
        set_auth(
            token='cli_abc123def456',
            email='user@example.com'
        )
        assert is_authenticated()
        assert get_auth_token() == 'cli_abc123def456'

        # Step 2: Pair robot
        add_robot({
            'id': 'robot-home-001',
            'name': 'Living Room Bot',
            'secret': 'robot_secret_xyz789',
            'device_id': '00:11:22:33:44:55',
            'product_id': 'home_vacuum'
        })
        robots = get_robots()
        assert len(robots) == 1

        # Step 3: Verify ready for connect
        robot = get_robot(name='Living Room Bot')
        assert robot is not None
        assert robot['secret'] is not None  # Robot secret available
        assert get_auth_token() is not None  # Auth token available

        # Ready to call: remake connect --robot-name "Living Room Bot"

    def test_multi_robot_scenario(self):
        """Test: login with multiple robots paired."""
        set_auth(token='cli_token_123', email='user@example.com')

        # Pair multiple robots
        add_robot({'id': 'r1', 'name': 'Kitchen', 'secret': 's1'})
        add_robot({'id': 'r2', 'name': 'Bedroom', 'secret': 's2'})
        add_robot({'id': 'r3', 'name': 'Garage', 'secret': 's3'})

        robots = get_robots()
        assert len(robots) == 3

        # Can select any robot
        assert get_robot(name='Kitchen')['id'] == 'r1'
        assert get_robot(name='Bedroom')['id'] == 'r2'
        assert get_robot(name='Garage')['id'] == 'r3'


if __name__ == '__main__':
    unittest.main()
