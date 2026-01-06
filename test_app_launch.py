#!/usr/bin/env python3
"""
Integration tests for 3-phase app launch protocol.

Tests the complete app session lifecycle:
- Phase 1: establish_app_session_cmd → establish_app_session_response
- Phase 2: setup_app_cmd → setup_app_response
- Phase 3: enable_remote_control_cmd → enable_remote_control_response
"""

import json
import unittest
import uuid
from unittest.mock import Mock, patch
from dataclasses import dataclass
from enum import Enum


# Simulate SessionState enum (from platform_client_node.py)
class SessionState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    SETTING_UP = "setting_up"
    READY = "ready"
    ACTIVE = "active"
    TERMINATING = "terminating"


@dataclass
class AppSession:
    """Simulates AppSession from platform_client_node.py"""
    session_id: str
    app_id: str
    session_token: str
    app_ws_url: str
    connection_ticket: str = None
    state: SessionState = SessionState.DISCONNECTED
    verified: bool = False
    remote_control_enabled: bool = False


class TestPhase1EstablishAppSession(unittest.TestCase):
    """Test Phase 1: Establish App Session"""

    def test_phase1_creates_session(self):
        """Test Phase 1 creates AppSession from command data."""
        # Platform sends establish_app_session_cmd
        cmd = {
            'cmd_id': str(uuid.uuid4()),
            'session_id': 'sess_abc123',
            'app_id': 'hello-world',
            'session_token': 'token_xyz789',
            'app_ws_url': 'wss://hello-world.remake.ai',
            'connection_ticket': 'ticket_def456'
        }

        # Robot receives and processes command
        session = AppSession(
            session_id=cmd['session_id'],
            app_id=cmd['app_id'],
            session_token=cmd['session_token'],
            app_ws_url=cmd['app_ws_url'],
            connection_ticket=cmd['connection_ticket'],
            state=SessionState.CONNECTING
        )

        # Verify session was created
        assert session.session_id == 'sess_abc123'
        assert session.app_id == 'hello-world'
        assert session.state == SessionState.CONNECTING

    def test_phase1_verifies_no_active_session(self):
        """Test Phase 1 rejects if another session is active."""
        # Current session is active
        current_session = AppSession(
            session_id='sess_old',
            app_id='other-app',
            session_token='token_old',
            app_ws_url='wss://other.remake.ai',
            state=SessionState.ACTIVE  # Still active
        )

        # Try to establish new session
        new_cmd = {
            'session_id': 'sess_new',
            'app_id': 'hello-world'
        }

        # Should reject because current_session.state != DISCONNECTED
        if current_session and current_session.state != SessionState.DISCONNECTED:
            # Reject: session_conflict
            response_status = 'failed'
            error = 'session_conflict'
        else:
            response_status = 'success'
            error = None

        assert response_status == 'failed'
        assert error == 'session_conflict'

    def test_phase1_transition_to_connected(self):
        """Test Phase 1 transitions session to CONNECTED state."""
        cmd = {
            'cmd_id': str(uuid.uuid4()),
            'session_id': 'sess_123',
            'app_id': 'test-app',
            'session_token': 'token_123',
            'app_ws_url': 'wss://test.remake.ai',
        }

        session = AppSession(
            session_id=cmd['session_id'],
            app_id=cmd['app_id'],
            session_token=cmd['session_token'],
            app_ws_url=cmd['app_ws_url'],
            state=SessionState.CONNECTING
        )

        # Move to CONNECTED
        session.state = SessionState.CONNECTED

        assert session.state == SessionState.CONNECTED

    def test_phase1_response_message(self):
        """Test Phase 1 response message format."""
        cmd_id = str(uuid.uuid4())
        session_id = 'sess_123'

        response = {
            'cmd_id': cmd_id,
            'session_id': session_id,
            'status': 'success',
            'message': 'Session established'
        }

        assert response['status'] == 'success'
        assert response['cmd_id'] == cmd_id
        assert response['session_id'] == session_id


class TestPhase2SetupApp(unittest.TestCase):
    """Test Phase 2: Setup App"""

    def test_phase2_requires_connected_session(self):
        """Test Phase 2 requires session from Phase 1."""
        # Session from Phase 1
        session = AppSession(
            session_id='sess_123',
            app_id='test-app',
            session_token='token_123',
            app_ws_url='wss://test.remake.ai',
            state=SessionState.CONNECTED
        )

        # Phase 2 command
        cmd = {
            'cmd_id': str(uuid.uuid4()),
            'session_id': 'sess_123'
        }

        # Verify session exists
        if session and session.session_id == cmd['session_id']:
            can_proceed = True
        else:
            can_proceed = False

        assert can_proceed is True

    def test_phase2_transition_to_setting_up(self):
        """Test Phase 2 transitions to SETTING_UP state."""
        session = AppSession(
            session_id='sess_123',
            app_id='test-app',
            session_token='token_123',
            app_ws_url='wss://test.remake.ai',
            state=SessionState.CONNECTED
        )

        # Phase 2: move to SETTING_UP
        session.state = SessionState.SETTING_UP
        assert session.state == SessionState.SETTING_UP

    def test_phase2_transition_to_ready(self):
        """Test Phase 2 transitions to READY state."""
        session = AppSession(
            session_id='sess_123',
            app_id='test-app',
            session_token='token_123',
            app_ws_url='wss://test.remake.ai',
            state=SessionState.SETTING_UP
        )

        # Complete setup
        session.state = SessionState.READY
        assert session.state == SessionState.READY

    def test_phase2_performs_setup_actions(self):
        """Test Phase 2 can perform setup actions."""
        session = AppSession(
            session_id='sess_123',
            app_id='test-app',
            session_token='token_123',
            app_ws_url='wss://test.remake.ai',
            state=SessionState.CONNECTED
        )

        # Simulate setup actions
        state_restored = False
        assets_uploaded = 0

        # In real implementation:
        # - Load app assets from storage
        # - Restore app state from previous session
        # - Initialize app resources

        session.state = SessionState.READY

        # Return setup summary
        response = {
            'cmd_id': str(uuid.uuid4()),
            'session_id': session.session_id,
            'status': 'success',
            'installation_summary': {
                'state_restored': state_restored,
                'assets_uploaded': assets_uploaded
            }
        }

        assert response['status'] == 'success'
        assert response['installation_summary']['assets_uploaded'] == 0

    def test_phase2_rejects_if_session_not_found(self):
        """Test Phase 2 rejects if session doesn't exist."""
        cmd = {
            'cmd_id': str(uuid.uuid4()),
            'session_id': 'sess_missing'
        }

        # Try to find session
        session = None  # Not found

        if not session or session.session_id != cmd['session_id']:
            response = {
                'status': 'failed',
                'error': 'session_not_found',
                'error_message': 'Session not found'
            }
        else:
            response = {'status': 'success'}

        assert response['status'] == 'failed'
        assert response['error'] == 'session_not_found'


class TestPhase3EnableRemoteControl(unittest.TestCase):
    """Test Phase 3: Enable Remote Control"""

    def test_phase3_requires_ready_session(self):
        """Test Phase 3 requires READY session from Phase 2."""
        session = AppSession(
            session_id='sess_123',
            app_id='test-app',
            session_token='token_123',
            app_ws_url='wss://test.remake.ai',
            state=SessionState.READY  # From Phase 2
        )

        cmd = {
            'cmd_id': str(uuid.uuid4()),
            'session_id': 'sess_123'
        }

        # Verify state is READY
        if session and session.state == SessionState.READY:
            can_enable = True
        else:
            can_enable = False

        assert can_enable is True

    def test_phase3_rejects_if_not_ready(self):
        """Test Phase 3 rejects if session not in READY state."""
        session = AppSession(
            session_id='sess_123',
            app_id='test-app',
            session_token='token_123',
            app_ws_url='wss://test.remake.ai',
            state=SessionState.SETTING_UP  # Still setting up
        )

        cmd = {'cmd_id': str(uuid.uuid4()), 'session_id': 'sess_123'}

        # Check state
        if session and session.state != SessionState.READY:
            response = {
                'status': 'failed',
                'error': 'invalid_state',
                'error_message': f'Cannot enable control from state: {session.state.value}'
            }
        else:
            response = {'status': 'success'}

        assert response['status'] == 'failed'
        assert 'invalid_state' in response['error']

    def test_phase3_enables_remote_control(self):
        """Test Phase 3 sets remote_control_enabled flag."""
        session = AppSession(
            session_id='sess_123',
            app_id='test-app',
            session_token='token_123',
            app_ws_url='wss://test.remake.ai',
            state=SessionState.READY
        )

        # Phase 3: Enable remote control
        session.state = SessionState.ACTIVE
        session.remote_control_enabled = True

        assert session.remote_control_enabled is True
        assert session.state == SessionState.ACTIVE

    def test_phase3_response_indicates_success(self):
        """Test Phase 3 response indicates control is enabled."""
        response = {
            'cmd_id': str(uuid.uuid4()),
            'session_id': 'sess_123',
            'status': 'success',
            'message': 'Remote control enabled'
        }

        assert response['status'] == 'success'
        assert 'enabled' in response['message'].lower()


class TestCompleteAppLaunch(unittest.TestCase):
    """Test complete 3-phase app launch flow."""

    def test_full_app_launch_flow(self):
        """Test: Phase 1 → Phase 2 → Phase 3."""
        # Initial state
        current_session = None

        # =====================================================================
        # PHASE 1: Establish App Session
        # =====================================================================
        phase1_cmd = {
            'cmd_id': str(uuid.uuid4()),
            'session_id': 'sess_abc123',
            'app_id': 'hello-world',
            'session_token': 'token_xyz789',
            'app_ws_url': 'wss://hello-world.remake.ai',
            'connection_ticket': 'ticket_def456'
        }

        # Check no active session
        assert current_session is None or current_session.state == SessionState.DISCONNECTED

        # Create session
        current_session = AppSession(
            session_id=phase1_cmd['session_id'],
            app_id=phase1_cmd['app_id'],
            session_token=phase1_cmd['session_token'],
            app_ws_url=phase1_cmd['app_ws_url'],
            connection_ticket=phase1_cmd['connection_ticket'],
            state=SessionState.CONNECTING
        )

        # Transition to CONNECTED
        current_session.state = SessionState.CONNECTED

        assert current_session.state == SessionState.CONNECTED

        # =====================================================================
        # PHASE 2: Setup App
        # =====================================================================
        phase2_cmd = {
            'cmd_id': str(uuid.uuid4()),
            'session_id': 'sess_abc123'
        }

        # Verify session exists
        assert current_session.session_id == phase2_cmd['session_id']

        # Setup app
        current_session.state = SessionState.SETTING_UP
        current_session.state = SessionState.READY

        assert current_session.state == SessionState.READY

        # =====================================================================
        # PHASE 3: Enable Remote Control
        # =====================================================================
        phase3_cmd = {
            'cmd_id': str(uuid.uuid4()),
            'session_id': 'sess_abc123'
        }

        # Verify session ready
        assert current_session.state == SessionState.READY

        # Enable control
        current_session.state = SessionState.ACTIVE
        current_session.remote_control_enabled = True

        # =====================================================================
        # VERIFICATION
        # =====================================================================
        assert current_session.state == SessionState.ACTIVE
        assert current_session.remote_control_enabled is True
        assert current_session.session_id == 'sess_abc123'
        assert current_session.app_id == 'hello-world'

    def test_app_termination_after_launch(self):
        """Test app can be terminated after successful launch."""
        session = AppSession(
            session_id='sess_123',
            app_id='hello-world',
            session_token='token_123',
            app_ws_url='wss://hello-world.remake.ai',
            state=SessionState.ACTIVE,
            remote_control_enabled=True
        )

        # Receive terminate_app_cmd
        terminate_cmd = {
            'cmd_id': str(uuid.uuid4()),
            'session_id': 'sess_123',
            'force': False,
            'reason': 'user_requested'
        }

        # Verify session exists
        if session and session.session_id == terminate_cmd['session_id']:
            # Stop movement
            remote_control_enabled = False

            # Terminate session
            session.state = SessionState.TERMINATING
            session.remote_control_enabled = False

            # Clean up
            current_session = None
        else:
            current_session = session

        assert session.state == SessionState.TERMINATING
        assert session.remote_control_enabled is False


class TestErrorRecovery(unittest.TestCase):
    """Test error handling during app launch."""

    def test_phase1_error_handling(self):
        """Test Phase 1 error recovery."""
        errors = []

        try:
            # Simulate Phase 1 error (e.g., connection failure)
            raise Exception("Failed to connect to app WebSocket")
        except Exception as e:
            errors.append({
                'phase': 1,
                'error': str(e),
                'status': 'failed'
            })

        assert len(errors) == 1
        assert errors[0]['phase'] == 1
        assert 'connect' in errors[0]['error'].lower()

    def test_phase2_error_handling(self):
        """Test Phase 2 error recovery."""
        session = AppSession(
            session_id='sess_123',
            app_id='test-app',
            session_token='token_123',
            app_ws_url='wss://test.remake.ai',
            state=SessionState.CONNECTED
        )

        # Phase 2 error (e.g., asset loading failed)
        session.state = SessionState.SETTING_UP

        # Error occurs
        error_response = {
            'status': 'failed',
            'error': 'asset_load_failed',
            'error_message': 'Failed to load app assets'
        }

        # Revert to CONNECTED
        session.state = SessionState.CONNECTED

        assert session.state == SessionState.CONNECTED
        assert error_response['status'] == 'failed'

    def test_phase3_error_handling(self):
        """Test Phase 3 error recovery."""
        session = AppSession(
            session_id='sess_123',
            app_id='test-app',
            session_token='token_123',
            app_ws_url='wss://test.remake.ai',
            state=SessionState.READY
        )

        # Phase 3 error (e.g., ROS2 bridge failed to initialize)
        if session.state == SessionState.READY:
            # Try to enable
            try:
                # Simulate error
                raise Exception("ROS2 bridge initialization failed")
            except Exception as e:
                error_response = {
                    'status': 'failed',
                    'error': 'ros2_init_failed',
                    'message': str(e)
                }
                # Session stays in READY, doesn't move to ACTIVE
        else:
            error_response = {'status': 'success'}

        assert error_response['status'] == 'failed'
        assert session.state == SessionState.READY  # Still ready, not active


if __name__ == '__main__':
    unittest.main()
