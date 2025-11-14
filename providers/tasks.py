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

    OPTIMIZATION (Issue #4 fix):
    Fetches each device once using a 3-hour time window, then splits results
    in memory into "current" (latest position) and "breadcrumbs" (all positions).
    This reduces HTTP requests from 2N to N (50% performance improvement).

    Performance for 40 devices: ~24s (down from ~48s)
    Performance for 60 devices: ~36s (down from ~72s)

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

        OPTIMIZATION (Issue #4 fix):
        Single-pass fetch: Each device is fetched once with a 3-hour window.
        Results are split in memory into current (latest) and breadcrumbs (all).
        This eliminates duplicate HTTP requests and reduces total time by ~50%.

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

            # Fetch positions with unified device loop (eliminates duplicate fetches)
            # OPTIMIZATION (Issue #4 fix):
            # Strategy: Fetch each device once with 3-hour window, then split into
            # "current" (latest position) and "breadcrumbs" (all positions) in memory.
            # Performance: Reduces HTTP requests from 2N to N (50% improvement).
            current = []
            breadcrumbs = []
            device_count = len(devices)

            # Define time ranges once
            from datetime import datetime, timedelta
            current_time = datetime.utcnow()
            breadcrumbs_from_time = current_time - timedelta(hours=3)

            for i, device in enumerate(devices):
                # Check for cancellation before each device
                if self.isCanceled():
                    return False

                # Update progress (0-100% for all devices)
                progress = int((i / device_count) * 100)
                self.setProgress(progress)

                try:
                    # Fetch this device's route data ONCE using 3-hour window
                    device_id = str(device['id'])
                    device_name = device.get('name', f"Device {device_id}")

                    params = {
                        'deviceId': device['id'],
                        'from': breadcrumbs_from_time.strftime('%Y-%m-%dT%H:%M:%SZ'),
                        'to': current_time.strftime('%Y-%m-%dT%H:%M:%SZ')
                    }

                    # Single API call per device (was 2 calls before)
                    # Pass session to provider method (Issue #1 fix)
                    routes = self.provider._make_request('/api/reports/route', params, session=session)

                    if routes:
                        # Extract current position (latest in the dataset)
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

                        # Extract all positions as breadcrumbs
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
                    # Log error but continue with other devices (graceful degradation)
                    print(f"Warning: Could not fetch data for device {device.get('name', device['id'])}: {e}")
                    continue

                # Throttle requests to avoid overwhelming server
                # Note: Only throttle if not the last device
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


class ConnectionTestTask(QgsTask):
    """
    Background task for testing provider connectivity.

    Tests provider connection without blocking the UI thread.
    For HTTP providers, creates a thread-local session to avoid
    contention (Issue #1 fix).

    LIFE-SAFETY CRITICAL: Connection testing must never block the UI
    during mission setup. Operators need immediate map access.

    Qt5/Qt6 Compatible: Uses QgsTask API.
    """

    def __init__(self, provider: 'Provider', description: str = "Testing connection"):
        """
        Initialize connection test task.

        Args:
            provider: Provider instance to test (must be thread-safe)
            description: Task description for progress display
        """
        super().__init__(description, QgsTask.CanCancel)
        self.provider = provider
        self.success = False
        self.error_message: Optional[str] = None

    def run(self) -> bool:
        """
        Test connection in background thread.

        CRITICAL: This runs in a background thread. Do NOT:
        - Create or modify Qt widgets
        - Use QgsMessageBar or any GUI operations
        - Access QGIS map canvas or layers directly

        Returns:
            True if connection successful, False otherwise
        """
        try:
            # Check for cancellation
            if self.isCanceled():
                return False

            # For HTTP providers, pass a thread-local session (Issue #1 fix)
            # For other providers (CSV), test_connection() doesn't need session
            if hasattr(self.provider, '_create_session'):
                # HTTP provider - create thread-local session
                session = self.provider._create_session()
                try:
                    self.success = self.provider.test_connection(session=session)
                finally:
                    # CRITICAL: Close session to release connections
                    try:
                        session.close()
                    except Exception as e:
                        print(f"Warning: Error closing session in ConnectionTestTask: {e}")
            else:
                # CSV or other provider without session support
                self.success = self.provider.test_connection()

            return self.success

        except Exception as e:
            # Capture error for main thread handling
            self.error_message = str(e)
            self.success = False
            return False
