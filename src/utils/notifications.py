"""
Notification helper — logs messages and can be extended for Discord /
Telegram / email integration.
"""

from __future__ import annotations

import logging

from config.settings import NOTIFY_ENABLED

log = logging.getLogger("notifications")


def notify(message: str) -> None:
    """Send a notification.  Currently just logs; extend as needed."""
    if not NOTIFY_ENABLED:
        return
    log.info("[NOTIFY] %s", message)
