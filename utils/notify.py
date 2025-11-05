# -*- coding: utf-8 -*-
"""
Simplified notification API wrapping QGIS message bar.

Provides version-compatible message bar notifications with simple, semantic API.
Always use these instead of calling messageBar().pushMessage() directly.

Example:
    from utils.notify import success, error
    from qgis.utils import iface

    success(iface.messageBar(), "Operation Complete", "Data loaded successfully")
    error(iface.messageBar(), "Error", "Failed to load data")
"""

from .qt_compat import push_message


def info(message_bar, title, message, duration=5):
    """
    Show informational message (blue icon).

    Args:
        message_bar: QGIS message bar instance (from iface.messageBar())
        title: Message title
        message: Message content
        duration: Display duration in seconds (default: 5)
    """
    push_message(message_bar, title, message, level=0, duration=duration)


def warning(message_bar, title, message, duration=5):
    """
    Show warning message (yellow icon).

    Args:
        message_bar: QGIS message bar instance (from iface.messageBar())
        title: Message title
        message: Message content
        duration: Display duration in seconds (default: 5)
    """
    push_message(message_bar, title, message, level=1, duration=duration)


def error(message_bar, title, message, duration=5):
    """
    Show error message (red icon).

    Args:
        message_bar: QGIS message bar instance (from iface.messageBar())
        title: Message title
        message: Message content
        duration: Display duration in seconds (default: 5)
    """
    push_message(message_bar, title, message, level=2, duration=duration)


def success(message_bar, title, message, duration=5):
    """
    Show success message (green icon).

    Args:
        message_bar: QGIS message bar instance (from iface.messageBar())
        title: Message title
        message: Message content
        duration: Display duration in seconds (default: 5)
    """
    push_message(message_bar, title, message, level=3, duration=duration)


__all__ = ['info', 'warning', 'error', 'success']
