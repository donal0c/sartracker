# -*- coding: utf-8 -*-
"""
Simplified notification API wrapping QGIS message bar.

Provides version-compatible message bar notifications with simple, semantic API.
Always use these instead of calling messageBar().pushMessage() directly.

LIFECYCLE SAFETY: This module includes guards against deleted Qt objects
and plugin unload scenarios that can cause RuntimeError crashes.

Example:
    from utils.notify import success, error, safe_notify
    from qgis.utils import iface

    # Simple usage (when you know message_bar is valid):
    success(iface.messageBar(), "Operation Complete", "Data loaded successfully")
    error(iface.messageBar(), "Error", "Failed to load data")

    # Safe usage (for async callbacks or uncertain contexts):
    safe_notify(iface.messageBar(), info, "Title", "Message", is_unloading=False)
"""

import logging
from typing import Callable, Optional

from .qt_compat import push_message

logger = logging.getLogger(__name__)

# Maximum lengths for message truncation
MAX_TITLE_LENGTH = 100
MAX_MESSAGE_LENGTH = 500
MIN_DURATION = 1
MAX_DURATION = 30

# Import sip.isdeleted for Qt object validation
try:
    from qgis.PyQt.sip import isdeleted as sip_isdeleted
except ImportError:
    try:
        import sip
        sip_isdeleted = sip.isdeleted
    except Exception:
        def sip_isdeleted(_obj):
            """Fallback - assume object is not deleted."""
            return False


def _is_valid_message_bar(message_bar) -> bool:
    """
    Check if message_bar is valid and usable.

    Guards against:
    - None values
    - Deleted Qt objects (sip.isdeleted)
    - Objects without pushMessage method

    Args:
        message_bar: Object to validate

    Returns:
        True if message_bar appears valid, False otherwise
    """
    if message_bar is None:
        return False

    try:
        # Check if Qt object has been deleted
        if sip_isdeleted(message_bar):
            return False

        # Verify it has the required method
        if not hasattr(message_bar, 'pushMessage'):
            return False

        return True
    except (RuntimeError, TypeError, AttributeError):
        # Any error checking validity means it's not valid
        return False


def _truncate_string(value: str, max_length: int) -> str:
    """
    Safely truncate a string to maximum length.

    Args:
        value: String to truncate
        max_length: Maximum allowed length

    Returns:
        Truncated string with "..." suffix if truncated
    """
    if not isinstance(value, str):
        value = str(value) if value is not None else ""

    if len(value) <= max_length:
        return value

    # Truncate and add ellipsis
    return value[:max_length - 3] + "..."


def safe_notify(
    message_bar,
    notify_func: Callable,
    title: str,
    message: str,
    duration: int = 5,
    is_unloading: bool = False,
    log_prefix: str = "[NOTIFY]"
) -> bool:
    """
    Safely attempt to show a notification with comprehensive guards.

    LIFECYCLE SAFETY: This function guards against common crash scenarios
    during plugin unload, QGIS shutdown, and async callbacks.

    Guards against:
    - None message_bar
    - Deleted Qt objects (sip.isdeleted)
    - Plugin unloading state
    - RuntimeError from QGIS shutdown
    - Invalid/long message content

    Args:
        message_bar: QGIS message bar instance (or None)
        notify_func: One of info, warning, error, success
        title: Notification title (truncated to 100 chars)
        message: Notification message (truncated to 500 chars)
        duration: Display duration in seconds (clamped to 1-30)
        is_unloading: Whether plugin is unloading (suppresses notification)
        log_prefix: Prefix for debug log messages

    Returns:
        True if notification was shown, False otherwise

    Example:
        from utils.notify import safe_notify, info, warning

        # In an async callback or uncertain context:
        bar = self.iface.messageBar() if self.iface else None
        safe_notify(bar, info, "Task Complete", "Operation finished",
                   is_unloading=self._is_unloading)
    """
    # Guard: Plugin unloading - suppress all notifications
    if is_unloading:
        logger.debug("%s Suppressed during unload: %s", log_prefix, title)
        return False

    # Guard: Invalid message bar
    if not _is_valid_message_bar(message_bar):
        logger.debug("%s Invalid message_bar, suppressed: %s", log_prefix, title)
        return False

    # Sanitize inputs
    title = _truncate_string(title, MAX_TITLE_LENGTH)
    message = _truncate_string(message, MAX_MESSAGE_LENGTH)
    duration = max(MIN_DURATION, min(duration, MAX_DURATION))

    try:
        notify_func(message_bar, title, message, duration=duration)
        return True
    except RuntimeError as e:
        # Common during plugin unload or QGIS shutdown
        logger.debug("%s RuntimeError suppressed: %s", log_prefix, e)
        return False
    except Exception as e:
        # Catch any other unexpected errors
        logger.warning("%s Unexpected error: %s", log_prefix, e)
        return False


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


# =============================================================================
# SAFE CONVENIENCE WRAPPERS
# =============================================================================
# These functions accept iface directly and handle all safety checks internally.
# Use these in async callbacks, signal handlers, and any context where the
# plugin might be unloading or QGIS shutting down.


def _get_safe_message_bar(iface):
    """
    Safely get message bar from iface, returning None on any error.

    Guards against:
    - None iface
    - Deleted Qt objects
    - RuntimeError from QGIS shutdown
    """
    if iface is None:
        return None
    try:
        if sip_isdeleted(iface):
            return None
        bar = iface.messageBar()
        if bar is None or sip_isdeleted(bar):
            return None
        return bar
    except (RuntimeError, AttributeError, TypeError):
        return None


def safe_info(iface, title: str, message: str, duration: int = 5,
              is_unloading: bool = False) -> bool:
    """
    Safely show informational message with full lifecycle guards.

    Use this in async callbacks, signal handlers, and uncertain contexts.

    Args:
        iface: QGIS interface instance (or None)
        title: Message title
        message: Message content
        duration: Display duration in seconds
        is_unloading: Set True if plugin is unloading (suppresses notification)

    Returns:
        True if notification was shown, False otherwise
    """
    bar = _get_safe_message_bar(iface)
    return safe_notify(bar, info, title, message, duration=duration,
                       is_unloading=is_unloading)


def safe_warning(iface, title: str, message: str, duration: int = 5,
                 is_unloading: bool = False) -> bool:
    """
    Safely show warning message with full lifecycle guards.

    Use this in async callbacks, signal handlers, and uncertain contexts.

    Args:
        iface: QGIS interface instance (or None)
        title: Message title
        message: Message content
        duration: Display duration in seconds
        is_unloading: Set True if plugin is unloading (suppresses notification)

    Returns:
        True if notification was shown, False otherwise
    """
    bar = _get_safe_message_bar(iface)
    return safe_notify(bar, warning, title, message, duration=duration,
                       is_unloading=is_unloading)


def safe_error(iface, title: str, message: str, duration: int = 5,
               is_unloading: bool = False) -> bool:
    """
    Safely show error message with full lifecycle guards.

    Use this in async callbacks, signal handlers, and uncertain contexts.

    Args:
        iface: QGIS interface instance (or None)
        title: Message title
        message: Message content
        duration: Display duration in seconds
        is_unloading: Set True if plugin is unloading (suppresses notification)

    Returns:
        True if notification was shown, False otherwise
    """
    bar = _get_safe_message_bar(iface)
    return safe_notify(bar, error, title, message, duration=duration,
                       is_unloading=is_unloading)


def safe_success(iface, title: str, message: str, duration: int = 5,
                 is_unloading: bool = False) -> bool:
    """
    Safely show success message with full lifecycle guards.

    Use this in async callbacks, signal handlers, and uncertain contexts.

    Args:
        iface: QGIS interface instance (or None)
        title: Message title
        message: Message content
        duration: Display duration in seconds
        is_unloading: Set True if plugin is unloading (suppresses notification)

    Returns:
        True if notification was shown, False otherwise
    """
    bar = _get_safe_message_bar(iface)
    return safe_notify(bar, success, title, message, duration=duration,
                       is_unloading=is_unloading)


__all__ = [
    # Original functions (use when you have a valid message_bar)
    'info', 'warning', 'error', 'success',
    # Safe wrappers (use in async/uncertain contexts)
    'safe_notify', 'safe_info', 'safe_warning', 'safe_error', 'safe_success',
    # Utilities
    '_is_valid_message_bar', '_get_safe_message_bar',
]
