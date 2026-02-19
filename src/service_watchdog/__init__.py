"""
Service Watchdog - Production-ready process monitoring daemon

A configurable service monitoring solution that watches processes,
sends alerts on failures, and automatically restarts services.
"""

__version__ = "1.0.0"
__author__ = "Tommie Seals"

from .watchdog import ServiceWatchdog
from .config import WatchdogConfig
from .monitor import ServiceMonitor

__all__ = ["ServiceWatchdog", "WatchdogConfig", "ServiceMonitor"]
