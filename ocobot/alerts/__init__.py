"""ocobot.alerts — Telegram sending channel + non-blocking Notifier.

Public surface for the alerts package. Importing this module must NOT perform
any network call or start any thread.
"""
from .telegram_client import TelegramClient, TelegramError
from .notifier import Notifier
from .formatting import (
    escape_mdv2,
    build_monitor_start_message,
    build_reposition_message,
    format_event,
)

__all__ = [
    "TelegramClient",
    "TelegramError",
    "Notifier",
    "escape_mdv2",
    "build_monitor_start_message",
    "build_reposition_message",
    "format_event",
]
