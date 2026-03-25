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
Launch file for the Remake App Bridge.

Starts the App Bridge node that connects containerized apps
to the ROS2 robot via Socket.IO.

Usage:
    ros2 launch remake_ros2 app_bridge.launch.py
    ros2 launch remake_ros2 app_bridge.launch.py port:=9000
    ros2 launch remake_ros2 app_bridge.launch.py services:=/path/to/services.yaml
"""

import os
from ament_index_python.packages import get_package_share_path
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess
from launch.substitutions import LaunchConfiguration


def generate_launch_description():
    # Default services.yaml path
    pkg_share = get_package_share_path('remake_ros2')
    default_services = os.path.join(pkg_share, 'config', 'services.yaml')

    return LaunchDescription([
        DeclareLaunchArgument(
            'host',
            default_value='0.0.0.0',
            description='Socket.IO server bind address'
        ),
        DeclareLaunchArgument(
            'port',
            default_value='8788',
            description='Socket.IO server port'
        ),
        DeclareLaunchArgument(
            'services',
            default_value=default_services,
            description='Path to services.yaml configuration'
        ),
        DeclareLaunchArgument(
            'robot_id',
            default_value='remake-robot',
            description='Robot identifier sent in welcome message'
        ),
        ExecuteProcess(
            cmd=[
                'python3', '-m', 'remake_ros2.app_bridge_node',
                '--host', LaunchConfiguration('host'),
                '--port', LaunchConfiguration('port'),
                '--services', LaunchConfiguration('services'),
                '--robot-id', LaunchConfiguration('robot_id'),
            ],
            name='app_bridge',
            output='screen',
        ),
    ])
