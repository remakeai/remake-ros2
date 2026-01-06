# CLI Commands Reference

Complete reference for all 13 remakeai_ros2 CLI commands.

---

## 1. Login

**Authenticate user with Remake.AI**

```bash
remake login [OPTIONS]
```

**Description:**
Opens browser for OAuth login with Remake.AI account. Token saved to config.

**Output:**
```
Opening browser for login...
Please complete login in your browser.
Login successful!
```

**Config Updated:**
```json
{
  "auth": {
    "token": "eyJhbGc...",
    "email": "user@remake.ai",
    "expires_at": "2025-01-08T12:00:00Z"
  }
}
```

---

## 2. Logout

**Clear authentication credentials**

```bash
remake logout [OPTIONS]
```

**Description:**
Removes stored auth token and user email.

**Output:**
```
Logged out successfully.
Credentials cleared.
```

---

## 3. Pair

**Add new robot to configuration**

```bash
remake pair [OPTIONS]
  --robot-id TEXT        Robot ID (required)
  --secret TEXT          Robot secret (required)
  --name TEXT           Robot display name
  --device-id TEXT      Device MAC address
  --product-id TEXT     Product type
```

**Example:**
```bash
remake pair \
  --robot-id robot-001 \
  --secret abc123xyz789 \
  --name "Living Room Bot" \
  --device-id "00:11:22:33:44:55"
```

**Output:**
```
Robot paired successfully!
Robot: robot-001
Name: Living Room Bot
Device: 00:11:22:33:44:55
```

---

## 4. Unpair

**Remove robot from configuration**

```bash
remake unpair [OPTIONS]
  --robot-id TEXT   Robot ID (required)
```

**Example:**
```bash
remake unpair --robot-id robot-001
```

**Output:**
```
Robot unpaired successfully!
Removed: robot-001
```

---

## 5. Robots

**List all paired robots**

```bash
remake robots [OPTIONS]
```

**Output:**
```
Paired Robots (1):
1. robot-001
   Name: Living Room Bot
   Device: 00:11:22:33:44:55
   Paired: 2025-01-07T10:00:00Z
```

---

## 6. Connect

**Connect robot to platform**

```bash
remake connect [OPTIONS]
  --robot-name TEXT        Robot name (required)
  --ros2 / --no-ros2      Enable ROS2 bridge (default: True)
  --platform-url TEXT     Platform URL
  --timeout INT           Connection timeout (default: 30s)
```

**Example:**
```bash
remake connect --robot-name "My Robot" --ros2
```

**Output:**
```
[Phase 1] Connecting to platform
[OK] Connected to wss://apps.remake.ai
[OK] Authentication token obtained
[OK] Robot connected and authenticated
[OK] ROS2 bridge started
[OK] Waiting for app session...
```

**Blocks until:**
- Connection lost
- User presses Ctrl+C
- Session terminated

---

## 7. Logout (Alias)

**Exit connection without logout**

```bash
remake disconnect [OPTIONS]
```

**Output:**
```
Disconnecting...
Disconnected.
```

---

## 8. Status

**Show current system status**

```bash
remake status [OPTIONS]
```

**Output:**
```
remakeai_ros2 Status
===================

Authentication:
  Status: AUTHENTICATED
  Email: user@remake.ai
  Token Expires: 2025-01-08T12:00:00Z

Paired Robots: 1
  - robot-001: Living Room Bot

Platform:
  URL: wss://apps.remake.ai
  Connected: NO

Configuration:
  Asset Quota: 100 MB
  ROS2 Domain: 0
```

---

## 9. Info

**Show robot and app information**

```bash
remake info [OPTIONS]
  --robot-name TEXT   Robot name (required if connected)
```

**Output:**
```
Robot Information
=================

Robot ID: robot-001
Name: Living Room Bot
Status: OFFLINE

Specifications:
  Model: Vacuum Pro v2
  Sensors: [laser, battery, camera, map]
  Max Speed: 0.5 m/s
  Max Angular: 2.0 rad/s
  Shape: circular, 0.35m diameter

Capabilities:
  - mapping
  - navigation
  - remote_control
  - asset_management
```

---

## 10. Logs

**Show system logs**

```bash
remake logs [OPTIONS]
  --lines INT         Number of lines (default: 50)
  --follow / --no-follow  Stream new logs
  --filter TEXT       Filter by keyword
```

**Example:**
```bash
remake logs --lines 100 --filter "error"
```

**Output:**
```
=== Recent Logs ===

2025-01-07 12:00:45 [INFO] Started remakeai_ros2
2025-01-07 12:01:30 [DEBUG] Connecting to platform...
2025-01-07 12:01:35 [INFO] Connected successfully
2025-01-07 12:05:00 [WARN] High latency detected (150ms)
2025-01-07 12:10:00 [INFO] App session started
```

---

## 11. Config

**Manage configuration settings**

```bash
remake config [OPTIONS] COMMAND
  --get KEY     Get config value
  --set KEY VALUE    Set config value
  --list        List all settings
  --reset       Reset to defaults
```

**Examples:**
```bash
# Get setting
remake config --get platform_url

# Set setting
remake config --set asset_quota_mb 200

# List all settings
remake config --list

# Reset to defaults
remake config --reset
```

**Output:**
```
Current Configuration:
  platform_url: wss://apps.remake.ai
  asset_quota_mb: 100
  ros2_domain_id: 0
  log_level: INFO
```

---

## 12. Assets

**Manage app asset files**

```bash
remake assets [OPTIONS] COMMAND
  --list                List all files
  --upload FILE         Upload file
  --download FILE       Download file
  --delete FILE         Delete file
  --usage              Show quota usage
```

**Examples:**
```bash
# List files
remake assets --list

# Upload file
remake assets --upload model.pkl

# Download file
remake assets --download model.pkl

# Delete file
remake assets --delete model.pkl

# Check usage
remake assets --usage
```

**Output:**
```
Asset Management
================

Storage Usage:
  Used: 25.5 MB / 100 MB
  Remaining: 74.5 MB

Files (3):
  1. model.pkl (15.2 MB)
     Uploaded: 2025-01-07T10:00:00Z
     Hash: a1b2c3d4e5f6...

  2. config.json (0.1 MB)
     Uploaded: 2025-01-07T10:05:00Z
     Hash: b2c3d4e5f6a1...

  3. data.bin (10.2 MB)
     Uploaded: 2025-01-07T10:10:00Z
     Hash: c3d4e5f6a1b2...
```

---

## 13. Launch

**Launch an app on the robot**

```bash
remake launch [OPTIONS]
  --app TEXT          App ID (required)
  --robot-name TEXT   Robot name (required)
  --timeout INT       Timeout (default: 60s)
```

**Example:**
```bash
remake launch --app hello-world --robot-name "My Robot"
```

**Output:**
```
Launching app...
App ID: hello-world
Robot: robot-001
Status: PENDING

Waiting for app launch...
[Phase 1] Establishing session...
[Phase 2] Setting up resources...
[Phase 3] Enabling remote control...

[OK] App launched successfully!
Session ID: sess_abc123
App URL: https://hello-world.remake.ai
```

---

## 14. Factory Reset

**Reset robot to factory defaults**

```bash
remake factory-reset [OPTIONS]
  --robot-id TEXT     Robot ID (required)
  --force / --no-force  Skip confirmation
```

**Example:**
```bash
remake factory-reset --robot-id robot-001
```

**Confirmation:**
```
WARNING: This will reset the robot to factory defaults!
All credentials and configuration will be cleared.

Are you sure? (yes/no): yes

Resetting robot...
[OK] Factory reset complete!
Robot must be reconfigured and paired again.
```

---

## Global Options

```bash
remake [GLOBAL_OPTIONS] COMMAND [OPTIONS]

Global Options:
  --debug             Enable debug logging
  --config FILE       Use custom config file
  --version           Show version
  --help              Show help
```

**Examples:**
```bash
# Debug mode
remake --debug status

# Custom config
remake --config /etc/remake/config.json login

# Show version
remake --version

# Show help
remake --help
```

---

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Usage error |
| 3 | Authentication failed |
| 4 | Robot not found |
| 5 | Connection timeout |
| 10 | File not found |
| 11 | Insufficient quota |

---

## Examples

### Complete Workflow
```bash
# 1. Login
remake login

# 2. Pair robot
remake pair --robot-id robot-001 --secret abc123

# 3. Check status
remake status

# 4. Upload file
remake assets --upload model.pkl

# 5. Connect robot
remake connect --robot-name "My Robot" --ros2

# 6. Launch app (from platform dashboard)

# 7. Check logs
remake logs

# 8. Disconnect
Ctrl+C
```

### Scripted Automation
```bash
#!/bin/bash

# Login if needed
remake status || remake login

# Pair robot
remake pair --robot-id $ROBOT_ID --secret $ROBOT_SECRET

# Upload files
for file in *.pkl; do
    remake assets --upload "$file"
done

# Connect and wait
remake connect --robot-name "Auto Bot" --ros2
```

---

## Tips & Tricks

1. **Use `--help` for any command**
   ```bash
   remake connect --help
   ```

2. **Use aliases for common commands**
   ```bash
   alias r=remake
   r status
   r logs
   ```

3. **Redirect output to file**
   ```bash
   remake logs > logs.txt
   remake status > status.txt
   ```

4. **Use in scripts**
   ```bash
   TOKEN=$(remake config --get platform_url)
   ROBOT=$(remake robots | grep "robot-001")
   ```

5. **Watch logs in real-time**
   ```bash
   remake logs --follow
   ```

---

## Troubleshooting Commands

```bash
# Check if authenticated
remake status

# Show detailed info
remake --debug status

# View logs for errors
remake logs --filter error

# Test connection
remake info

# Reset if corrupted
remake factory-reset

# Verify pairing
remake robots

# Check config
remake config --list
```
