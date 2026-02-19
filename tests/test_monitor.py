"""Tests for service monitoring."""

import socket
from unittest.mock import MagicMock, patch

import pytest

from service_watchdog.config import ServiceConfig
from service_watchdog.monitor import ServiceController, ServiceMonitor, ServiceStatus


class TestServiceStatus:
    """Test ServiceStatus dataclass."""

    def test_healthy_when_running(self):
        """Service is healthy when running without errors."""
        status = ServiceStatus(name="test", running=True)
        assert status.healthy is True

    def test_unhealthy_when_not_running(self):
        """Service is unhealthy when not running."""
        status = ServiceStatus(name="test", running=False)
        assert status.healthy is False

    def test_unhealthy_with_error(self):
        """Service is unhealthy when running but has error."""
        status = ServiceStatus(name="test", running=True, error="Connection refused")
        assert status.healthy is False


class TestServiceMonitor:
    """Test ServiceMonitor class."""

    def test_check_by_process_name(self):
        """Check service by process name."""
        config = ServiceConfig(
            name="test",
            process_name="nonexistent_process_12345",
            restart_command="restart.sh",
        )
        monitor = ServiceMonitor(config)
        status = monitor.check()

        assert status.running is False
        assert status.check_method == "process_name"

    def test_check_by_port_closed(self):
        """Check service by port when port is closed."""
        config = ServiceConfig(
            name="test",
            port=59999,  # Unlikely to be in use
            restart_command="restart.sh",
        )
        monitor = ServiceMonitor(config)
        status = monitor.check()

        assert status.running is False
        assert status.check_method == "port"
        assert "not listening" in status.error.lower()

    def test_check_by_port_open(self):
        """Check service by port when port is open."""
        # Create a temporary server
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.listen(1)

        try:
            config = ServiceConfig(
                name="test",
                port=port,
                restart_command="restart.sh",
            )
            monitor = ServiceMonitor(config)
            status = monitor.check()

            assert status.running is True
            assert status.check_method == "port"
        finally:
            sock.close()

    @patch("service_watchdog.monitor.requests.get")
    def test_check_by_health_url_success(self, mock_get):
        """Check service by health URL - success."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        config = ServiceConfig(
            name="test",
            health_url="http://localhost/health",
            restart_command="restart.sh",
        )
        monitor = ServiceMonitor(config)
        status = monitor.check()

        assert status.running is True
        assert status.check_method == "health_url"

    @patch("service_watchdog.monitor.requests.get")
    def test_check_by_health_url_failure(self, mock_get):
        """Check service by health URL - failure."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_get.return_value = mock_response

        config = ServiceConfig(
            name="test",
            health_url="http://localhost/health",
            restart_command="restart.sh",
        )
        monitor = ServiceMonitor(config)
        status = monitor.check()

        assert status.running is False
        assert "500" in status.error

    def test_check_by_pid_file_missing(self):
        """Check service by PID file when file doesn't exist."""
        config = ServiceConfig(
            name="test",
            pid_file="/nonexistent/path/test.pid",
            restart_command="restart.sh",
        )
        monitor = ServiceMonitor(config)
        status = monitor.check()

        assert status.running is False
        assert status.check_method == "pid_file"
        assert "not found" in status.error.lower()


class TestServiceController:
    """Test ServiceController class."""

    def test_restart_dry_run(self):
        """Restart in dry-run mode."""
        config = ServiceConfig(
            name="test",
            port=8080,
            restart_command="systemctl restart test",
        )
        controller = ServiceController(config, dry_run=True)
        success, message = controller.restart()

        assert success is True
        assert "DRY-RUN" in message
        assert "systemctl restart test" in message

    def test_start_dry_run(self):
        """Start in dry-run mode."""
        config = ServiceConfig(
            name="test",
            port=8080,
            start_command="./start.sh",
        )
        controller = ServiceController(config, dry_run=True)
        success, message = controller.start()

        assert success is True
        assert "DRY-RUN" in message

    def test_no_restart_command(self):
        """Error when no restart command configured."""
        config = ServiceConfig(
            name="test",
            port=8080,
            restart_command=None,
            start_command=None,
        )
        controller = ServiceController(config)
        success, message = controller.restart()

        assert success is False
        assert "no" in message.lower()

    @patch("subprocess.run")
    def test_restart_success(self, mock_run):
        """Successful restart execution."""
        mock_run.return_value = MagicMock(returncode=0, stderr="")

        config = ServiceConfig(
            name="test",
            port=8080,
            restart_command="systemctl restart test",
        )
        controller = ServiceController(config, dry_run=False)
        success, message = controller.restart()

        assert success is True
        mock_run.assert_called_once()

    @patch("subprocess.run")
    def test_restart_failure(self, mock_run):
        """Failed restart execution."""
        mock_run.return_value = MagicMock(returncode=1, stderr="Service not found")

        config = ServiceConfig(
            name="test",
            port=8080,
            restart_command="systemctl restart test",
        )
        controller = ServiceController(config, dry_run=False)
        success, message = controller.restart()

        assert success is False
        assert "failed" in message.lower()
