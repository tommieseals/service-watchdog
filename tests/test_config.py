"""Tests for configuration handling."""

import tempfile
from pathlib import Path

import pytest

from service_watchdog.config import ServiceConfig, WatchdogConfig


class TestServiceConfig:
    """Test ServiceConfig validation."""

    def test_valid_config_with_process_name(self):
        """Valid config with process name detection."""
        config = ServiceConfig(
            name="test-service",
            process_name="nginx",
            restart_command="systemctl restart nginx",
        )
        errors = config.validate()
        assert errors == []

    def test_valid_config_with_port(self):
        """Valid config with port detection."""
        config = ServiceConfig(
            name="test-service",
            port=8080,
            restart_command="systemctl restart app",
        )
        errors = config.validate()
        assert errors == []

    def test_valid_config_with_health_url(self):
        """Valid config with health URL detection."""
        config = ServiceConfig(
            name="test-service",
            health_url="http://localhost/health",
            start_command="./start.sh",
        )
        errors = config.validate()
        assert errors == []

    def test_invalid_config_no_detection(self):
        """Invalid config without detection method."""
        config = ServiceConfig(
            name="test-service",
            restart_command="systemctl restart app",
        )
        errors = config.validate()
        assert len(errors) == 1
        assert "detection method" in errors[0].lower()

    def test_invalid_config_no_restart(self):
        """Invalid config without restart command."""
        config = ServiceConfig(
            name="test-service",
            port=8080,
        )
        errors = config.validate()
        assert len(errors) == 1
        assert "restart_command" in errors[0] or "start_command" in errors[0]


class TestWatchdogConfig:
    """Test WatchdogConfig loading and validation."""

    def test_load_from_yaml(self):
        """Load config from YAML file."""
        yaml_content = """
log_level: DEBUG
services:
  - name: test-app
    port: 3000
    restart_command: systemctl restart test-app
notifiers:
  - type: telegram
    bot_token: "123:ABC"
    chat_id: "12345"
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()

            config = WatchdogConfig.from_yaml(f.name)

            assert config.log_level == "DEBUG"
            assert len(config.services) == 1
            assert config.services[0].name == "test-app"
            assert config.services[0].port == 3000
            assert len(config.notifiers) == 1
            assert config.notifiers[0].type == "telegram"

            Path(f.name).unlink()

    def test_validate_empty_services(self):
        """Validate error when no services configured."""
        config = WatchdogConfig()
        errors = config.validate()
        assert len(errors) >= 1
        assert any("service" in e.lower() for e in errors)

    def test_validate_with_valid_services(self):
        """Validate passes with valid services."""
        config = WatchdogConfig(
            services=[
                ServiceConfig(
                    name="test",
                    port=8080,
                    restart_command="restart.sh",
                )
            ]
        )
        errors = config.validate()
        assert errors == []

    def test_to_dict(self):
        """Export config to dictionary."""
        config = WatchdogConfig(
            log_level="DEBUG",
            services=[
                ServiceConfig(
                    name="test",
                    port=8080,
                    restart_command="restart.sh",
                )
            ],
        )
        data = config.to_dict()

        assert data["log_level"] == "DEBUG"
        assert len(data["services"]) == 1
        assert data["services"][0]["name"] == "test"


class TestConfigFromDict:
    """Test config creation from dictionary."""

    def test_minimal_config(self):
        """Create config from minimal dictionary."""
        data = {
            "services": [
                {
                    "name": "app",
                    "port": 3000,
                    "restart_command": "restart.sh",
                }
            ]
        }
        config = WatchdogConfig.from_dict(data)

        assert len(config.services) == 1
        assert config.services[0].name == "app"
        # Check defaults
        assert config.services[0].check_interval == 30
        assert config.services[0].failure_threshold == 2

    def test_full_config(self):
        """Create config with all options."""
        data = {
            "log_file": "/custom/log.txt",
            "log_level": "WARNING",
            "dry_run": True,
            "services": [
                {
                    "name": "full-app",
                    "enabled": False,
                    "process_name": "myapp",
                    "port": 8080,
                    "health_url": "http://localhost:8080/health",
                    "restart_command": "restart.sh",
                    "restart_delay": 120,
                    "max_restarts": 5,
                    "restart_window": 7200,
                    "check_interval": 60,
                    "failure_threshold": 5,
                    "env": {"KEY": "value"},
                }
            ],
            "notifiers": [
                {
                    "type": "webhook",
                    "url": "https://example.com/hook",
                    "on_failure": True,
                    "on_recovery": False,
                }
            ],
        }
        config = WatchdogConfig.from_dict(data)

        assert config.log_file == "/custom/log.txt"
        assert config.log_level == "WARNING"
        assert config.dry_run is True

        svc = config.services[0]
        assert svc.enabled is False
        assert svc.restart_delay == 120
        assert svc.max_restarts == 5
        assert svc.env == {"KEY": "value"}

        notif = config.notifiers[0]
        assert notif.type == "webhook"
        assert notif.on_failure is True
        assert notif.on_recovery is False
