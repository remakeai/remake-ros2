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
ChatMixin - Add user messaging capabilities to robot apps.

Usage:
    class MyRobotApp(RobotApp, ChatMixin):
        async def run(self):
            response = await self.ask_user(
                question="What should I do?",
                options=["Option A", "Option B", "Option C"],
                timeout=60,
                default="Option B"
            )
            print(f"User selected: {response}")
"""

import asyncio
import uuid
import logging
from typing import List, Dict, Any, Optional, Union

logger = logging.getLogger(__name__)


class ChatMixin:
    """
    Mixin class that adds user messaging capabilities to robot apps.

    Requires the app to have a `transport` attribute with `send_message()` method
    and to call `_setup_chat_handlers()` during initialization.
    """

    def __init__(self):
        super().__init__()
        self._pending_questions: Dict[str, asyncio.Future] = {}
        self._setup_chat_handlers()

    def _setup_chat_handlers(self):
        """Register message handlers for chat responses."""
        if hasattr(self, 'register_message_type'):
            self.register_message_type('user_response')
            self.add_message_callback('user_response', self._handle_user_response)

    async def _handle_user_response(self, message: Dict[str, Any]):
        """Handle incoming user response."""
        message_id = message.get('message_id')
        if message_id and message_id in self._pending_questions:
            future = self._pending_questions.pop(message_id)
            if not future.done():
                future.set_result({
                    'selected_option_id': message.get('selected_option_id'),
                    'selected_option_label': message.get('selected_option_label'),
                    'is_auto_selected': message.get('is_auto_selected', False)
                })

    def _normalize_options(self, options: Union[List[str], List[Dict[str, str]]]) -> List[Dict[str, str]]:
        """Convert options to standard format [{id, label}, ...]"""
        normalized = []
        for i, opt in enumerate(options):
            if isinstance(opt, str):
                normalized.append({'id': f'opt_{i}', 'label': opt})
            elif isinstance(opt, dict):
                normalized.append({
                    'id': opt.get('id', f'opt_{i}'),
                    'label': opt.get('label', str(opt))
                })
            else:
                normalized.append({'id': f'opt_{i}', 'label': str(opt)})
        return normalized

    async def ask_user(
        self,
        question: str,
        options: Union[List[str], List[Dict[str, str]]],
        timeout: int = 60,
        default: Optional[str] = None
    ) -> str:
        """
        Ask the user a question and wait for their response.

        Args:
            question: The question text to display to the user
            options: List of option strings or dicts with {id, label}
            timeout: Seconds to wait before auto-selecting default (default: 60)
            default: Option label to auto-select on timeout (default: first option)

        Returns:
            The label of the selected option

        Example:
            response = await self.ask_user(
                question="I found an obstacle. What should I do?",
                options=["Go around it", "Stop and wait", "Return to base"],
                timeout=30,
                default="Stop and wait"
            )
        """
        # Normalize options
        normalized_options = self._normalize_options(options)

        # Determine default option
        default_option_id = None
        if default:
            for opt in normalized_options:
                if opt['label'] == default:
                    default_option_id = opt['id']
                    break
        if not default_option_id:
            default_option_id = normalized_options[0]['id']

        # Generate message ID
        message_id = str(uuid.uuid4())

        # Create future to wait for response
        future = asyncio.get_event_loop().create_future()
        self._pending_questions[message_id] = future

        # Send question to platform
        await self.transport.send_message({
            'type': 'robot_question',
            'message_id': message_id,
            'content': question,
            'options': normalized_options,
            'timeout_seconds': timeout,
            'default_option': default_option_id
        })

        logger.info(f"Asked user: {question}")

        try:
            # Wait for response with timeout (add buffer for network latency)
            response = await asyncio.wait_for(future, timeout=timeout + 5)

            if response.get('is_auto_selected'):
                logger.info(f"User response (auto-selected): {response.get('selected_option_label')}")
            else:
                logger.info(f"User response: {response.get('selected_option_label')}")

            return response.get('selected_option_label', '')

        except asyncio.TimeoutError:
            # Clean up and return default
            self._pending_questions.pop(message_id, None)
            default_label = next(
                (opt['label'] for opt in normalized_options if opt['id'] == default_option_id),
                normalized_options[0]['label']
            )
            logger.warning(f"Question timed out, using default: {default_label}")
            return default_label

    async def send_notification(self, message: str):
        """
        Send a notification message to the user (no response expected).

        Args:
            message: The notification text to display
        """
        message_id = str(uuid.uuid4())
        await self.transport.send_message({
            'type': 'robot_notification',
            'message_id': message_id,
            'content': message
        })
        logger.info(f"Sent notification: {message}")
