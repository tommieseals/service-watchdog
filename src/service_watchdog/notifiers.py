"""Notification plugins for Service Watchdog."""

import json
import smtplib
import ssl
from abc import ABC, abstractmethod
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import requests

from .config import NotifierConfig
from .monitor import ServiceStatus


class NotificationEvent:
    """Represents a notification event."""

    FAILURE = "failure"
    RECOVERY = "recovery"
    RESTART = "restart"
    RESTART_FAILED = "restart_failed"

    def __init__(
        self,
        event_type: str,
        service_name: str,
        message: str,
        status: Optional[ServiceStatus] = None,
        timestamp: Optional[datetime] = None,
    ):
        self.event_type = event_type
        self.service_name = service_name
        self.message = message
        self.status = status
        self.timestamp = timestamp or datetime.now()

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "event_type": self.event_type,
            "service_name": self.service_name,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
            "status": {
                "running": self.status.running,
                "pid": self.status.pid,
                "error": self.status.error,
            }
            if self.status
            else None,
        }


class BaseNotifier(ABC):
    """Base class for notification plugins."""

    def __init__(self, config: NotifierConfig):
        self.config = config

    def should_notify(self, event: NotificationEvent) -> bool:
        """Check if notification should be sent for this event."""
        if not self.config.enabled:
            return False

        if event.event_type == NotificationEvent.FAILURE:
            return self.config.on_failure
        elif event.event_type == NotificationEvent.RECOVERY:
            return self.config.on_recovery
        elif event.event_type in (NotificationEvent.RESTART, NotificationEvent.RESTART_FAILED):
            return self.config.on_restart

        return True

    @abstractmethod
    def send(self, event: NotificationEvent) -> tuple[bool, str]:
        """Send notification. Returns (success, message)."""
        pass


class TelegramNotifier(BaseNotifier):
    """Telegram notification plugin."""

    def send(self, event: NotificationEvent) -> tuple[bool, str]:
        if not self.should_notify(event):
            return True, "Notification skipped (disabled for this event type)"

        if not self.config.bot_token or not self.config.chat_id:
            return False, "Telegram bot_token and chat_id required"

        # Format message with emoji
        emoji_map = {
            NotificationEvent.FAILURE: "🔴",
            NotificationEvent.RECOVERY: "✅",
            NotificationEvent.RESTART: "🔄",
            NotificationEvent.RESTART_FAILED: "❌",
        }
        emoji = emoji_map.get(event.event_type, "📢")

        text = f"{emoji} *Service Watchdog*\n\n"
        text += f"*Service:* `{event.service_name}`\n"
        text += f"*Event:* {event.event_type.upper()}\n"
        text += f"*Time:* {event.timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        text += event.message

        if event.status and event.status.error:
            text += f"\n\n*Error:* {event.status.error}"

        try:
            response = requests.post(
                f"https://api.telegram.org/bot{self.config.bot_token}/sendMessage",
                data={
                    "chat_id": self.config.chat_id,
                    "text": text,
                    "parse_mode": "Markdown",
                },
                timeout=30,
            )
            response.raise_for_status()
            return True, "Telegram notification sent"
        except requests.RequestException as e:
            return False, f"Telegram error: {e}"


class SlackNotifier(BaseNotifier):
    """Slack notification plugin."""

    def send(self, event: NotificationEvent) -> tuple[bool, str]:
        if not self.should_notify(event):
            return True, "Notification skipped (disabled for this event type)"

        if not self.config.webhook_url:
            return False, "Slack webhook_url required"

        # Color based on event type
        color_map = {
            NotificationEvent.FAILURE: "danger",
            NotificationEvent.RECOVERY: "good",
            NotificationEvent.RESTART: "warning",
            NotificationEvent.RESTART_FAILED: "danger",
        }
        color = color_map.get(event.event_type, "#808080")

        payload = {
            "attachments": [
                {
                    "color": color,
                    "title": f"Service Watchdog: {event.service_name}",
                    "text": event.message,
                    "fields": [
                        {"title": "Event", "value": event.event_type.upper(), "short": True},
                        {
                            "title": "Time",
                            "value": event.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                            "short": True,
                        },
                    ],
                    "footer": "Service Watchdog",
                }
            ]
        }

        if event.status and event.status.error:
            payload["attachments"][0]["fields"].append(
                {"title": "Error", "value": event.status.error, "short": False}
            )

        try:
            response = requests.post(
                self.config.webhook_url,
                json=payload,
                timeout=30,
            )
            response.raise_for_status()
            return True, "Slack notification sent"
        except requests.RequestException as e:
            return False, f"Slack error: {e}"


class EmailNotifier(BaseNotifier):
    """Email notification plugin."""

    def send(self, event: NotificationEvent) -> tuple[bool, str]:
        if not self.should_notify(event):
            return True, "Notification skipped (disabled for this event type)"

        if not all([self.config.smtp_host, self.config.from_addr, self.config.to_addrs]):
            return False, "Email smtp_host, from_addr, and to_addrs required"

        # Build email
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"[Service Watchdog] {event.service_name}: {event.event_type.upper()}"
        msg["From"] = self.config.from_addr
        msg["To"] = ", ".join(self.config.to_addrs)

        # Plain text version
        text = f"""Service Watchdog Alert

Service: {event.service_name}
Event: {event.event_type.upper()}
Time: {event.timestamp.strftime('%Y-%m-%d %H:%M:%S')}

{event.message}
"""
        if event.status and event.status.error:
            text += f"\nError: {event.status.error}"

        # HTML version
        html = f"""
<html>
<body>
<h2>Service Watchdog Alert</h2>
<table>
<tr><td><strong>Service:</strong></td><td>{event.service_name}</td></tr>
<tr><td><strong>Event:</strong></td><td>{event.event_type.upper()}</td></tr>
<tr><td><strong>Time:</strong></td><td>{event.timestamp.strftime('%Y-%m-%d %H:%M:%S')}</td></tr>
</table>
<p>{event.message}</p>
"""
        if event.status and event.status.error:
            html += f"<p><strong>Error:</strong> {event.status.error}</p>"
        html += "</body></html>"

        msg.attach(MIMEText(text, "plain"))
        msg.attach(MIMEText(html, "html"))

        try:
            context = ssl.create_default_context()
            with smtplib.SMTP(self.config.smtp_host, self.config.smtp_port) as server:
                server.starttls(context=context)
                if self.config.smtp_user and self.config.smtp_password:
                    server.login(self.config.smtp_user, self.config.smtp_password)
                server.sendmail(self.config.from_addr, self.config.to_addrs, msg.as_string())
            return True, "Email notification sent"
        except Exception as e:
            return False, f"Email error: {e}"


class WebhookNotifier(BaseNotifier):
    """Generic webhook notification plugin."""

    def send(self, event: NotificationEvent) -> tuple[bool, str]:
        if not self.should_notify(event):
            return True, "Notification skipped (disabled for this event type)"

        if not self.config.url:
            return False, "Webhook url required"

        payload = event.to_dict()

        try:
            response = requests.request(
                method=self.config.method,
                url=self.config.url,
                json=payload,
                headers=self.config.headers,
                timeout=30,
            )
            response.raise_for_status()
            return True, f"Webhook notification sent ({response.status_code})"
        except requests.RequestException as e:
            return False, f"Webhook error: {e}"


class NotifierFactory:
    """Factory for creating notifier instances."""

    _notifiers = {
        "telegram": TelegramNotifier,
        "slack": SlackNotifier,
        "email": EmailNotifier,
        "webhook": WebhookNotifier,
    }

    @classmethod
    def create(cls, config: NotifierConfig) -> BaseNotifier:
        """Create a notifier instance from config."""
        notifier_class = cls._notifiers.get(config.type.lower())
        if not notifier_class:
            raise ValueError(f"Unknown notifier type: {config.type}")
        return notifier_class(config)

    @classmethod
    def register(cls, name: str, notifier_class: type):
        """Register a custom notifier type."""
        cls._notifiers[name.lower()] = notifier_class
