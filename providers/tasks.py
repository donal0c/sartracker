# -*- coding: utf-8 -*-
"""
Provider Refresh Tasks

Base class and implementations for provider-specific background tasks.

Qt5/Qt6 Compatible: Uses QgsTask API.
"""

from typing import Dict, List, Optional, Any
from abc import ABC, abstractmethod
from qgis.core import QgsTask


class ProviderRefreshTask(QgsTask):
    """
    Abstract base class for provider refresh tasks.

    All providers must implement a task that follows this interface,
    ensuring consistent behavior across CSV, HTTP, PostGIS, etc.

    CRITICAL THREADING NOTES (Life-Safety):
    - run() executes in background thread - NO Qt GUI operations allowed
    - finished() executes in main thread - safe for GUI operations
    - Always check isCanceled() between major operations
    - Store results/errors in instance variables, NOT in GUI

    Qt5/Qt6 Compatible: QgsTask works identically in both versions.
    """

    def __init__(self, provider: 'Provider', description: str = "Refreshing data"):
        """
        Initialize provider refresh task.

        Args:
            provider: Provider instance (must be thread-safe)
            description: Task description for progress display
        """
        super().__init__(description, QgsTask.CanCancel)
        self.provider = provider
        self.results: Optional[Dict[str, List]] = None
        self.error_message: Optional[str] = None

    @abstractmethod
    def run(self) -> bool:
        """
        Execute refresh in background thread.

        CRITICAL: This runs in a background thread. Do NOT:
        - Create or modify Qt widgets
        - Use QgsMessageBar or any GUI operations
        - Access QGIS map canvas or layers directly

        Must populate self.results with dict containing:
        - 'current': List[FeatureDict] - latest positions
        - 'breadcrumbs': List[FeatureDict] - historical trail
        - 'devices': List[Dict] - device list

        Returns:
            True on success, False on error
        """
        pass


class CSVRefreshTask(ProviderRefreshTask):
    """
    CSV-specific refresh task.

    Wraps CSV parsing in background thread to prevent UI freezes.
    Uses file-level caching for optimal performance.

    This task is designed for life-safety operations - it must never
    block the UI or crash during active rescue missions.
    """

    def run(self) -> bool:
        """
        Run CSV parsing in background thread.

        Returns:
            True if successful, False if error occurred
        """
        try:
            # Check for cancellation before starting
            if self.isCanceled():
                return False

            # Parse current positions (uses file-level caching)
            current = self.provider.get_current()

            # Check for cancellation after each major operation
            if self.isCanceled():
                return False

            # Parse breadcrumbs (historical trail)
            breadcrumbs = self.provider.get_breadcrumbs()

            if self.isCanceled():
                return False

            # Get device list
            devices = self.provider.get_devices()

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
            # CRITICAL: Do NOT show error dialogs here - we're in background thread
            self.error_message = str(e)
            return False
