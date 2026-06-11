# Service Watchdog

[![CI](https://github.com/tommieseals/service-watchdog/actions/workflows/ci.yml/badge.svg)](https://github.com/tommieseals/service-watchdog/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A configurable service monitoring daemon that watches processes, sends alerts on
failures, and restarts services automatically.

## Features

- **Multiple detection methods**: process name matching, PID file monitoring,
  port availability checks, HTTP health endpoint validation
- **Notifications**: Telegram, Slack, email (SMTP), and generic webhooks
- **Restart logic**: configurable restart delays, maximum restart limits per
  time window, graceful stop/start sequences, environment variable injection
- **Deployment**: systemd unit files and a macOS launchd plist are included;
  dry-run mode for testing; persistent state across restarts

## Demo

Output of `service-watchdog status` against a config watching a local web app
and a Redis instance that is not running:

```
Service Watchdog Status
==================================================

🟢 web-app
   Running: True
   Healthy: True
   Check method: health_url
   Failures: 0
   Restarts: 0

🔴 redis
   Running: False
   Healthy: False
   Error: Port 6379 not listening
   Check method: port
   Failures: 0
   Restarts: 0
```

## Installation

Not published on PyPI. Install from GitHub:

```bash
pip install git+https://github.com/tommieseals/service-watchdog
```

Or from a local clone:

```bash
git clone https://github.com/tommieseals/service-watchdog.git
cd service-watchdog
pip install -e .
```

Requires Python 3.10 or newer.

## Quick Start

### 1. Generate a sample config

```bash
service-watchdog init -o /etc/service-watchdog/config.yaml
```

### 2. Edit the configuration

```yaml
# /etc/service-watchdog/config.yaml
services:
  - name: nginx
    process_name: nginx
    port: 80
    restart_command: systemctl restart nginx
    check_interval: 30
    failure_threshold: 2
    restart_delay: 60

notifiers:
  - type: telegram
    bot_token: ${TELEGRAM_BOT_TOKEN}
    chat_id: ${TELEGRAM_CHAT_ID}
```

### 3. Validate your config

```bash
service-watchdog validate -c /etc/service-watchdog/config.yaml
```

### 4. Run the watchdog

```bash
# Foreground (for testing)
service-watchdog run -c /etc/service-watchdog/config.yaml

# With dry-run mode (no actual restarts)
service-watchdog run -c /etc/service-watchdog/config.yaml --dry-run

# As a daemon (Linux/macOS only)
service-watchdog run -c /etc/service-watchdog/config.yaml -d
```

### 5. Check status

```bash
service-watchdog status -c /etc/service-watchdog/config.yaml
```

## Configuration Reference

### Environment Variable Interpolation

Any string value in the config may reference an environment variable with
`${VAR}` syntax, including inside larger strings and in nested values
(notifier headers, service `env` maps, address lists):

```yaml
notifiers:
  - type: webhook
    url: https://your-service.com/alerts
    headers:
      Authorization: "Bearer ${API_TOKEN}"
```

References are resolved when the config is loaded. If a referenced variable
is not set, loading fails with an error naming the missing variable — use
`service-watchdog validate` to catch this before deploying. This keeps
secrets (bot tokens, SMTP passwords, webhook auth headers) out of the YAML
file.

### Service Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `name` | string | required | Unique service identifier |
| `enabled` | bool | `true` | Enable/disable monitoring |
| `process_name` | string | - | Process name to match |
| `pid_file` | string | - | Path to PID file |
| `port` | int | - | Port to check |
| `health_url` | string | - | HTTP endpoint to check |
| `health_timeout` | int | `10` | Health check timeout (seconds) |
| `restart_command` | string | - | Command to restart service |
| `stop_command` | string | - | Command to stop service |
| `start_command` | string | - | Command to start service |
| `working_dir` | string | - | Working directory for commands |
| `env` | dict | `{}` | Environment variables |
| `restart_delay` | int | `60` | Seconds before restart attempt |
| `max_restarts` | int | `3` | Max restarts within window |
| `restart_window` | int | `3600` | Window in seconds (1 hour) |
| `check_interval` | int | `30` | Seconds between checks |
| `failure_threshold` | int | `2` | Consecutive failures before action |

### Notifier Options

#### Telegram
```yaml
notifiers:
  - type: telegram
    enabled: true
    bot_token: "123456:ABC-DEF..."
    chat_id: "123456789"
    on_failure: true
    on_recovery: true
    on_restart: true
```

#### Slack
```yaml
notifiers:
  - type: slack
    enabled: true
    webhook_url: "https://hooks.slack.com/services/..."
```

#### Email
```yaml
notifiers:
  - type: email
    enabled: true
    smtp_host: smtp.gmail.com
    smtp_port: 587
    smtp_user: user@gmail.com
    smtp_password: ${SMTP_PASSWORD}
    from_addr: watchdog@example.com
    to_addrs:
      - admin@example.com
      - oncall@example.com
```

#### Webhook
```yaml
notifiers:
  - type: webhook
    enabled: true
    url: "https://your-service.com/alerts"
    method: POST
    headers:
      Authorization: "Bearer ${API_TOKEN}"
```

## Systemd Installation (Linux)

```bash
# Copy service file
sudo cp systemd/service-watchdog.service /etc/systemd/system/

# Create config directory
sudo mkdir -p /etc/service-watchdog
sudo cp examples/nginx.yaml /etc/service-watchdog/config.yaml

# Create state directory
sudo mkdir -p /var/lib/service-watchdog
sudo mkdir -p /var/log/service-watchdog

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable service-watchdog
sudo systemctl start service-watchdog

# Check status
sudo systemctl status service-watchdog
journalctl -u service-watchdog -f
```

### Multi-Instance Setup

Monitor different service groups with separate configs:

```bash
# Enable multiple instances
sudo systemctl enable service-watchdog@nginx
sudo systemctl enable service-watchdog@database
sudo systemctl start service-watchdog@nginx
sudo systemctl start service-watchdog@database
```

Each instance uses `/etc/service-watchdog/<name>.yaml`.

## macOS Installation

```bash
# Copy launchd plist
sudo cp launchd/com.service-watchdog.plist /Library/LaunchDaemons/

# Create directories
sudo mkdir -p /usr/local/etc/service-watchdog
sudo mkdir -p /var/lib/service-watchdog
sudo mkdir -p /var/log/service-watchdog

# Copy config
sudo cp examples/nginx.yaml /usr/local/etc/service-watchdog/config.yaml

# Load the service
sudo launchctl load /Library/LaunchDaemons/com.service-watchdog.plist

# Check status
sudo launchctl list | grep service-watchdog
```

## Running on Windows

The checks (process name, port, health URL, PID file) and the CLI work on
Windows, and the test suite runs in CI on `windows-latest`. However:

- The `-d`/`--daemon` flag uses `os.fork()` and is **not available on
  Windows**. Run the watchdog in the foreground instead.
- No Windows service wrapper ships with this project. To keep the watchdog
  running in the background, use one of the standard approaches:
  - **Task Scheduler**: create a task that runs
    `service-watchdog run -c C:\path\to\config.yaml` at startup
    (`schtasks /create /sc onstart ...` or via the GUI). Set it to restart on
    failure.
  - **[NSSM](https://nssm.cc/)** (Non-Sucking Service Manager): wrap the same
    command as a proper Windows service with
    `nssm install service-watchdog`.
- Use Windows paths for `log_file`, `state_file`, and `pid_file` in your
  config (the defaults are Unix paths), and Windows commands for
  `restart_command` (e.g. `powershell -Command "Restart-Service MyService"`).

These wrappers are documented for convenience but are not shipped or tested by
this project the way the systemd/launchd units are.

## Dry-Run Mode

Test your configuration without actually restarting services:

```bash
service-watchdog run -c config.yaml --dry-run -v
```

In dry-run mode:

- All checks execute normally
- Notifications are sent (to verify they work)
- No actual restart commands are executed
- Logs show what *would* happen

## Example Configurations

See the [`examples/`](examples/) directory for complete configurations:

- [`nginx.yaml`](examples/nginx.yaml) - Web server monitoring
- [`postgres.yaml`](examples/postgres.yaml) - Database monitoring
- [`node-app.yaml`](examples/node-app.yaml) - Node.js application with PM2
- [`multi-service.yaml`](examples/multi-service.yaml) - Full application stack
- [`docker.yaml`](examples/docker.yaml) - Docker container monitoring

## CLI Reference

```
Usage: service-watchdog [OPTIONS] COMMAND [ARGS]...

Commands:
  run       Start the watchdog daemon
  validate  Validate configuration file
  status    Show status of monitored services
  restart   Manually restart a service
  init      Generate a sample configuration file

Options:
  --version  Show the version and exit.
  --help     Show this message and exit.
```

### Commands

```bash
# Start daemon
service-watchdog run -c config.yaml [-d] [--dry-run] [-v]

# Validate config
service-watchdog validate -c config.yaml

# Check status
service-watchdog status -c config.yaml [--json]

# Manual restart
service-watchdog restart -c config.yaml SERVICE_NAME

# Generate sample config
service-watchdog init [-o OUTPUT_FILE]
```

## Architecture

```
┌─────────────────────────────────────────────────┐
│                Service Watchdog                  │
├─────────────────────────────────────────────────┤
│  ┌─────────┐  ┌─────────┐  ┌─────────┐         │
│  │ Monitor │  │ Monitor │  │ Monitor │  ...     │
│  │ nginx   │  │ postgres│  │ my-app  │         │
│  └────┬────┘  └────┬────┘  └────┬────┘         │
│       │            │            │               │
│       └────────────┴────────────┘               │
│                    │                            │
│              ┌─────▼─────┐                      │
│              │  Watchdog │                      │
│              │   Core    │                      │
│              └─────┬─────┘                      │
│                    │                            │
│    ┌───────────────┼───────────────┐           │
│    │               │               │           │
│ ┌──▼──┐       ┌───▼───┐      ┌───▼───┐       │
│ │Slack│       │Telegram│      │Webhook│        │
│ └─────┘       └───────┘      └───────┘        │
└─────────────────────────────────────────────────┘
```

## Contributing

Contributions are welcome. Please feel free to submit a pull request.

```bash
# Setup development environment
git clone https://github.com/tommieseals/service-watchdog.git
cd service-watchdog
pip install -e ".[dev]"

# Run tests
pytest

# Format code
black src/ tests/
ruff check src/ tests/

# Type check
mypy src/
```

CI runs `ruff`, `black --check`, `mypy`, and `pytest` on Linux and Windows
across Python 3.10-3.12; pull requests need a green run.

## About this repo

Published as a curated snapshot of tooling I maintain; history was
consolidated for publication.

## License

MIT License - see [LICENSE](LICENSE) for details.
