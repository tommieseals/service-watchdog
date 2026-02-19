"""Service monitoring logic."""

from __future__ import annotations

import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

import psutil
import requests

from .config import ServiceConfig


@dataclass
class ServiceStatus:
    """Status of a monitored service."""

    name: str
    running: bool
    pid: Optional[int] = None
    cpu_percent: Optional[float] = None
    memory_mb: Optional[float] = None
    uptime_seconds: Optional[float] = None
    check_method: str = "unknown"
    error: Optional[str] = None

    @property
    def healthy(self) -> bool:
        """Check if service is healthy."""
        return self.running and self.error is None


class ServiceMonitor:
    """Monitor individual services using various detection methods."""

    def __init__(self, config: ServiceConfig):
        self.config = config

    def check(self) -> ServiceStatus:
        """Check if service is running using configured methods."""
        status = ServiceStatus(name=self.config.name, running=False)

        # Try each detection method in order of preference
        if self.config.health_url:
            status = self._check_health_url(status)
            if status.running:
                return status

        if self.config.port:
            status = self._check_port(status)
            if status.running:
                return status

        if self.config.pid_file:
            status = self._check_pid_file(status)
            if status.running:
                return status

        if self.config.process_name:
            status = self._check_process_name(status)
            if status.running:
                return status

        return status

    def _check_process_name(self, status: ServiceStatus) -> ServiceStatus:
        """Check if process is running by name."""
        status.check_method = "process_name"

        for proc in psutil.process_iter(["name", "pid", "cpu_percent", "memory_info", "create_time"]):
            try:
                if proc.info["name"] == self.config.process_name:
                    status.running = True
                    status.pid = proc.info["pid"]
                    status.cpu_percent = proc.info["cpu_percent"]
                    if proc.info["memory_info"]:
                        status.memory_mb = proc.info["memory_info"].rss / (1024 * 1024)
                    if proc.info["create_time"]:
                        import time
                        status.uptime_seconds = time.time() - proc.info["create_time"]
                    return status
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        return status

    def _check_pid_file(self, status: ServiceStatus) -> ServiceStatus:
        """Check if process is running using PID file."""
        status.check_method = "pid_file"
        pid_path = Path(self.config.pid_file)

        if not pid_path.exists():
            status.error = f"PID file not found: {pid_path}"
            return status

        try:
            pid = int(pid_path.read_text().strip())
            if psutil.pid_exists(pid):
                proc = psutil.Process(pid)
                status.running = True
                status.pid = pid
                status.cpu_percent = proc.cpu_percent()
                status.memory_mb = proc.memory_info().rss / (1024 * 1024)
                status.uptime_seconds = proc.create_time()
            else:
                status.error = f"PID {pid} not running (stale PID file)"
        except ValueError:
            status.error = f"Invalid PID file: {pid_path}"
        except psutil.NoSuchProcess:
            status.error = f"Process {pid} not found"

        return status

    def _check_port(self, status: ServiceStatus) -> ServiceStatus:
        """Check if service is listening on configured port."""
        status.check_method = "port"

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)

        try:
            result = sock.connect_ex(("127.0.0.1", self.config.port))
            status.running = result == 0
            if not status.running:
                status.error = f"Port {self.config.port} not listening"
        except socket.error as e:
            status.error = f"Socket error: {e}"
        finally:
            sock.close()

        # Try to find the process using this port (may require elevated permissions)
        if status.running:
            try:
                for conn in psutil.net_connections(kind="inet"):
                    if conn.laddr.port == self.config.port and conn.status == "LISTEN":
                        try:
                            proc = psutil.Process(conn.pid)
                            status.pid = conn.pid
                            status.cpu_percent = proc.cpu_percent()
                            status.memory_mb = proc.memory_info().rss / (1024 * 1024)
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
                        break
            except psutil.AccessDenied:
                # macOS and some Linux systems require root to enumerate connections
                pass

        return status

    def _check_health_url(self, status: ServiceStatus) -> ServiceStatus:
        """Check service health via HTTP endpoint."""
        status.check_method = "health_url"

        try:
            response = requests.get(
                self.config.health_url,
                timeout=self.config.health_timeout,
            )
            status.running = response.status_code < 500
            if not status.running:
                status.error = f"Health check returned {response.status_code}"
        except requests.Timeout:
            status.error = f"Health check timed out after {self.config.health_timeout}s"
        except requests.RequestException as e:
            status.error = f"Health check failed: {e}"

        return status


class ServiceController:
    """Control service lifecycle (start/stop/restart)."""

    def __init__(self, config: ServiceConfig, dry_run: bool = False):
        self.config = config
        self.dry_run = dry_run

    def start(self) -> tuple[bool, str]:
        """Start the service."""
        cmd = self.config.start_command or self.config.restart_command
        if not cmd:
            return False, "No start command configured"

        return self._run_command(cmd, "start")

    def stop(self) -> tuple[bool, str]:
        """Stop the service."""
        cmd = self.config.stop_command
        if not cmd:
            return False, "No stop command configured"

        return self._run_command(cmd, "stop")

    def restart(self) -> tuple[bool, str]:
        """Restart the service."""
        cmd = self.config.restart_command
        if cmd:
            return self._run_command(cmd, "restart")

        # Fallback to stop + start
        if self.config.stop_command:
            success, msg = self.stop()
            if not success:
                return False, f"Stop failed: {msg}"

        return self.start()

    def _run_command(self, cmd: str, action: str) -> tuple[bool, str]:
        """Execute a command."""
        if self.dry_run:
            return True, f"[DRY-RUN] Would execute: {cmd}"

        try:
            env = dict(subprocess.os.environ)
            env.update(self.config.env)

            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                cwd=self.config.working_dir,
                env=env,
                timeout=60,
            )

            if result.returncode == 0:
                return True, f"{action.capitalize()} successful"
            else:
                return False, f"{action.capitalize()} failed: {result.stderr}"

        except subprocess.TimeoutExpired:
            return False, f"{action.capitalize()} command timed out"
        except Exception as e:
            return False, f"{action.capitalize()} error: {e}"
