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
Unit tests for ChatMixin functionality.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from kaiaai.chat_mixin import ChatMixin


class MockTransport:
    """Mock transport for testing."""
    def __init__(self):
        self.send_message = AsyncMock()
        self.sent_messages = []

    async def send_message(self, message):
        self.sent_messages.append(message)


class TestChatApp(ChatMixin):
    """Test app that uses ChatMixin."""
    def __init__(self):
        self.transport = MockTransport()
        self.message_callbacks = {}
        self.latest_messages = {}
        super().__init__()

    def register_message_type(self, message_type):
        """Mock implementation."""
        if message_type not in self.message_callbacks:
            self.message_callbacks[message_type] = []

    def add_message_callback(self, message_type, callback):
        """Mock implementation."""
        if message_type not in self.message_callbacks:
            self.message_callbacks[message_type] = []
        self.message_callbacks[message_type].append(callback)


class TestChatMixin:
    """Test suite for ChatMixin."""

    @pytest.mark.asyncio
    async def test_ask_user_simple_options(self):
        """Test asking user with simple string options."""
        app = TestChatApp()

        # Simulate user response after 0.1 seconds
        async def simulate_response():
            await asyncio.sleep(0.1)
            # Get the message_id from the sent message
            sent_msg = app.transport.sent_messages[0]
            await app._handle_user_response({
                'message_id': sent_msg['message_id'],
                'selected_option_id': 'opt_1',
                'selected_option_label': 'Option B',
                'is_auto_selected': False
            })

        # Start response simulation
        asyncio.create_task(simulate_response())

        # Ask question
        response = await app.ask_user(
            question="Choose an option:",
            options=["Option A", "Option B", "Option C"],
            timeout=5
        )

        assert response == "Option B"
        assert len(app.transport.sent_messages) == 1
        msg = app.transport.sent_messages[0]
        assert msg['type'] == 'robot_question'
        assert msg['content'] == "Choose an option:"
        assert len(msg['options']) == 3
        assert msg['options'][1]['label'] == "Option B"

    @pytest.mark.asyncio
    async def test_ask_user_structured_options(self):
        """Test asking user with structured dict options."""
        app = TestChatApp()

        async def simulate_response():
            await asyncio.sleep(0.1)
            sent_msg = app.transport.sent_messages[0]
            await app._handle_user_response({
                'message_id': sent_msg['message_id'],
                'selected_option_id': 'manual',
                'selected_option_label': 'Manual Control',
                'is_auto_selected': False
            })

        asyncio.create_task(simulate_response())

        response = await app.ask_user(
            question="Select mode:",
            options=[
                {"id": "auto", "label": "Autonomous"},
                {"id": "manual", "label": "Manual Control"}
            ],
            timeout=5
        )

        assert response == "Manual Control"
        msg = app.transport.sent_messages[0]
        assert msg['options'][1]['id'] == 'manual'

    @pytest.mark.asyncio
    async def test_ask_user_timeout(self):
        """Test timeout behavior with default option."""
        app = TestChatApp()

        # Don't send any response, let it timeout
        response = await app.ask_user(
            question="Will timeout:",
            options=["Option A", "Option B"],
            timeout=0.2,  # Very short timeout for testing
            default="Option B"
        )

        # Should return the default
        assert response == "Option B"

    @pytest.mark.asyncio
    async def test_ask_user_timeout_first_option_default(self):
        """Test timeout defaults to first option when no default specified."""
        app = TestChatApp()

        response = await app.ask_user(
            question="Will timeout:",
            options=["First", "Second", "Third"],
            timeout=0.2
        )

        # Should return first option
        assert response == "First"

    @pytest.mark.asyncio
    async def test_ask_user_auto_selected(self):
        """Test handling of auto-selected response."""
        app = TestChatApp()

        async def simulate_auto_response():
            await asyncio.sleep(0.1)
            sent_msg = app.transport.sent_messages[0]
            await app._handle_user_response({
                'message_id': sent_msg['message_id'],
                'selected_option_id': 'opt_0',
                'selected_option_label': 'Default Option',
                'is_auto_selected': True  # Marked as auto-selected
            })

        asyncio.create_task(simulate_auto_response())

        response = await app.ask_user(
            question="Test:",
            options=["Default Option", "Other"],
            timeout=5,
            default="Default Option"
        )

        assert response == "Default Option"

    @pytest.mark.asyncio
    async def test_send_notification(self):
        """Test sending notification to user."""
        app = TestChatApp()

        await app.send_notification("Test notification message")

        assert len(app.transport.sent_messages) == 1
        msg = app.transport.sent_messages[0]
        assert msg['type'] == 'robot_notification'
        assert msg['content'] == "Test notification message"
        assert 'message_id' in msg

    @pytest.mark.asyncio
    async def test_multiple_questions(self):
        """Test asking multiple questions in sequence."""
        app = TestChatApp()

        async def simulate_responses():
            # Wait for first question
            await asyncio.sleep(0.1)
            msg1 = app.transport.sent_messages[0]
            await app._handle_user_response({
                'message_id': msg1['message_id'],
                'selected_option_label': 'Answer 1',
                'is_auto_selected': False
            })

            # Wait for second question
            await asyncio.sleep(0.2)
            msg2 = app.transport.sent_messages[1]
            await app._handle_user_response({
                'message_id': msg2['message_id'],
                'selected_option_label': 'Answer 2',
                'is_auto_selected': False
            })

        asyncio.create_task(simulate_responses())

        # First question
        response1 = await app.ask_user(
            question="Question 1?",
            options=["Answer 1", "Other"],
            timeout=5
        )

        # Second question
        response2 = await app.ask_user(
            question="Question 2?",
            options=["Answer 2", "Other"],
            timeout=5
        )

        assert response1 == "Answer 1"
        assert response2 == "Answer 2"
        assert len(app.transport.sent_messages) == 2

    @pytest.mark.asyncio
    async def test_normalize_options(self):
        """Test option normalization."""
        app = TestChatApp()

        # Test simple strings
        simple = app._normalize_options(["A", "B", "C"])
        assert len(simple) == 3
        assert simple[0] == {'id': 'opt_0', 'label': 'A'}
        assert simple[1] == {'id': 'opt_1', 'label': 'B'}

        # Test dicts with id and label
        structured = app._normalize_options([
            {"id": "x", "label": "X"},
            {"id": "y", "label": "Y"}
        ])
        assert structured[0] == {'id': 'x', 'label': 'X'}
        assert structured[1] == {'id': 'y', 'label': 'Y'}

        # Test mixed types
        mixed = app._normalize_options([
            "String option",
            {"id": "custom", "label": "Custom"},
            123  # Non-string type
        ])
        assert mixed[0]['label'] == "String option"
        assert mixed[1]['id'] == "custom"
        assert mixed[2]['label'] == "123"

    @pytest.mark.asyncio
    async def test_concurrent_questions_different_ids(self):
        """Test that concurrent questions have different message IDs."""
        app = TestChatApp()

        async def ask_and_respond(idx):
            async def respond():
                await asyncio.sleep(0.1)
                msg = app.transport.sent_messages[idx]
                await app._handle_user_response({
                    'message_id': msg['message_id'],
                    'selected_option_label': f'Answer {idx}',
                    'is_auto_selected': False
                })

            asyncio.create_task(respond())
            return await app.ask_user(
                question=f"Question {idx}?",
                options=[f"Answer {idx}", "Other"],
                timeout=5
            )

        # Ask two questions concurrently
        results = await asyncio.gather(
            ask_and_respond(0),
            ask_and_respond(1)
        )

        assert results[0] == "Answer 0"
        assert results[1] == "Answer 1"

        # Check message IDs are different
        msg_ids = [msg['message_id'] for msg in app.transport.sent_messages]
        assert len(set(msg_ids)) == 2  # All unique


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
