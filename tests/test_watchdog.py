"""Tests for the watchdog core: thresholds, flap protection, state persistence."""

import logging
import time
from unittest.mock import MagicMock, patch

import pytest

from service_watchdog.config import ServiceConfig, WatchdogConfig
from service_watchdog.monitor import ServiceStatus
from service_watchdog.notifiers import NotificationEvent
from service_watchdog.watchdog import ServiceState, ServiceWatchdog, WatchdogState


@pytest.fixture(autouse=True)
def _clean_logger():
    """Remove handlers added by ServiceWatchdog so log files are released."""
    yield
    wd_logger = logging.getLogger("service-watchdog")
    for handler in wd_logger.handlers[:]:
        handler.close()
        wd_logger.removeHandler(handler)


def make_config(tmp_path, **service_overrides) -> WatchdogConfig:
    """Build a single-service watchdog config rooted in tmp_path."""
    service = ServiceConfig(
        name="svc",
        port=59998,
        restart_command="restart.sh",
        failure_threshold=3,
        restart_delay=60,
        max_restarts=2,
        restart_window=3600,
        check_interval=0,
    )
    for key, value in service_overrides.items():
        setattr(service, key, value)

    return WatchdogConfig(
        services=[service],
        log_file=str(tmp_path / "wd.log"),
        pid_file=str(tmp_path / "wd.pid"),
        state_file=str(tmp_path / "state.json"),
    )


def failing_status() -> ServiceStatus:
    return ServiceStatus(
        name="svc",
        running=False,
        error="Port 59998 not listening",
        check_method="port",
    )


def healthy_status() -> ServiceStatus:
    return ServiceStatus(name="svc", running=True, check_method="port")


class TestFailureThreshold:
    """Consecutive failure counting and alerting."""

    def test_failures_below_threshold_counted_without_alert(self, tmp_path):
        config = make_config(tmp_path, failure_threshold=3)
        wd = ServiceWatchdog(config)
        wd.notify = MagicMock()
        svc = config.services[0]

        wd.handle_failure(svc, failing_status())
        wd.handle_failure(svc, failing_status())

        state = wd.state.services["svc"]
        assert state.consecutive_failures == 2
        assert state.alerted is False
        assert state.pending_restart_at is None
        wd.notify.assert_not_called()

    def test_alert_and_restart_scheduled_at_threshold(self, tmp_path):
        config = make_config(tmp_path, failure_threshold=2, restart_delay=60)
        wd = ServiceWatchdog(config)
        wd.notify = MagicMock()
        svc = config.services[0]

        before = time.time()
        wd.handle_failure(svc, failing_status())
        wd.handle_failure(svc, failing_status())
        after = time.time()

        state = wd.state.services["svc"]
        assert state.consecutive_failures == 2
        assert state.alerted is True
        assert state.pending_restart_at is not None
        assert before + 60 <= state.pending_restart_at <= after + 60

        wd.notify.assert_called_once()
        event = wd.notify.call_args[0][0]
        assert event.event_type == NotificationEvent.FAILURE
        assert event.service_name == "svc"

    def test_alert_sent_only_once(self, tmp_path):
        config = make_config(tmp_path, failure_threshold=2)
        wd = ServiceWatchdog(config)
        wd.notify = MagicMock()
        svc = config.services[0]

        for _ in range(5):
            wd.handle_failure(svc, failing_status())

        assert wd.state.services["svc"].consecutive_failures == 5
        wd.notify.assert_called_once()

    def test_recovery_resets_state_and_notifies(self, tmp_path):
        config = make_config(tmp_path, failure_threshold=2)
        wd = ServiceWatchdog(config)
        wd.notify = MagicMock()
        svc = config.services[0]

        wd.handle_failure(svc, failing_status())
        wd.handle_failure(svc, failing_status())
        wd.notify.reset_mock()

        wd.handle_recovery(svc, healthy_status())

        state = wd.state.services["svc"]
        assert state.consecutive_failures == 0
        assert state.alerted is False
        assert state.pending_restart_at is None

        wd.notify.assert_called_once()
        event = wd.notify.call_args[0][0]
        assert event.event_type == NotificationEvent.RECOVERY

    def test_recovery_without_prior_failures_is_silent(self, tmp_path):
        config = make_config(tmp_path)
        wd = ServiceWatchdog(config)
        wd.notify = MagicMock()

        wd.handle_recovery(config.services[0], healthy_status())

        wd.notify.assert_not_called()


class TestFlapProtection:
    """Restart-window accounting and max-restart limits."""

    def test_restart_executes_and_increments_count(self, tmp_path):
        config = make_config(tmp_path, max_restarts=2)
        wd = ServiceWatchdog(config)
        wd.notify = MagicMock()
        svc = config.services[0]
        wd.state.services["svc"].pending_restart_at = time.time()

        with patch("service_watchdog.watchdog.ServiceController") as mock_cls:
            mock_cls.return_value.restart.return_value = (True, "Restart successful")
            wd.attempt_restart(svc)

        mock_cls.return_value.restart.assert_called_once()
        state = wd.state.services["svc"]
        assert state.restart_count == 1
        assert state.pending_restart_at is None
        event = wd.notify.call_args[0][0]
        assert event.event_type == NotificationEvent.RESTART

    def test_restarts_blocked_after_max_within_window(self, tmp_path):
        config = make_config(tmp_path, max_restarts=2, restart_window=3600)
        wd = ServiceWatchdog(config)
        wd.notify = MagicMock()
        svc = config.services[0]

        state = wd.state.services["svc"]
        state.restart_window_start = time.time()
        state.restart_count = 2
        state.pending_restart_at = time.time()

        with patch("service_watchdog.watchdog.ServiceController") as mock_cls:
            wd.attempt_restart(svc)

        mock_cls.assert_not_called()
        assert state.restart_count == 2
        assert state.pending_restart_at is None  # gave up, no retry loop
        event = wd.notify.call_args[0][0]
        assert event.event_type == NotificationEvent.RESTART_FAILED

    def test_window_expiry_resets_counter(self, tmp_path):
        config = make_config(tmp_path, max_restarts=2, restart_window=3600)
        wd = ServiceWatchdog(config)
        wd.notify = MagicMock()
        svc = config.services[0]

        state = wd.state.services["svc"]
        state.restart_window_start = time.time() - 3700  # window has elapsed
        state.restart_count = 2

        with patch("service_watchdog.watchdog.ServiceController") as mock_cls:
            mock_cls.return_value.restart.return_value = (True, "Restart successful")
            wd.attempt_restart(svc)

        mock_cls.return_value.restart.assert_called_once()
        assert state.restart_count == 1
        assert state.restart_window_start == pytest.approx(time.time(), abs=5)

    def test_failed_restart_schedules_retry(self, tmp_path):
        config = make_config(tmp_path, restart_delay=30)
        wd = ServiceWatchdog(config)
        wd.notify = MagicMock()
        svc = config.services[0]

        with patch("service_watchdog.watchdog.ServiceController") as mock_cls:
            mock_cls.return_value.restart.return_value = (False, "Restart failed: boom")
            before = time.time()
            wd.attempt_restart(svc)
            after = time.time()

        state = wd.state.services["svc"]
        assert state.restart_count == 1
        assert state.pending_restart_at is not None
        assert before + 30 <= state.pending_restart_at <= after + 30
        event = wd.notify.call_args[0][0]
        assert event.event_type == NotificationEvent.RESTART_FAILED


class TestStatePersistence:
    """Serialization and file round-trips of watchdog state."""

    def test_state_dict_round_trip(self):
        state = WatchdogState(started_at=1700000000.0)
        state.services["svc"] = ServiceState(
            name="svc",
            consecutive_failures=4,
            restart_count=2,
            restart_window_start=1700000100.0,
            last_check=1700000200.0,
            pending_restart_at=1700000300.0,
            alerted=True,
        )

        restored = WatchdogState.from_dict(state.to_dict())

        assert restored.started_at == 1700000000.0
        svc = restored.services["svc"]
        assert svc.consecutive_failures == 4
        assert svc.restart_count == 2
        assert svc.restart_window_start == 1700000100.0
        assert svc.last_check == 1700000200.0
        assert svc.pending_restart_at == 1700000300.0
        assert svc.alerted is True

    def test_save_and_load_state_file(self, tmp_path):
        config = make_config(tmp_path)
        wd1 = ServiceWatchdog(config)
        state = wd1.state.services["svc"]
        state.consecutive_failures = 3
        state.restart_count = 1
        state.alerted = True
        wd1._save_state()

        assert (tmp_path / "state.json").exists()

        wd2 = ServiceWatchdog(config)
        wd2._load_state()

        restored = wd2.state.services["svc"]
        assert restored.consecutive_failures == 3
        assert restored.restart_count == 1
        assert restored.alerted is True

    def test_save_state_skipped_in_dry_run(self, tmp_path):
        config = make_config(tmp_path)
        config.dry_run = True
        wd = ServiceWatchdog(config)
        wd._save_state()

        assert not (tmp_path / "state.json").exists()


class TestRunOnce:
    """End-to-end check cycle with mocked process checks."""

    def test_failure_to_restart_cycle(self, tmp_path):
        config = make_config(tmp_path, failure_threshold=2, restart_delay=0, check_interval=0)
        wd = ServiceWatchdog(config)
        wd.notify = MagicMock()

        with (
            patch("service_watchdog.watchdog.ServiceMonitor") as mock_monitor_cls,
            patch("service_watchdog.watchdog.ServiceController") as mock_ctl_cls,
        ):
            mock_monitor_cls.return_value.check.return_value = failing_status()
            mock_ctl_cls.return_value.restart.return_value = (True, "Restart successful")

            wd.run_once()  # failure 1 of 2
            assert wd.state.services["svc"].consecutive_failures == 1

            wd.run_once()  # failure 2: alert + schedule immediate restart
            state = wd.state.services["svc"]
            assert state.alerted is True
            assert state.pending_restart_at is not None

            wd.run_once()  # pending restart is due: restart attempted
            assert state.restart_count == 1
            assert state.pending_restart_at is None

        mock_ctl_cls.return_value.restart.assert_called_once()
        assert (tmp_path / "state.json").exists()

    def test_disabled_service_not_checked(self, tmp_path):
        config = make_config(tmp_path, enabled=False)
        wd = ServiceWatchdog(config)

        with patch("service_watchdog.watchdog.ServiceMonitor") as mock_monitor_cls:
            wd.run_once()

        mock_monitor_cls.assert_not_called()
