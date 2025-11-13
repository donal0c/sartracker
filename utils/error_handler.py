# -*- coding: utf-8 -*-
"""
Centralized Error Handler for SAR Tracker

Handles conversion of exceptions to UI notifications.
Bridges domain layer (exceptions) and presentation layer (message bar).

This is the ONLY place where exceptions are converted to messageBar calls.

Qt5/Qt6 Compatible: Uses qgis.PyQt and utils for all Qt imports.
"""

from qgis.PyQt.QtCore import QObject, pyqtSignal
from .exceptions import SARTrackerError
from .notify import info, warning, error as error_notify, success


class ErrorHandler(QObject):
    """
    Centralized error handler service.

    Converts exceptions to user-visible notifications.
    Emits signals for logging and monitoring.

    Signals:
        error_occurred(exception, context): Emitted when any error is handled
        recoverable_error(exception): Emitted for recoverable errors
        critical_error(exception): Emitted for critical errors
    """

    # Signals for monitoring and logging
    error_occurred = pyqtSignal(Exception, str)  # exception, context
    recoverable_error = pyqtSignal(Exception)
    critical_error = pyqtSignal(Exception)

    def __init__(self, message_bar):
        """
        Initialize error handler.

        Args:
            message_bar: QGIS message bar instance (from iface.messageBar())
        """
        super().__init__()
        self.message_bar = message_bar

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
        # Emit monitoring signal
        self.error_occurred.emit(exception, context)

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

        # Display notification
        notify_func(
            self.message_bar,
            exception.title,
            exception.message,
            duration=duration
        )

        # Emit specific signals for monitoring
        if exception.severity == 'critical':
            self.critical_error.emit(exception)
        elif exception.recoverable:
            self.recoverable_error.emit(exception)

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

        error_notify(
            self.message_bar,
            title,
            message,
            duration=duration
        )

        # Log for debugging
        import traceback
        print(f"Unhandled exception in SAR Tracker: {context}")
        traceback.print_exc()
