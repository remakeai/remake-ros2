# ChatMixin - User Messaging SDK

The ChatMixin provides robot apps with the ability to ask users questions and receive responses in real-time through the Kaia.ai platform.

## Features

- **Interactive decision-making** - Ask users questions during robot operation
- **Timeout handling** - Automatic fallback to default option
- **Flexible options** - Support for simple strings or structured objects
- **Notifications** - Send one-way messages to users
- **Async/await** - Integrates seamlessly with async robot apps

## Installation

The ChatMixin is included in the kaiaai package. No additional installation needed.

```bash
cd kaiaai
pip install -e .
```

## Quick Start

### Step 1: Import and Create Your Robot App

```python
from kaiaai import AppstoreRobotClient, ChatMixin

class MyRobotApp(AppstoreRobotClient, ChatMixin):
    def __init__(self, robot_id, robot_secret):
        super().__init__(robot_id, robot_secret)

    async def run(self):
        # Your robot logic here
        pass
```

### Step 2: Ask User a Question

```python
async def run(self):
    response = await self.ask_user(
        question="What should I do?",
        options=["Clean the room", "Patrol", "Return to base"],
        timeout=60,
        default="Return to base"
    )

    if response == "Clean the room":
        await self.clean()
    elif response == "Patrol":
        await self.patrol()
    else:
        await self.go_home()
```

### Step 3: Send Notifications

```python
async def clean(self):
    await self.send_notification("Starting cleaning task...")
    # Do work
    await self.send_notification("Cleaning complete!")
```

## API Reference

### `ask_user()`

Ask the user a question and wait for their response.

**Signature:**
```python
async def ask_user(
    question: str,
    options: Union[List[str], List[Dict[str, str]]],
    timeout: int = 60,
    default: Optional[str] = None
) -> str
```

**Parameters:**
- `question` (str): The question text to display to the user
- `options` (List[str] | List[Dict]): Available response options
  - Simple: `["Option 1", "Option 2"]`
  - Structured: `[{"id": "opt1", "label": "Option 1"}, ...]`
- `timeout` (int): Seconds to wait before auto-selecting default (default: 60)
- `default` (str, optional): Option label to auto-select on timeout (defaults to first option)

**Returns:**
- `str`: The label of the selected option

### `send_notification()`

Send a notification message to the user (no response expected).

**Signature:**
```python
async def send_notification(message: str)
```

**Parameters:**
- `message` (str): The notification text to display

## Usage Patterns

### Yes/No Decision

```python
response = await self.ask_user(
    question="Battery is low. Charge now?",
    options=["Yes", "No"],
    timeout=30,
    default="Yes"
)

if response == "Yes":
    await self.navigate_to_charger()
```

### Multiple Choice

```python
response = await self.ask_user(
    question="I detected an obstacle. What should I do?",
    options=["Go around it", "Stop and wait", "Return to base", "Continue slowly"],
    timeout=45,
    default="Stop and wait"
)
```

### Mode Selection with Structured Options

```python
mode = await self.ask_user(
    question="Select operating mode:",
    options=[
        {"id": "auto", "label": "Autonomous"},
        {"id": "manual", "label": "Manual Control"},
        {"id": "explore", "label": "Exploration"}
    ],
    timeout=60,
    default="Autonomous"
)
```

### Progress Updates

```python
async def long_task(self):
    await self.send_notification("Starting long task...")

    for i in range(5):
        await self.work_step(i)
        await self.send_notification(f"Progress: {(i+1)*20}%")

    await self.send_notification("Task complete!")
```

## Complete Example

```python
import asyncio
from kaiaai import AppstoreRobotClient, ChatMixin

class CleaningRobot(AppstoreRobotClient, ChatMixin):
    def __init__(self, robot_id, robot_secret):
        super().__init__(robot_id, robot_secret)

    async def run(self):
        task = await self.ask_user(
            question="What should I do today?",
            options=[
                "Clean the living room",
                "Clean the kitchen",
                "Patrol the house",
                "Wait for instructions"
            ],
            timeout=120,
            default="Wait for instructions"
        )

        if "Clean" in task:
            await self.clean_room(task)
        elif task == "Patrol the house":
            await self.patrol()
        else:
            await self.send_notification("Standing by for instructions.")

    async def clean_room(self, room_name):
        await self.send_notification(f"Starting to {room_name.lower()}...")

        for i in range(4):
            await asyncio.sleep(5)
            await self.send_notification(f"Cleaning progress: {(i+1)*25}%")

        await self.send_notification(f"{room_name} complete!")

        next_action = await self.ask_user(
            question="What should I do next?",
            options=["Continue cleaning", "Return to base"],
            timeout=60,
            default="Return to base"
        )

        if next_action == "Continue cleaning":
            await self.run()
        else:
            await self.send_notification("Returning to base...")

    async def patrol(self):
        await self.send_notification("Starting patrol...")


async def main():
    robot = CleaningRobot("your-robot-id", "your-robot-secret")

    try:
        await robot.connect()
        await robot.run()
    except KeyboardInterrupt:
        print("Shutting down...")
    finally:
        await robot.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
```

## Timeout Behavior

When a timeout occurs:
1. The pending question is cleaned up
2. The default option is returned automatically
3. A warning is logged

```python
# If user doesn't respond in 30 seconds, "Stop" is auto-selected
response = await self.ask_user(
    question="Continue?",
    options=["Continue", "Stop"],
    timeout=30,
    default="Stop"
)
# response will be "Stop" after timeout
```

## Error Handling

```python
try:
    response = await self.ask_user(
        question="What next?",
        options=["A", "B"],
        timeout=60
    )
    await self.handle_response(response)
except Exception as e:
    logger.error(f"Error in user interaction: {e}")
    # Fallback behavior
```

## Best Practices

1. **Set appropriate timeouts** - 30-60 seconds for simple questions, 120+ for complex decisions
2. **Provide good defaults** - Choose safe/conservative options (e.g., "Stop" vs "Continue")
3. **Keep questions clear** - Use simple, direct language; avoid technical jargon
4. **Limit options** - 2-5 options work best
5. **Use notifications** - Update users on progress and task completion
6. **Handle timeouts** - Always expect auto-selection might occur

## Troubleshooting

### Questions not appearing
Make sure you're connected to the platform before calling `ask_user()`.

### Timeouts happening too fast
Increase timeout value or check network connectivity.

### Can't import ChatMixin
Install kaiaai package: `pip install -e .`

### AttributeError on transport
Make sure you call `super().__init__()` and connect before asking questions.

## See Also

- [Platform Guide](PLATFORM_GUIDE.md) - Platform integration guide
