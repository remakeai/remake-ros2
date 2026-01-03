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
Example: Using ChatMixin to ask users questions during robot operation.

This example shows how to integrate ChatMixin into a robot app to enable
interactive decision-making with users.
"""

import asyncio
import logging
from kaiaai import AppstoreRobotClient, ChatMixin

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class InteractiveRobotApp(AppstoreRobotClient, ChatMixin):
    """
    Example robot app that asks users for guidance during operation.

    Inherits from both AppstoreRobotClient (for robot control) and
    ChatMixin (for user messaging).
    """

    def __init__(self, robot_id: str, robot_secret: str):
        super().__init__(robot_id, robot_secret)

    async def on_obstacle_detected(self, obstacle_distance: float):
        """Called when robot detects an obstacle."""
        logger.info(f"Obstacle detected at {obstacle_distance:.2f}m")

        # Ask user what to do
        response = await self.ask_user(
            question=f"I detected an obstacle {obstacle_distance:.2f}m ahead. What should I do?",
            options=[
                "Go around it",
                "Stop and wait",
                "Return to base",
                "Keep going slowly"
            ],
            timeout=30,
            default="Stop and wait"
        )

        # Act on user's decision
        if response == "Go around it":
            await self.navigate_around_obstacle()
        elif response == "Stop and wait":
            await self.stop()
            await self.send_notification("Stopped and waiting for further instructions.")
        elif response == "Return to base":
            await self.return_to_base()
        elif response == "Keep going slowly":
            await self.move_forward_slowly()

    async def on_battery_low(self, battery_percent: int):
        """Called when battery is low."""
        logger.info(f"Battery low: {battery_percent}%")

        # Ask user about charging
        response = await self.ask_user(
            question=f"Battery is at {battery_percent}%. Should I charge now?",
            options=["Yes, charge now", "No, continue working"],
            timeout=60,
            default="Yes, charge now"
        )

        if response == "Yes, charge now":
            await self.navigate_to_charger()
            await self.send_notification("Heading to charging station.")
        else:
            await self.send_notification("Continuing work. Will check battery again soon.")

    async def on_task_complete(self):
        """Called when a task is finished."""
        await self.send_notification("Task completed successfully!")

        # Ask what to do next
        response = await self.ask_user(
            question="What should I do next?",
            options=[
                "Start another task",
                "Return to base",
                "Wait for instructions",
                "Explore the area"
            ],
            timeout=120,
            default="Wait for instructions"
        )

        logger.info(f"User chose: {response}")
        # Handle next action based on response

    async def navigate_around_obstacle(self):
        """Navigate around detected obstacle."""
        logger.info("Navigating around obstacle...")
        # Implementation here

    async def stop(self):
        """Stop robot movement."""
        logger.info("Stopping robot...")
        # Implementation here

    async def return_to_base(self):
        """Return to base/home position."""
        logger.info("Returning to base...")
        # Implementation here

    async def move_forward_slowly(self):
        """Move forward at reduced speed."""
        logger.info("Moving forward slowly...")
        # Implementation here

    async def navigate_to_charger(self):
        """Navigate to charging station."""
        logger.info("Navigating to charger...")
        # Implementation here

    async def run(self):
        """Main robot control loop."""
        logger.info("Interactive robot app started")

        # Example: Ask user before starting
        start_response = await self.ask_user(
            question="Ready to start operation. Which mode?",
            options=[
                {"id": "auto", "label": "Autonomous mode"},
                {"id": "manual", "label": "Manual control"},
                {"id": "explore", "label": "Exploration mode"}
            ],
            timeout=60,
            default="Autonomous mode"
        )

        logger.info(f"Starting in mode: {start_response}")

        # Continue with robot operations...
        await asyncio.sleep(10)  # Simulate work

        # Trigger example events
        await self.on_obstacle_detected(1.5)
        await asyncio.sleep(5)

        await self.on_battery_low(20)
        await asyncio.sleep(5)

        await self.on_task_complete()


async def main():
    """Run the interactive robot app."""
    # Replace with actual robot credentials
    robot_id = "your-robot-id"
    robot_secret = "your-robot-secret"

    app = InteractiveRobotApp(robot_id, robot_secret)

    try:
        # Connect to platform
        await app.connect()

        # Run the app
        await app.run()

    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await app.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
