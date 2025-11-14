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


class HTTPRefreshTask(ProviderRefreshTask):
    """
    HTTP-specific refresh task with retry logic and throttling.

    Wraps HTTP API calls in background thread to prevent UI freezes during
    network operations. Includes retry logic for transient failures and
    request throttling to avoid overwhelming the server.

    LIFE-SAFETY CRITICAL: This task must never block the UI thread during
    active rescue operations. Network failures must be handled gracefully.

    Qt5/Qt6 Compatible: Uses QgsTask API.
    """

    def __init__(self, provider: 'Provider', description: str = "Fetching tracking data",
                 retry_count: int = 3, retry_backoff: float = 1.0, request_throttle: float = 0.1):
        """
        Initialize HTTP refresh task.

        Args:
            provider: HttpTraccarProvider instance (thread-safe)
            description: Task description for progress display
            retry_count: Number of retry attempts for failed requests (default: 3)
            retry_backoff: Base backoff time in seconds for exponential backoff (default: 1.0)
            request_throttle: Delay in seconds between device requests (default: 0.1)
        """
        super().__init__(provider, description)
        self.retry_count = retry_count
        self.retry_backoff = retry_backoff
        self.request_throttle = request_throttle

    def run(self) -> bool:
        """
        Run HTTP fetches in background thread with retries.

        CRITICAL: This runs in a background thread. Do NOT:
        - Create or modify Qt widgets
        - Use QgsMessageBar or any GUI operations
        - Access QGIS map canvas or layers directly

        THREAD-SAFETY (Issue #1 fix):
        Creates a dedicated requests.Session for this task to avoid
        sharing connection pools with other concurrent tasks.

        Returns:
            True if successful, False if error occurred
        """
        import time

        # Create thread-local session (Issue #1 fix)
        # This session is used ONLY by this task and disposed after completion
        session = self.provider._create_session()

        try:
            # Check for cancellation before starting
            if self.isCanceled():
                return False

            # Fetch devices with retry logic (pass session)
            devices = self._fetch_with_retry(
                lambda: self.provider.get_devices(session=session),
                "devices"
            )

            if devices is None:
                return False  # Error occurred

            # Check for cancellation
            if self.isCanceled():
                return False

            # Fetch current positions with individual device error handling
            current = []
            device_count = len(devices)

            for i, device in enumerate(devices):
                # Check for cancellation before each device
                if self.isCanceled():
                    return False

                # Update progress (0-50% for current positions)
                progress = int((i / device_count) * 50)
                self.setProgress(progress)

                try:
                    # Fetch this device's current position
                    device_id = str(device['id'])
                    device_name = device.get('name', f"Device {device_id}")

                    # Use provider's existing method but handle individual failures
                    from datetime import datetime, timedelta
                    current_time = datetime.utcnow()
                    from_time = current_time - timedelta(hours=1)

                    params = {
                        'deviceId': device['id'],
                        'from': from_time.strftime('%Y-%m-%dT%H:%M:%SZ'),
                        'to': current_time.strftime('%Y-%m-%dT%H:%M:%SZ')
                    }
                    # Pass session to provider method (Issue #1 fix)
                    routes = self.provider._make_request('/api/reports/route', params, session=session)

                    if routes:
                        latest = max(routes, key=lambda x: x.get('fixTime', ''))
                        current.append({
                            'device_id': device_id,
                            'name': device_name,
                            'lat': latest['latitude'],
                            'lon': latest['longitude'],
                            'ts': latest['fixTime'],
                            'altitude': latest.get('altitude'),
                            'speed': latest.get('speed'),
                            'battery': latest.get('attributes', {}).get('batteryLevel')
                        })

                except Exception as e:
                    # Log error but continue with other devices (graceful degradation)
                    print(f"Warning: Could not fetch position for device {device.get('name', device['id'])}: {e}")
                    continue

                # Throttle requests to avoid overwhelming server
                if i < device_count - 1:  # Don't sleep after last device
                    time.sleep(self.request_throttle)

            # Check for cancellation
            if self.isCanceled():
                return False

            # Fetch breadcrumbs with individual device error handling
            breadcrumbs = []

            for i, device in enumerate(devices):
                # Check for cancellation before each device
                if self.isCanceled():
                    return False

                # Update progress (50-100% for breadcrumbs)
                progress = 50 + int((i / device_count) * 50)
                self.setProgress(progress)

                try:
                    # Fetch this device's breadcrumbs
                    device_id = str(device['id'])
                    device_name = device.get('name', f"Device {device_id}")

                    from datetime import datetime, timedelta
                    current_time = datetime.utcnow()
                    from_time = current_time - timedelta(hours=3)

                    params = {
                        'deviceId': device['id'],
                        'from': from_time.strftime('%Y-%m-%dT%H:%M:%SZ'),
                        'to': current_time.strftime('%Y-%m-%dT%H:%M:%SZ')
                    }
                    # Pass session to provider method (Issue #1 fix)
                    routes = self.provider._make_request('/api/reports/route', params, session=session)

                    for pos in routes:
                        breadcrumbs.append({
                            'device_id': device_id,
                            'name': device_name,
                            'lat': pos['latitude'],
                            'lon': pos['longitude'],
                            'ts': pos['fixTime'],
                            'altitude': pos.get('altitude'),
                            'speed': pos.get('speed'),
                            'battery': pos.get('attributes', {}).get('batteryLevel')
                        })

                except Exception as e:
                    # Log error but continue with other devices
                    print(f"Warning: Could not fetch breadcrumbs for device {device.get('name', device['id'])}: {e}")
                    continue

                # Throttle requests
                if i < device_count - 1:
                    time.sleep(self.request_throttle)

            # Sort breadcrumbs by device then timestamp
            breadcrumbs.sort(key=lambda x: (x['device_id'], x['ts']))

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

        finally:
            # CRITICAL: Close session to release connections (Issue #1 fix)
            try:
                session.close()
            except Exception as e:
                print(f"Warning: Error closing HTTP session: {e}")

    def _fetch_with_retry(self, fetch_func, operation_name: str) -> Optional[Any]:
        """
        Execute fetch function with retry logic and exponential backoff.

        Args:
            fetch_func: Function to execute (should include session parameter)
            operation_name: Name for error messages

        Returns:
            Result of fetch_func, or None if all retries failed

        THREAD-SAFETY (Issue #1 fix):
        fetch_func should be a lambda that passes the task's session
        to provider methods, ensuring thread-isolated HTTP state.
        """
        import time

        for attempt in range(self.retry_count):
            # Check for cancellation before each attempt
            if self.isCanceled():
                return None

            try:
                result = fetch_func()
                return result

            except Exception as e:
                # Last attempt - capture error
                if attempt == self.retry_count - 1:
                    self.error_message = f"Failed to fetch {operation_name} after {self.retry_count} attempts: {str(e)}"
                    return None

                # Wait before retry (exponential backoff)
                wait_time = self.retry_backoff * (2 ** attempt)
                time.sleep(wait_time)
