from setuptools import find_packages, setup

package_name = 'remake_ros2'

setup(
    name=package_name,
    version='0.2.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/config', ['config/services.yaml']),
        ('share/' + package_name + '/launch', ['launch/app_bridge.launch.py']),
    ],
    install_requires=[
        'setuptools',
        'httpx>=0.24.0',
        'python-socketio>=5.0.0',
        'aiohttp>=3.8.0',
        'pyyaml>=6.0',
    ],
    zip_safe=True,
    author='Ilia O.',
    author_email='iliao@remake.ai',
    maintainer='Ilia O.',
    maintainer_email='iliao@remake.ai',
    keywords=['ROS', 'ROS2', 'Remake.ai'],
    classifiers=[
        'Intended Audience :: Developers',
        'License :: OSI Approved :: Apache Software License',
        'Programming Language :: Python',
        'Topic :: Software Development',
    ],
    description=('ROS2 App Bridge for Remake.ai robot app platform'),
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'remake_app_bridge = remake_ros2.app_bridge_node:main',
        ],
    },
)
