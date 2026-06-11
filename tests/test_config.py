"""Tests for configuration handling."""

import pytest

from service_watchdog.config import ServiceConfig, WatchdogConfig, interpolate_env


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

    def test_load_from_yaml(self, tmp_path):
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
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml_content)

        config = WatchdogConfig.from_yaml(config_file)

        assert config.log_level == "DEBUG"
        assert len(config.services) == 1
        assert config.services[0].name == "test-app"
        assert config.services[0].port == 3000
        assert len(config.notifiers) == 1
        assert config.notifiers[0].type == "telegram"

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


class TestEnvInterpolation:
    """Test ${VAR} environment variable interpolation in config loading."""

    def test_env_var_present(self, monkeypatch):
        """${VAR} is replaced with the environment value."""
        monkeypatch.setenv("WD_TEST_TOKEN", "123:ABC")
        monkeypatch.setenv("WD_TEST_CHAT", "98765")

        config = WatchdogConfig.from_dict(
            {
                "services": [{"name": "app", "port": 3000, "restart_command": "restart.sh"}],
                "notifiers": [
                    {
                        "type": "telegram",
                        "bot_token": "${WD_TEST_TOKEN}",
                        "chat_id": "${WD_TEST_CHAT}",
                    }
                ],
            }
        )

        assert config.notifiers[0].bot_token == "123:ABC"
        assert config.notifiers[0].chat_id == "98765"

    def test_env_var_missing_raises(self, monkeypatch):
        """A reference to an unset variable raises a clear error."""
        monkeypatch.delenv("WD_TEST_MISSING", raising=False)

        with pytest.raises(ValueError, match="WD_TEST_MISSING"):
            WatchdogConfig.from_dict(
                {"notifiers": [{"type": "telegram", "bot_token": "${WD_TEST_MISSING}"}]}
            )

    def test_nested_values_interpolated(self, monkeypatch):
        """Placeholders inside nested dicts and lists are resolved."""
        monkeypatch.setenv("WD_TEST_API_TOKEN", "s3cret")
        monkeypatch.setenv("WD_TEST_NODE_ENV", "production")
        monkeypatch.setenv("WD_TEST_ONCALL", "oncall@example.com")

        config = WatchdogConfig.from_dict(
            {
                "services": [
                    {
                        "name": "app",
                        "port": 3000,
                        "restart_command": "restart.sh",
                        "env": {"NODE_ENV": "${WD_TEST_NODE_ENV}"},
                    }
                ],
                "notifiers": [
                    {
                        "type": "webhook",
                        "url": "https://example.com/hook",
                        "headers": {"Authorization": "Bearer ${WD_TEST_API_TOKEN}"},
                    },
                    {
                        "type": "email",
                        "smtp_host": "smtp.example.com",
                        "to_addrs": ["admin@example.com", "${WD_TEST_ONCALL}"],
                    },
                ],
            }
        )

        assert config.services[0].env == {"NODE_ENV": "production"}
        assert config.notifiers[0].headers == {"Authorization": "Bearer s3cret"}
        assert config.notifiers[1].to_addrs == ["admin@example.com", "oncall@example.com"]

    def test_multiple_refs_in_one_string(self, monkeypatch):
        """Several placeholders in a single string are all resolved."""
        monkeypatch.setenv("WD_TEST_USER", "alice")
        monkeypatch.setenv("WD_TEST_PASS", "hunter2")

        result = interpolate_env("${WD_TEST_USER}:${WD_TEST_PASS}@host")
        assert result == "alice:hunter2@host"

    def test_non_string_values_unchanged(self):
        """Ints, bools, and None pass through untouched."""
        assert interpolate_env(587) == 587
        assert interpolate_env(True) is True
        assert interpolate_env(None) is None

    def test_strings_without_placeholders_unchanged(self):
        """Plain strings (including bare $VAR without braces) are untouched."""
        assert interpolate_env("no placeholders here") == "no placeholders here"
        assert interpolate_env("echo $HOME") == "echo $HOME"

    def test_from_yaml_interpolates(self, tmp_path, monkeypatch):
        """Interpolation applies when loading from a YAML file."""
        monkeypatch.setenv("WD_TEST_SMTP_PASSWORD", "yaml-secret")
        yaml_content = """
services:
  - name: app
    port: 3000
    restart_command: restart.sh
notifiers:
  - type: email
    smtp_host: smtp.example.com
    smtp_password: ${WD_TEST_SMTP_PASSWORD}
"""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml_content)

        config = WatchdogConfig.from_yaml(config_file)
        assert config.notifiers[0].smtp_password == "yaml-secret"
