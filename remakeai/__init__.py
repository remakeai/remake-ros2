__version__ = "1.0.0"

from .message_callback_mixin import MessageCallbackMixin
from .robot_client import RobotClient

# ROS2-dependent imports (optional - only available in ROS2 environment)
try:
    from .robot_client_ros2 import RobotClientROS2
    from .platform_robot_client import PlatformRobotClient
except ImportError:
    RobotClientROS2 = None
    PlatformRobotClient = None

# CLI exports
from .api import PlatformClient
from .websocket_client import RobotConnection

__all__ = [
    'MessageCallbackMixin',
    'RobotClient',
    'RobotClientROS2',
    'PlatformRobotClient',
    'PlatformClient',
    'RobotConnection',
]
