"""
Service Watchdog - process monitoring daemon

A configurable service monitor that watches processes,
sends alerts on failures, and automatically restarts services.
"""

__version__ = "1.0.1"
__author__ = "Tommie Seals"

from .config import WatchdogConfig
from .monitor import ServiceMonitor
from .watchdog import ServiceWatchdog

__all__ = ["ServiceWatchdog", "WatchdogConfig", "ServiceMonitor"]
