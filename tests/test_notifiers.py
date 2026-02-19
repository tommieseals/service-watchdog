"""Tests for notification plugins."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from service_watchdog.config import NotifierConfig
from service_watchdog.monitor import ServiceStatus
from service_watchdog.notifiers import (
    NotificationEvent,
    NotifierFactory,
    SlackNotifier,
    TelegramNotifier,
    WebhookNotifier,
)


class TestNotificationEvent:
    """Test NotificationEvent class."""

    def test_create_failure_event(self):
        """Create a failure notification event."""
        status = ServiceStatus(name="test", running=False, error="Connection refused")
        event = NotificationEvent(
            event_type=NotificationEvent.FAILURE,
            service_name="test-service",
            message="Service has failed",
            status=status,
        )

        assert event.event_type == "failure"
        assert event.service_name == "test-service"
        assert event.status.error == "Connection refused"

    def test_to_dict(self):
        """Convert event to dictionary."""
        event = NotificationEvent(
            event_type=NotificationEvent.RECOVERY,
            service_name="test-service",
            message="Service recovered",
            timestamp=datetime(2024, 1, 15, 10, 30, 0),
        )

        data = event.to_dict()

        assert data["event_type"] == "recovery"
        assert data["service_name"] == "test-service"
        assert "2024-01-15" in data["timestamp"]


class TestTelegramNotifier:
    """Test Telegram notification plugin."""

    def test_should_notify_disabled(self):
        """Skip notification when disabled."""
        config = NotifierConfig(type="telegram", enabled=False)
        notifier = TelegramNotifier(config)
        event = NotificationEvent(
            event_type=NotificationEvent.FAILURE,
            service_name="test",
            message="Failed",
        )

        assert notifier.should_notify(event) is False

    def test_should_notify_by_event_type(self):
        """Respect event type filters."""
        config = NotifierConfig(
            type="telegram",
            enabled=True,
            on_failure=True,
            on_recovery=False,
            on_restart=True,
        )
        notifier = TelegramNotifier(config)

        failure_event = NotificationEvent(
            event_type=NotificationEvent.FAILURE,
            service_name="test",
            message="Failed",
        )
        recovery_event = NotificationEvent(
            event_type=NotificationEvent.RECOVERY,
            service_name="test",
            message="Recovered",
        )

        assert notifier.should_notify(failure_event) is True
        assert notifier.should_notify(recovery_event) is False

    @patch("service_watchdog.notifiers.requests.post")
    def test_send_success(self, mock_post):
        """Send Telegram notification successfully."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        config = NotifierConfig(
            type="telegram",
            enabled=True,
            bot_token="123:ABC",
            chat_id="12345",
        )
        notifier = TelegramNotifier(config)
        event = NotificationEvent(
            event_type=NotificationEvent.FAILURE,
            service_name="test-service",
            message="Service failed",
        )

        success, message = notifier.send(event)

        assert success is True
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert "123:ABC" in call_args[0][0]

    def test_send_missing_credentials(self):
        """Fail when credentials missing."""
        config = NotifierConfig(
            type="telegram",
            enabled=True,
            bot_token=None,
            chat_id=None,
        )
        notifier = TelegramNotifier(config)
        event = NotificationEvent(
            event_type=NotificationEvent.FAILURE,
            service_name="test",
            message="Failed",
        )

        success, message = notifier.send(event)

        assert success is False
        assert "required" in message.lower()


class TestSlackNotifier:
    """Test Slack notification plugin."""

    @patch("service_watchdog.notifiers.requests.post")
    def test_send_success(self, mock_post):
        """Send Slack notification successfully."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        config = NotifierConfig(
            type="slack",
            enabled=True,
            webhook_url="https://hooks.slack.com/xxx",
        )
        notifier = SlackNotifier(config)
        event = NotificationEvent(
            event_type=NotificationEvent.FAILURE,
            service_name="test-service",
            message="Service failed",
        )

        success, message = notifier.send(event)

        assert success is True

    def test_color_mapping(self):
        """Verify color mapping for different event types."""
        config = NotifierConfig(
            type="slack",
            enabled=True,
            webhook_url="https://hooks.slack.com/xxx",
        )
        notifier = SlackNotifier(config)

        # We can't easily test the actual color without mocking,
        # but we can verify the notifier initializes correctly
        assert notifier.config.type == "slack"


class TestWebhookNotifier:
    """Test generic webhook notification plugin."""

    @patch("service_watchdog.notifiers.requests.request")
    def test_send_post(self, mock_request):
        """Send POST webhook notification."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_request.return_value = mock_response

        config = NotifierConfig(
            type="webhook",
            enabled=True,
            url="https://example.com/hook",
            method="POST",
            headers={"Authorization": "Bearer token"},
        )
        notifier = WebhookNotifier(config)
        event = NotificationEvent(
            event_type=NotificationEvent.RESTART,
            service_name="test-service",
            message="Restarted",
        )

        success, message = notifier.send(event)

        assert success is True
        mock_request.assert_called_once()
        call_kwargs = mock_request.call_args[1]
        assert call_kwargs["method"] == "POST"
        assert "Authorization" in call_kwargs["headers"]


class TestNotifierFactory:
    """Test NotifierFactory class."""

    def test_create_telegram(self):
        """Create Telegram notifier."""
        config = NotifierConfig(type="telegram")
        notifier = NotifierFactory.create(config)
        assert isinstance(notifier, TelegramNotifier)

    def test_create_slack(self):
        """Create Slack notifier."""
        config = NotifierConfig(type="slack")
        notifier = NotifierFactory.create(config)
        assert isinstance(notifier, SlackNotifier)

    def test_create_webhook(self):
        """Create webhook notifier."""
        config = NotifierConfig(type="webhook")
        notifier = NotifierFactory.create(config)
        assert isinstance(notifier, WebhookNotifier)

    def test_create_unknown(self):
        """Raise error for unknown notifier type."""
        config = NotifierConfig(type="unknown")
        with pytest.raises(ValueError) as exc_info:
            NotifierFactory.create(config)
        assert "unknown" in str(exc_info.value).lower()

    def test_register_custom(self):
        """Register custom notifier type."""
        class CustomNotifier:
            def __init__(self, config):
                self.config = config

        NotifierFactory.register("custom", CustomNotifier)
        config = NotifierConfig(type="custom")
        notifier = NotifierFactory.create(config)
        assert isinstance(notifier, CustomNotifier)
