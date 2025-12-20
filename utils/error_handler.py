# -*- coding: utf-8 -*-
"""
Centralized Error Handler for SAR Tracker

Handles conversion of exceptions to UI notifications.
Bridges domain layer (exceptions) and presentation layer (message bar).

This is the ONLY place where exceptions are converted to messageBar calls.

LIFECYCLE SAFETY: This module uses safe_notify() to guard against stale
message_bar references during plugin unload and QGIS shutdown.

Qt5/Qt6 Compatible: Uses qgis.PyQt and utils for all Qt imports.
"""

import logging
from qgis.PyQt.QtCore import QObject, pyqtSignal
from .exceptions import SARTrackerError
from .notify import info, warning, error as error_notify, success, safe_notify

logger = logging.getLogger(__name__)


class ErrorHandler(QObject):
    """
    Centralized error handler service.

    Converts exceptions to user-visible notifications.
    Emits signals for logging and monitoring.

    LIFECYCLE SAFETY: Stores iface reference and resolves message_bar at use
    time to avoid stale reference crashes during plugin unload.

    Signals:
        error_occurred(exception, context): Emitted when any error is handled
        recoverable_error(exception): Emitted for recoverable errors
        critical_error(exception): Emitted for critical errors
    """

    # Signals for monitoring and logging
    error_occurred = pyqtSignal(Exception, str)  # exception, context
    recoverable_error = pyqtSignal(Exception)
    critical_error = pyqtSignal(Exception)

    def __init__(self, iface):
        """
        Initialize error handler.

        LIFECYCLE SAFETY: Stores iface reference instead of message_bar to
        resolve message_bar at use time, avoiding stale reference issues.

        Args:
            iface: QGIS interface instance (iface, not iface.messageBar())
        """
        super().__init__()
        self._iface = iface
        self._is_unloading = False

    def set_unloading(self, unloading: bool = True):
        """
        Set unloading state to suppress notifications during shutdown.

        LIFECYCLE SAFETY: Call this from plugin.unload() before cleanup.

        Args:
            unloading: True when plugin is unloading
        """
        self._is_unloading = unloading

    def _get_message_bar(self):
        """
        Safely get message bar at use time.

        Returns:
            Message bar instance or None if unavailable
        """
        if self._is_unloading:
            return None
        if self._iface is None:
            return None
        try:
            return self._iface.messageBar()
        except (RuntimeError, AttributeError):
            return None

    def handle_exception(self, exception, context="", duration=5):
        """
        Handle an exception and display appropriate notification.

        Args:
            exception: Exception instance
            context: Additional context string (e.g., "Loading mission data")
            duration: Message display duration in seconds

        Returns:
            bool: True if error was handled, False if not a SARTrackerError
        """
        # Emit monitoring signal (safe even during unload)
        try:
            self.error_occurred.emit(exception, context)
        except RuntimeError:
            pass  # Signal disconnected during unload

        # Handle SAR Tracker exceptions
        if isinstance(exception, SARTrackerError):
            self._handle_sar_exception(exception, duration)
            return True

        # Handle unknown exceptions
        self._handle_unknown_exception(exception, context, duration)
        return False

    def _handle_sar_exception(self, exception, duration):
        """
        Handle SAR Tracker custom exception.

        Args:
            exception: SARTrackerError instance
            duration: Message display duration in seconds
        """
        # Choose notification function based on severity
        severity_map = {
            'info': info,
            'warning': warning,
            'error': error_notify,
            'critical': error_notify
        }

        notify_func = severity_map.get(exception.severity, error_notify)
        message_bar = self._get_message_bar()

        # Use safe_notify for lifecycle-safe notification
        safe_notify(
            message_bar,
            notify_func,
            exception.title,
            exception.message,
            duration=duration,
            is_unloading=self._is_unloading,
            log_prefix="[ErrorHandler]"
        )

        # Emit specific signals for monitoring (guard against disconnection)
        try:
            if exception.severity == 'critical':
                self.critical_error.emit(exception)
            elif exception.recoverable:
                self.recoverable_error.emit(exception)
        except RuntimeError:
            pass  # Signal disconnected during unload

    def _handle_unknown_exception(self, exception, context, duration):
        """
        Handle non-SAR exceptions (stdlib, QGIS, etc.).

        Args:
            exception: Exception instance
            context: Context string
            duration: Message display duration in seconds
        """
        title = "Unexpected Error"
        if context:
            title += f" ({context})"

        message = str(exception)
        if not message:
            message = f"{exception.__class__.__name__} occurred"

        message_bar = self._get_message_bar()

        # Use safe_notify for lifecycle-safe notification
        safe_notify(
            message_bar,
            error_notify,
            title,
            message,
            duration=duration,
            is_unloading=self._is_unloading,
            log_prefix="[ErrorHandler]"
        )

        # Log for debugging (always safe)
        logger.error(f"Unhandled exception in SAR Tracker: {context}", exc_info=True)
