# -*- coding: utf-8 -*-
"""
CSV Parse Task

Background task for parsing CSV tracking data without blocking the UI.

Qt5/Qt6 Compatible: Uses QGIS QgsTask API for thread-safe background processing.
"""

from typing import Dict, List, Optional, Any
from qgis.core import QgsTask
from .csv import FileCSVProvider


class CSVParseTask(QgsTask):
    """
    Background task for parsing CSV tracking data.

    This task runs CSV parsing in a background thread to prevent UI freezes
    during data refresh operations. Uses file-level caching for optimal performance.

    IMPORTANT Threading Notes:
    - run() executes in background thread - NO Qt GUI operations allowed
    - finished() executes in main thread - safe for GUI operations
    - Task is cancellable via isCanceled() check

    Qt5/Qt6 Compatible: Uses QgsTask which works identically in both versions.
    """

    def __init__(self, provider: FileCSVProvider, description: str = "Parsing tracking data"):
        """
        Initialize CSV parse task.

        Args:
            provider: FileCSVProvider instance (must be thread-safe or copied)
            description: Task description for progress display

        Note: We pass the provider instance rather than the path because the
              provider contains the cache which we want to reuse.
        """
        super().__init__(description, QgsTask.CanCancel)

        self.provider = provider
        self.results = None
        self.error_message = None

    def run(self) -> bool:
        """
        Run the task in background thread.

        CRITICAL: This method runs in a background thread. Do NOT:
        - Create or modify Qt widgets
        - Use QgsMessageBar or any GUI operations
        - Access QGIS map canvas or layers

        Returns:
            True if successful, False if error occurred
        """
        try:
            # Check for cancellation before starting
            if self.isCanceled():
                return False

            # Parse current positions
            current = self.provider.get_current(cancel_cb=self.isCanceled)

            # Check for cancellation after each major operation
            if self.isCanceled():
                return False

            # Parse breadcrumbs
            breadcrumbs = self.provider.get_breadcrumbs(cancel_cb=self.isCanceled)

            if self.isCanceled():
                return False

            # Get device list
            devices = self.provider.get_devices(cancel_cb=self.isCanceled)

            if self.isCanceled():
                return False

            # Store results for main thread retrieval
            self.results = {
                'current': current,
                'breadcrumbs': breadcrumbs,
                'devices': devices
            }

            return True

        except Exception as e:
            # Capture error for main thread handling
            self.error_message = str(e)
            return False

    def finished(self, result: bool):
        """
        Called in main thread when task completes.

        Override this method or connect to taskCompleted/taskTerminated signals.

        Args:
            result: Return value from run()
        """
        # Default implementation does nothing
        # Subclass should override or connect to signals
        pass

    def cancel(self):
        """
        Cancel the task.

        This sets the cancellation flag which is checked in run().
        """
        super().cancel()
