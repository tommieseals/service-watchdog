"""Command-line interface for Service Watchdog."""

import json
import os
import sys
from pathlib import Path

import click

from .config import WatchdogConfig
from .watchdog import ServiceWatchdog


@click.group()
@click.version_option(package_name="service-watchdog")
def main():
    """Service Watchdog - Monitor and auto-restart services."""
    pass


@main.command()
@click.option(
    "-c", "--config", "config_path",
    type=click.Path(exists=True),
    required=True,
    help="Path to configuration file (YAML)",
)
@click.option(
    "-d", "--daemon",
    is_flag=True,
    help="Run as daemon (background process)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Dry-run mode (no actual restarts)",
)
@click.option(
    "-v", "--verbose",
    is_flag=True,
    help="Enable verbose logging",
)
def run(config_path: str, daemon: bool, dry_run: bool, verbose: bool):
    """Start the watchdog daemon."""
    try:
        config = WatchdogConfig.from_yaml(config_path)
    except Exception as e:
        click.echo(f"Error loading config: {e}", err=True)
        sys.exit(1)

    if dry_run:
        config.dry_run = True

    if verbose:
        config.log_level = "DEBUG"

    if daemon:
        config.daemon = True
        _daemonize()

    # Validate config
    errors = config.validate()
    if errors:
        click.echo("Configuration errors:", err=True)
        for error in errors:
            click.echo(f"  - {error}", err=True)
        sys.exit(1)

    watchdog = ServiceWatchdog(config)
    watchdog.run()


@main.command()
@click.option(
    "-c", "--config", "config_path",
    type=click.Path(exists=True),
    required=True,
    help="Path to configuration file (YAML)",
)
def validate(config_path: str):
    """Validate configuration file."""
    try:
        config = WatchdogConfig.from_yaml(config_path)
        errors = config.validate()

        if errors:
            click.echo("❌ Configuration has errors:", err=True)
            for error in errors:
                click.echo(f"  - {error}", err=True)
            sys.exit(1)
        else:
            click.echo("✅ Configuration is valid")
            click.echo(f"\nServices configured: {len(config.services)}")
            for svc in config.services:
                status = "enabled" if svc.enabled else "disabled"
                click.echo(f"  - {svc.name} ({status})")
            click.echo(f"\nNotifiers configured: {len(config.notifiers)}")
            for notif in config.notifiers:
                status = "enabled" if notif.enabled else "disabled"
                click.echo(f"  - {notif.type} ({status})")

    except Exception as e:
        click.echo(f"❌ Error loading config: {e}", err=True)
        sys.exit(1)


@main.command()
@click.option(
    "-c", "--config", "config_path",
    type=click.Path(exists=True),
    required=True,
    help="Path to configuration file (YAML)",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def status(config_path: str, as_json: bool):
    """Show status of monitored services."""
    try:
        config = WatchdogConfig.from_yaml(config_path)
        watchdog = ServiceWatchdog(config)
        result = watchdog.status()

        if as_json:
            click.echo(json.dumps(result, indent=2))
        else:
            click.echo("Service Watchdog Status")
            click.echo("=" * 50)

            for name, svc_status in result["services"].items():
                if svc_status["healthy"]:
                    icon = "🟢"
                elif svc_status["running"]:
                    icon = "🟡"
                else:
                    icon = "🔴"

                click.echo(f"\n{icon} {name}")
                click.echo(f"   Running: {svc_status['running']}")
                click.echo(f"   Healthy: {svc_status['healthy']}")
                if svc_status["pid"]:
                    click.echo(f"   PID: {svc_status['pid']}")
                if svc_status["error"]:
                    click.echo(f"   Error: {svc_status['error']}")
                click.echo(f"   Check method: {svc_status['check_method']}")
                click.echo(f"   Failures: {svc_status['consecutive_failures']}")
                click.echo(f"   Restarts: {svc_status['restart_count']}")

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@main.command()
@click.option(
    "-c", "--config", "config_path",
    type=click.Path(exists=True),
    required=True,
    help="Path to configuration file (YAML)",
)
@click.argument("service_name")
def restart(config_path: str, service_name: str):
    """Manually restart a service."""
    try:
        config = WatchdogConfig.from_yaml(config_path)

        svc_config = None
        for svc in config.services:
            if svc.name == service_name:
                svc_config = svc
                break

        if not svc_config:
            click.echo(f"Service not found: {service_name}", err=True)
            sys.exit(1)

        from .monitor import ServiceController
        controller = ServiceController(svc_config)
        success, message = controller.restart()

        if success:
            click.echo(f"✅ {message}")
        else:
            click.echo(f"❌ {message}", err=True)
            sys.exit(1)

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@main.command()
@click.option("-o", "--output", type=click.Path(), help="Output file path")
def init(output: str):
    """Generate a sample configuration file."""
    sample_config = '''# Service Watchdog Configuration
# Documentation: https://github.com/tommieseals/service-watchdog

# Global settings
log_file: /var/log/service-watchdog.log
log_level: INFO
pid_file: /var/run/service-watchdog.pid
state_file: /var/lib/service-watchdog/state.json

# Services to monitor
services:
  - name: nginx
    enabled: true
    # Detection methods (use at least one)
    process_name: nginx
    port: 80
    health_url: http://localhost/health

    # Restart configuration
    restart_command: systemctl restart nginx
    restart_delay: 60        # seconds to wait before restart
    max_restarts: 3          # max restarts within window
    restart_window: 3600     # window in seconds (1 hour)

    # Check settings
    check_interval: 30       # seconds between checks
    failure_threshold: 2     # failures before action

  - name: postgres
    enabled: true
    port: 5432
    restart_command: systemctl restart postgresql
    check_interval: 30
    failure_threshold: 3
    restart_delay: 30

  - name: my-app
    enabled: true
    pid_file: /var/run/my-app.pid
    health_url: http://localhost:3000/health
    restart_command: systemctl restart my-app
    working_dir: /opt/my-app
    env:
      NODE_ENV: production

# Notification channels
notifiers:
  - type: telegram
    enabled: true
    bot_token: ${TELEGRAM_BOT_TOKEN}
    chat_id: ${TELEGRAM_CHAT_ID}
    on_failure: true
    on_recovery: true
    on_restart: true

  - type: slack
    enabled: false
    webhook_url: ${SLACK_WEBHOOK_URL}

  - type: email
    enabled: false
    smtp_host: smtp.gmail.com
    smtp_port: 587
    smtp_user: ${SMTP_USER}
    smtp_password: ${SMTP_PASSWORD}
    from_addr: watchdog@example.com
    to_addrs:
      - admin@example.com

  - type: webhook
    enabled: false
    url: https://your-webhook.com/alerts
    method: POST
    headers:
      Authorization: Bearer ${WEBHOOK_TOKEN}
'''

    if output:
        Path(output).write_text(sample_config)
        click.echo(f"✅ Sample config written to: {output}")
    else:
        click.echo(sample_config)


def _daemonize():
    """Fork process to run as daemon."""
    # First fork
    try:
        pid = os.fork()
        if pid > 0:
            sys.exit(0)
    except OSError as e:
        sys.stderr.write(f"Fork #1 failed: {e}\n")
        sys.exit(1)

    # Decouple from parent environment
    os.chdir("/")
    os.setsid()
    os.umask(0)

    # Second fork
    try:
        pid = os.fork()
        if pid > 0:
            sys.exit(0)
    except OSError as e:
        sys.stderr.write(f"Fork #2 failed: {e}\n")
        sys.exit(1)

    # Redirect standard file descriptors
    sys.stdout.flush()
    sys.stderr.flush()

    with open("/dev/null", "r") as devnull:
        os.dup2(devnull.fileno(), sys.stdin.fileno())
    with open("/dev/null", "a+") as devnull:
        os.dup2(devnull.fileno(), sys.stdout.fileno())
        os.dup2(devnull.fileno(), sys.stderr.fileno())


# Alias for watchdog-ctl
def ctl():
    """Alias entry point for watchdog-ctl."""
    main()


if __name__ == "__main__":
    main()
