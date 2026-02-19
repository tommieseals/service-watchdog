# 🐕 Service Watchdog

[![CI](https://github.com/tommieseals/service-watchdog/actions/workflows/ci.yml/badge.svg)](https://github.com/tommieseals/service-watchdog/actions/workflows/ci.yml)

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

A production-ready, configurable service monitoring daemon that watches processes, sends alerts on failures, and automatically restarts services.

## ✨ Features

- **🔍 Multiple Detection Methods**
  - Process name matching
  - PID file monitoring
  - Port availability checks
  - HTTP health endpoint validation

- **🔔 Rich Notifications**
  - Telegram (instant mobile alerts)
  - Slack (team channels)
  - Email (SMTP with HTML support)
  - Webhook (integrate with any service)

- **⚡ Smart Restart Logic**
  - Configurable restart delays (prevent flapping)
  - Maximum restart limits per time window
  - Graceful stop → start sequences
  - Environment variable injection

- **🛠️ Production Ready**
  - Systemd service files included
  - macOS launchd support
  - Dry-run mode for testing
  - Persistent state across restarts
  - Structured logging

## 📦 Installation

```bash
# From PyPI
pip install service-watchdog

# From source
git clone https://github.com/tommieseals/service-watchdog.git
cd service-watchdog
pip install -e .
```

## 🚀 Quick Start

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

# As a daemon
service-watchdog run -c /etc/service-watchdog/config.yaml -d
```

### 5. Check status

```bash
service-watchdog status -c /etc/service-watchdog/config.yaml
```

## 📋 Configuration Reference

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

## 🐧 Systemd Installation

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

## 🍎 macOS Installation

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

## 🧪 Dry-Run Mode

Test your configuration without actually restarting services:

```bash
service-watchdog run -c config.yaml --dry-run -v
```

In dry-run mode:
- All checks execute normally
- Notifications are sent (to verify they work)
- **No actual restart commands are executed**
- Logs show what *would* happen

## 📊 Example Configurations

See the [`examples/`](examples/) directory for complete configurations:

- [`nginx.yaml`](examples/nginx.yaml) - Web server monitoring
- [`postgres.yaml`](examples/postgres.yaml) - Database monitoring
- [`node-app.yaml`](examples/node-app.yaml) - Node.js application with PM2
- [`multi-service.yaml`](examples/multi-service.yaml) - Full application stack
- [`docker.yaml`](examples/docker.yaml) - Docker container monitoring

## 🔧 CLI Reference

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

## 🏗️ Architecture

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

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

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

## 📄 License

MIT License - see [LICENSE](LICENSE) for details.

## 🙏 Acknowledgments

Inspired by the need for a simple, reliable process monitor that just works. Built with lessons learned from years of keeping services running in production.

---

Made with ❤️ by [Tommie Seals](https://github.com/tommieseals)
