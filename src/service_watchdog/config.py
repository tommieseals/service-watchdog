"""Configuration management for Service Watchdog."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union

import yaml


@dataclass
class ServiceConfig:
    """Configuration for a single monitored service."""

    name: str
    enabled: bool = True

    # Detection methods (at least one required)
    process_name: Optional[str] = None
    pid_file: Optional[str] = None
    port: Optional[int] = None
    health_url: Optional[str] = None
    health_timeout: int = 10

    # Restart configuration
    restart_command: Optional[str] = None
    stop_command: Optional[str] = None
    start_command: Optional[str] = None
    working_dir: Optional[str] = None
    restart_delay: int = 60  # seconds to wait before restarting
    max_restarts: int = 3  # max restarts within window
    restart_window: int = 3600  # window in seconds (1 hour)

    # Check intervals
    check_interval: int = 30  # seconds between checks
    failure_threshold: int = 2  # consecutive failures before action

    # Environment
    env: dict = field(default_factory=dict)

    def validate(self) -> list[str]:
        """Validate service configuration, return list of errors."""
        errors = []

        if not any([self.process_name, self.pid_file, self.port, self.health_url]):
            errors.append(f"Service '{self.name}': At least one detection method required")

        if self.restart_command is None and self.start_command is None:
            errors.append(f"Service '{self.name}': restart_command or start_command required")

        return errors


@dataclass
class NotifierConfig:
    """Configuration for a notification channel."""

    type: str  # telegram, slack, email, webhook
    enabled: bool = True

    # Telegram
    bot_token: Optional[str] = None
    chat_id: Optional[str] = None

    # Slack
    webhook_url: Optional[str] = None
    channel: Optional[str] = None

    # Email
    smtp_host: Optional[str] = None
    smtp_port: int = 587
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    from_addr: Optional[str] = None
    to_addrs: list[str] = field(default_factory=list)

    # Webhook
    url: Optional[str] = None
    method: str = "POST"
    headers: dict = field(default_factory=dict)

    # Common
    on_failure: bool = True
    on_recovery: bool = True
    on_restart: bool = True


@dataclass
class WatchdogConfig:
    """Main configuration for the watchdog daemon."""

    services: list[ServiceConfig] = field(default_factory=list)
    notifiers: list[NotifierConfig] = field(default_factory=list)

    # Global settings
    log_file: str = "/var/log/service-watchdog.log"
    log_level: str = "INFO"
    pid_file: str = "/var/run/service-watchdog.pid"
    state_file: str = "/var/lib/service-watchdog/state.json"

    # Daemon settings
    dry_run: bool = False
    daemon: bool = False

    @classmethod
    def from_yaml(cls, path: Union[str, Path]) -> "WatchdogConfig":
        """Load configuration from YAML file."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        with open(path) as f:
            data = yaml.safe_load(f)

        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WatchdogConfig":
        """Create configuration from dictionary."""
        config = cls()

        # Parse global settings
        config.log_file = data.get("log_file", config.log_file)
        config.log_level = data.get("log_level", config.log_level)
        config.pid_file = data.get("pid_file", config.pid_file)
        config.state_file = data.get("state_file", config.state_file)
        config.dry_run = data.get("dry_run", config.dry_run)
        config.daemon = data.get("daemon", config.daemon)

        # Parse services
        for svc_data in data.get("services", []):
            svc = ServiceConfig(
                name=svc_data["name"],
                enabled=svc_data.get("enabled", True),
                process_name=svc_data.get("process_name"),
                pid_file=svc_data.get("pid_file"),
                port=svc_data.get("port"),
                health_url=svc_data.get("health_url"),
                health_timeout=svc_data.get("health_timeout", 10),
                restart_command=svc_data.get("restart_command"),
                stop_command=svc_data.get("stop_command"),
                start_command=svc_data.get("start_command"),
                working_dir=svc_data.get("working_dir"),
                restart_delay=svc_data.get("restart_delay", 60),
                max_restarts=svc_data.get("max_restarts", 3),
                restart_window=svc_data.get("restart_window", 3600),
                check_interval=svc_data.get("check_interval", 30),
                failure_threshold=svc_data.get("failure_threshold", 2),
                env=svc_data.get("env", {}),
            )
            config.services.append(svc)

        # Parse notifiers
        for notif_data in data.get("notifiers", []):
            notif = NotifierConfig(
                type=notif_data["type"],
                enabled=notif_data.get("enabled", True),
                bot_token=notif_data.get("bot_token"),
                chat_id=notif_data.get("chat_id"),
                webhook_url=notif_data.get("webhook_url"),
                channel=notif_data.get("channel"),
                smtp_host=notif_data.get("smtp_host"),
                smtp_port=notif_data.get("smtp_port", 587),
                smtp_user=notif_data.get("smtp_user"),
                smtp_password=notif_data.get("smtp_password"),
                from_addr=notif_data.get("from_addr"),
                to_addrs=notif_data.get("to_addrs", []),
                url=notif_data.get("url"),
                method=notif_data.get("method", "POST"),
                headers=notif_data.get("headers", {}),
                on_failure=notif_data.get("on_failure", True),
                on_recovery=notif_data.get("on_recovery", True),
                on_restart=notif_data.get("on_restart", True),
            )
            config.notifiers.append(notif)

        return config

    def validate(self) -> list[str]:
        """Validate configuration, return list of errors."""
        errors = []

        if not self.services:
            errors.append("At least one service must be configured")

        for svc in self.services:
            errors.extend(svc.validate())

        return errors

    def to_dict(self) -> dict[str, Any]:
        """Export configuration to dictionary."""
        return {
            "log_file": self.log_file,
            "log_level": self.log_level,
            "pid_file": self.pid_file,
            "state_file": self.state_file,
            "dry_run": self.dry_run,
            "daemon": self.daemon,
            "services": [
                {
                    "name": s.name,
                    "enabled": s.enabled,
                    "process_name": s.process_name,
                    "pid_file": s.pid_file,
                    "port": s.port,
                    "health_url": s.health_url,
                    "restart_command": s.restart_command,
                    "restart_delay": s.restart_delay,
                    "max_restarts": s.max_restarts,
                    "check_interval": s.check_interval,
                }
                for s in self.services
            ],
            "notifiers": [{"type": n.type, "enabled": n.enabled} for n in self.notifiers],
        }
