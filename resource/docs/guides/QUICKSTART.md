# Quick Start Guide

Get started with remakeai_ros2 in 5 minutes.

---

## Prerequisites

- Python 3.9+
- ROS2 installed (Humble or Jazzy recommended)
- Remake.AI account
- Git

---

## 1. Clone & Setup (2 minutes)

```bash
# Clone the repository
git clone https://github.com/remake-ai/remakeai_ros2.git
cd remakeai_ros2

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install package
pip install -e .
```

---

## 2. Run All Tests (30 seconds)

```bash
# Verify everything works
python -m pytest test_*.py -v

# Expected output:
# ======================== 106 passed in 1.91s ==========================
```

---

## 3. CLI Quick Test (1 minute)

```bash
# Check CLI is working
remake --help

# Expected output:
# Usage: remake [OPTIONS] COMMAND [ARGS]...
#
# Commands:
#   connect      Connect to platform
#   factory-reset    Factory reset
#   ...
```

---

## 4. Login to Your Account (30 seconds)

```bash
remake login
# Follow the browser to login with your Remake.AI account
# Credentials saved to ~/.config/remake/config.json
```

---

## 5. Pair Your Robot (30 seconds)

```bash
# Get your robot ID and secret from dashboard
remake pair --robot-id robot-001 --secret YOUR_ROBOT_SECRET

# Verify pairing
remake robots
# Expected: Shows your paired robots
```

---

## 6. Connect Robot (1 minute)

```bash
# Connect robot to platform
remake connect --robot-name "My Robot" --ros2

# Expected output:
# Connected to wss://apps.remake.ai/robot-control
# [OK] Authentication token obtained
# [OK] Robot connected and authenticated
```

---

## 7. Check Status

```bash
remake status

# Expected output:
# Authentication: YES
# Paired Robots: 1
#   - robot-001: My Robot
# Platform: wss://apps.remake.ai
```

---

## What's Next?

### Option A: Test with a Real Robot
1. Install remakeai_ros2 on robot
2. Run `remake connect --robot-name "My Robot" --ros2`
3. Launch an app from the platform dashboard
4. Send movement commands

### Option B: Learn the Architecture
1. Read `docs/architecture/COMPONENTS.md`
2. Review `docs/architecture/PROTOCOL.md`
3. Study `docs/architecture/SECURITY.md`

### Option C: Explore the Code
1. Check out `remakeai/platform_client_node.py`
2. Review `remakeai/ros2_bridge.py`
3. Look at `remakeai/cli.py` for examples

### Option D: Write Custom Apps
1. See app examples in related projects
2. Use Socket.IO to communicate with robot
3. Send movement commands via WebSocket

---

## CLI Commands Cheat Sheet

```bash
# Authentication
remake login                          # Login with Remake.AI account
remake logout                         # Logout and clear credentials
remake status                         # Show auth status

# Robot Management
remake pair --robot-id ID --secret S  # Add new robot
remake robots                         # List paired robots
remake unpair --robot-id ID          # Remove robot

# Connection
remake connect --robot-name "Name" --ros2     # Connect robot
remake info                           # Show robot/app info

# Configuration
remake config --set platform_url URL  # Change platform
remake config --get platform_url      # View setting

# Files
remake assets --list                  # List stored files
remake assets --upload FILE           # Upload file
remake assets --delete FILE           # Delete file

# System
remake logs                           # Show system logs
remake factory-reset                 # Factory reset
remake help                          # Show this help
```

---

## Common Workflows

### Workflow 1: Connect and Control Robot

```bash
# Step 1: Login
remake login

# Step 2: Pair robot (if not already paired)
remake pair --robot-id robot-001 --secret YOUR_SECRET

# Step 3: Connect robot
remake connect --robot-name "My Robot" --ros2

# Step 4: Launch app from dashboard
# (open https://apps.remake.ai, select robot, launch app)

# Step 5: Control from app
# (app now has access to robot movement and sensors)
```

### Workflow 2: Deploy Files to App

```bash
# Step 1: Login
remake login

# Step 2: Upload files
remake assets --upload model.pkl
remake assets --upload config.json

# Step 3: List files
remake assets --list

# Step 4: Download file
remake assets --download model.pkl
```

### Workflow 3: Debug Connection Issues

```bash
# Check authentication
remake status

# View detailed logs
remake logs

# Check robot connectivity
remake info

# Reset if needed
remake factory-reset
```

---

## File Locations

**Configuration:** `~/.config/remake/config.json`
**Logs:** `~/.config/remake/logs/`
**Assets:** `~/.config/remake/assets/`

---

## Troubleshooting

### "Command not found: remake"
```bash
# Solution: Make sure virtual environment is activated
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows

# Then try again
remake --help
```

### "Authentication failed"
```bash
# Solution: Clear credentials and re-login
remake logout
remake login
```

### "Connection timeout"
```bash
# Solution: Check network
ping apps.remake.ai

# Check firewall/proxy
# WebSocket port: 443 (wss://)
```

### "Robot not found"
```bash
# Solution: Make sure robot is paired
remake robots

# If not paired:
remake pair --robot-id YOUR_ID --secret YOUR_SECRET
```

---

## Next Steps

1. ✅ Setup complete
2. ✅ Tests passing
3. ✅ CLI working
4. ✅ Robot connected

**Now:**
- Launch an app from the platform
- Send movement commands
- Stream sensor data
- Store files

See detailed docs in `resources/docs/` for more information.

---

## Getting Help

- **Issues:** Check GitHub issues
- **Docs:** Read `resources/docs/` folders
- **Email:** support@remake.ai
- **Chat:** Join our Discord

Happy coding!
