"""Main watchdog daemon implementation."""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import ServiceConfig, WatchdogConfig
from .monitor import ServiceController, ServiceMonitor, ServiceStatus
from .notifiers import BaseNotifier, NotificationEvent, NotifierFactory

logger = logging.getLogger("service-watchdog")


@dataclass
class ServiceState:
    """Runtime state for a monitored service."""

    name: str
    consecutive_failures: int = 0
    restart_count: int = 0
    restart_window_start: Optional[float] = None
    last_check: Optional[float] = None
    last_status: Optional[ServiceStatus] = None
    pending_restart_at: Optional[float] = None
    alerted: bool = False


@dataclass
class WatchdogState:
    """Persistent state for the watchdog daemon."""

    services: dict[str, ServiceState] = field(default_factory=dict)
    started_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        """Serialize state to dictionary."""
        return {
            "started_at": self.started_at,
            "services": {
                name: {
                    "consecutive_failures": svc.consecutive_failures,
                    "restart_count": svc.restart_count,
                    "restart_window_start": svc.restart_window_start,
                    "last_check": svc.last_check,
                    "pending_restart_at": svc.pending_restart_at,
                    "alerted": svc.alerted,
                }
                for name, svc in self.services.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WatchdogState":
        """Deserialize state from dictionary."""
        state = cls(started_at=data.get("started_at", time.time()))
        for name, svc_data in data.get("services", {}).items():
            state.services[name] = ServiceState(
                name=name,
                consecutive_failures=svc_data.get("consecutive_failures", 0),
                restart_count=svc_data.get("restart_count", 0),
                restart_window_start=svc_data.get("restart_window_start"),
                last_check=svc_data.get("last_check"),
                pending_restart_at=svc_data.get("pending_restart_at"),
                alerted=svc_data.get("alerted", False),
            )
        return state


class ServiceWatchdog:
    """Main watchdog daemon that monitors and manages services."""

    def __init__(self, config: WatchdogConfig):
        self.config = config
        self.state = WatchdogState()
        self.notifiers: list[BaseNotifier] = []
        self.running = False

        # Initialize state for each service
        for svc in config.services:
            self.state.services[svc.name] = ServiceState(name=svc.name)

        # Initialize notifiers
        for notif_config in config.notifiers:
            try:
                notifier = NotifierFactory.create(notif_config)
                self.notifiers.append(notifier)
            except ValueError as e:
                logger.warning(f"Failed to create notifier: {e}")

        self._setup_logging()

    def _setup_logging(self):
        """Configure logging."""
        level = getattr(logging, self.config.log_level.upper(), logging.INFO)
        logger.setLevel(level)

        # Console handler
        console = logging.StreamHandler()
        console.setLevel(level)
        console.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
        )
        logger.addHandler(console)

        # File handler
        if self.config.log_file and not self.config.dry_run:
            try:
                log_path = Path(self.config.log_file)
                log_path.parent.mkdir(parents=True, exist_ok=True)
                file_handler = logging.FileHandler(log_path)
                file_handler.setLevel(level)
                file_handler.setFormatter(
                    logging.Formatter(
                        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
                    )
                )
                logger.addHandler(file_handler)
            except PermissionError:
                logger.warning(f"Cannot write to log file: {self.config.log_file}")

    def _load_state(self):
        """Load persistent state from file."""
        state_path = Path(self.config.state_file)
        if state_path.exists():
            try:
                with open(state_path) as f:
                    data = json.load(f)
                    self.state = WatchdogState.from_dict(data)
                    logger.info(f"Loaded state from {state_path}")
            except Exception as e:
                logger.warning(f"Failed to load state: {e}")

    def _save_state(self):
        """Save persistent state to file."""
        if self.config.dry_run:
            return

        state_path = Path(self.config.state_file)
        try:
            state_path.parent.mkdir(parents=True, exist_ok=True)
            with open(state_path, "w") as f:
                json.dump(self.state.to_dict(), f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save state: {e}")

    def _write_pid_file(self):
        """Write PID file for daemon mode."""
        if self.config.dry_run:
            return

        pid_path = Path(self.config.pid_file)
        try:
            pid_path.parent.mkdir(parents=True, exist_ok=True)
            pid_path.write_text(str(os.getpid()))
            logger.debug(f"Wrote PID file: {pid_path}")
        except Exception as e:
            logger.warning(f"Failed to write PID file: {e}")

    def _remove_pid_file(self):
        """Remove PID file on shutdown."""
        pid_path = Path(self.config.pid_file)
        try:
            if pid_path.exists():
                pid_path.unlink()
        except Exception:
            pass

    def notify(self, event: NotificationEvent):
        """Send notification to all configured notifiers."""
        for notifier in self.notifiers:
            try:
                success, message = notifier.send(event)
                if success:
                    logger.debug(f"Notification sent via {notifier.config.type}: {message}")
                else:
                    logger.warning(f"Notification failed via {notifier.config.type}: {message}")
            except Exception as e:
                logger.error(f"Notification error ({notifier.config.type}): {e}")

    def check_service(self, svc_config: ServiceConfig) -> ServiceStatus:
        """Check a single service and return its status."""
        monitor = ServiceMonitor(svc_config)
        status = monitor.check()

        state = self.state.services.get(svc_config.name)
        if state:
            state.last_check = time.time()
            state.last_status = status

        return status

    def handle_failure(self, svc_config: ServiceConfig, status: ServiceStatus):
        """Handle service failure detection."""
        state = self.state.services[svc_config.name]
        state.consecutive_failures += 1

        logger.warning(
            f"Service '{svc_config.name}' failure #{state.consecutive_failures} "
            f"(threshold: {svc_config.failure_threshold})"
        )

        # Check if we've hit the failure threshold
        if state.consecutive_failures >= svc_config.failure_threshold:
            if not state.alerted:
                # Send failure notification
                event = NotificationEvent(
                    event_type=NotificationEvent.FAILURE,
                    service_name=svc_config.name,
                    message=f"Service has failed {state.consecutive_failures} consecutive checks.\n"
                    f"Will attempt restart in {svc_config.restart_delay} seconds.",
                    status=status,
                )
                self.notify(event)
                state.alerted = True

            # Schedule restart if not already pending
            if state.pending_restart_at is None:
                state.pending_restart_at = time.time() + svc_config.restart_delay
                logger.info(
                    f"Scheduled restart of '{svc_config.name}' in {svc_config.restart_delay}s"
                )

    def handle_recovery(self, svc_config: ServiceConfig, status: ServiceStatus):
        """Handle service recovery detection."""
        state = self.state.services[svc_config.name]

        if state.consecutive_failures > 0 or state.alerted:
            logger.info(f"Service '{svc_config.name}' recovered")

            # Send recovery notification
            event = NotificationEvent(
                event_type=NotificationEvent.RECOVERY,
                service_name=svc_config.name,
                message="Service is now running normally.",
                status=status,
            )
            self.notify(event)

        # Reset state
        state.consecutive_failures = 0
        state.alerted = False
        state.pending_restart_at = None

    def attempt_restart(self, svc_config: ServiceConfig):
        """Attempt to restart a failed service."""
        state = self.state.services[svc_config.name]
        now = time.time()

        # Check restart window
        if state.restart_window_start is None:
            state.restart_window_start = now
            state.restart_count = 0
        elif now - state.restart_window_start > svc_config.restart_window:
            # Reset window
            state.restart_window_start = now
            state.restart_count = 0

        # Check max restarts
        if state.restart_count >= svc_config.max_restarts:
            logger.error(
                f"Service '{svc_config.name}' exceeded max restarts "
                f"({svc_config.max_restarts}) within window"
            )
            event = NotificationEvent(
                event_type=NotificationEvent.RESTART_FAILED,
                service_name=svc_config.name,
                message=f"Exceeded maximum restart attempts ({svc_config.max_restarts}). "
                f"Manual intervention required.",
            )
            self.notify(event)
            state.pending_restart_at = None  # Stop trying
            return

        # Attempt restart
        controller = ServiceController(svc_config, dry_run=self.config.dry_run)
        success, message = controller.restart()
        state.restart_count += 1
        state.pending_restart_at = None

        if success:
            logger.info(f"Service '{svc_config.name}' restarted: {message}")
            event = NotificationEvent(
                event_type=NotificationEvent.RESTART,
                service_name=svc_config.name,
                message=f"Service restarted successfully.\n"
                f"Restart #{state.restart_count} within current window.",
            )
        else:
            logger.error(f"Failed to restart '{svc_config.name}': {message}")
            event = NotificationEvent(
                event_type=NotificationEvent.RESTART_FAILED,
                service_name=svc_config.name,
                message=f"Restart attempt failed: {message}\n"
                f"Attempt #{state.restart_count} of {svc_config.max_restarts}.",
            )
            # Schedule another restart attempt
            state.pending_restart_at = time.time() + svc_config.restart_delay

        self.notify(event)

    def run_once(self):
        """Run a single check cycle for all services."""
        for svc_config in self.config.services:
            if not svc_config.enabled:
                continue

            state = self.state.services.get(svc_config.name)
            if not state:
                state = ServiceState(name=svc_config.name)
                self.state.services[svc_config.name] = state

            # Check if pending restart is due
            if state.pending_restart_at and time.time() >= state.pending_restart_at:
                self.attempt_restart(svc_config)
                continue

            # Check if it's time for a check
            if state.last_check:
                elapsed = time.time() - state.last_check
                if elapsed < svc_config.check_interval:
                    continue

            # Perform the check
            status = self.check_service(svc_config)

            if status.healthy:
                self.handle_recovery(svc_config, status)
            else:
                self.handle_failure(svc_config, status)

        self._save_state()

    def run(self):
        """Run the watchdog daemon loop."""
        self.running = True
        self._load_state()
        self._write_pid_file()

        # Setup signal handlers
        def handle_signal(signum, frame):
            logger.info(f"Received signal {signum}, shutting down...")
            self.running = False

        signal.signal(signal.SIGTERM, handle_signal)
        signal.signal(signal.SIGINT, handle_signal)

        logger.info("Service Watchdog started")
        if self.config.dry_run:
            logger.info("Running in DRY-RUN mode")

        logger.info(f"Monitoring {len(self.config.services)} services")

        try:
            while self.running:
                self.run_once()
                time.sleep(1)  # Main loop runs every second
        finally:
            self._remove_pid_file()
            logger.info("Service Watchdog stopped")

    def status(self) -> dict:
        """Get current status of all monitored services."""
        result = {
            "watchdog": {
                "running": self.running,
                "started_at": datetime.fromtimestamp(self.state.started_at).isoformat(),
                "dry_run": self.config.dry_run,
            },
            "services": {},
        }

        for svc_config in self.config.services:
            state = self.state.services.get(svc_config.name)
            status = self.check_service(svc_config)

            result["services"][svc_config.name] = {
                "enabled": svc_config.enabled,
                "running": status.running,
                "healthy": status.healthy,
                "pid": status.pid,
                "check_method": status.check_method,
                "error": status.error,
                "consecutive_failures": state.consecutive_failures if state else 0,
                "restart_count": state.restart_count if state else 0,
            }

        return result
