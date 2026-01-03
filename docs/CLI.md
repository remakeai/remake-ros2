# Kaia CLI

Command-line tool for pairing robots with the Remake.ai apps platform.

## Quick Start

```bash
# 1. Login
kaia login

# 2. Pair a robot
kaia pair --robot-name my_robot

# 3. Connect (go online)
kaia connect

# Robot now appears in Appstore dashboard!
```

## Commands

| Command | Description |
|---------|-------------|
| `kaia login` | Authenticate with Appstore |
| `kaia logout` | Clear stored credentials |
| `kaia pair` | Register a new robot |
| `kaia unpair` | Remove a robot |
| `kaia connect` | Go online (WebSocket) |
| `kaia status` | Show current status |

## Configuration

Credentials stored in `~/.config/kaiaai/config.yml` (chmod 600)