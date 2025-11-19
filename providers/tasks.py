# -*- coding: utf-8 -*-
"""
Provider Refresh Tasks

Base class and implementations for provider-specific background tasks.

Qt5/Qt6 Compatible: Uses QgsTask API.
"""

from typing import Dict, List, Optional, Any
from abc import ABC, abstractmethod
from qgis.core import QgsTask

from ..utils.exceptions import ProviderNetworkError, ProviderAuthError, ProviderDataError


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


class BreadcrumbProcessingTask(QgsTask):
    """
    Background task for processing raw breadcrumb data into QGIS features.
    
    This task takes raw position dictionaries and processes them into
    lists of QgsFeature objects (or intermediate dicts optimized for rendering)
    to offload heavy coordinate parsing and attribute mapping from the main thread.
    
    Phase 3.3 Optimization.
    """
    
    def __init__(self, raw_breadcrumbs: List[Dict], device_colors: Dict[str, str], description: str = "Processing breadcrumbs"):
        super().__init__(description, QgsTask.CanCancel)
        self.raw_breadcrumbs = raw_breadcrumbs
        self.device_colors = device_colors
        self.processed_features = []
        self.error_message = None
        
    def run(self) -> bool:
        """
        Process breadcrumbs in background.
        """
        try:
            # We can't create QgsFeature objects safely in background thread easily 
            # without care, but we CAN prepare all geometry and attributes 
            # into a clean structure that the main thread can just dump into QgsFeatures.
            #
            # Actually, QgsFeature/QgsGeometry ARE implicitly shared and thread-safe 
            # for creation detached from a layer.
            
            # Optimization: Sort by device then time
            if self.isCanceled(): return False
            self.raw_breadcrumbs.sort(key=lambda x: (x['device_id'], x['ts']))
            
            processed = []
            total = len(self.raw_breadcrumbs)
            
            for i, pos in enumerate(self.raw_breadcrumbs):
                if self.isCanceled(): return False
                if i % 100 == 0:
                    self.setProgress((i / total) * 100)
                    
                # Basic validation
                try:
                    lat = float(pos['lat'])
                    lon = float(pos['lon'])
                    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                        continue
                        
                    # Store pre-validated, typed data
                    processed.append({
                        'device_id': str(pos['device_id']),
                        'name': str(pos['name']),
                        'ts': pos['ts'],
                        'lat': lat,
                        'lon': lon,
                        'altitude': pos.get('altitude'),
                        'speed': pos.get('speed'),
                        'battery': pos.get('battery'),
                        'color': self.device_colors.get(str(pos['device_id']), "#000000")
                    })
                except (ValueError, TypeError):
                    continue
                    
            self.processed_features = processed
            return True
            
        except Exception as e:
            self.error_message = str(e)
            return False


class TraccarRefreshTask(ProviderRefreshTask):
    """
    Traccar HTTP refresh task using Phase 4 optimized provider.

    Uses TraccarHttpProvider with device caching, last-good cache, and
    optimized API access patterns. Designed for life-safety operations.

    Phase 4 Improvements:
    - Uses /api/positions for current (not per-device loops)
    - Device cache reduces API calls
    - Last-good cache provides offline resilience
    - Full error handling with ProviderError hierarchy

    Qt5/Qt6 Compatible: Uses QgsTask API.
    """

    def __init__(self, provider: 'TraccarHttpProvider', description: str = "Fetching Traccar data"):
        """
        Initialize Traccar refresh task.

        Args:
            provider: TraccarHttpProvider instance (thread-safe)
            description: Task description for progress display
        """
        super().__init__(provider, description)

    def run(self) -> bool:
        """
        Run Traccar data fetch in background thread.

        CRITICAL: This runs in a background thread. Do NOT:
        - Create or modify Qt widgets
        - Use QgsMessageBar or any GUI operations
        - Access QGIS map canvas or layers directly

        THREAD-SAFETY (Phase 4):
        Creates a dedicated requests.Session for this task using
        provider._create_session() to avoid sharing connection pools.

        Returns:
            True if successful, False if error occurred
        """
        # Create thread-local session for this task
        session = self.provider._create_session()
        fallback_features = None

        try:
            # Check for cancellation before starting
            if self.isCanceled():
                return False

            # Fetch devices with session
            def _devices_from_features(features: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
                device_map: Dict[str, Dict[str, Any]] = {}
                for feature in features or []:
                    device_id = feature.get('device_id')
                    if not device_id:
                        continue
                    if device_id in device_map:
                        continue
                    device_map[device_id] = {
                        'device_id': device_id,
                        'name': feature.get('name', f"Device {device_id}"),
                        'status': 'unknown',
                        'last_update': feature.get('ts')
                    }
                return list(device_map.values())

            try:
                devices = self.provider.get_devices(session=session)
            except ProviderNetworkError as e:
                if getattr(self.provider, 'enable_last_good_cache', False):
                    fallback_features = self.provider._load_last_good_cache()
                if fallback_features:
                    print(f"[TRACCAR_TASK] Using cached devices due to network error: {e}")
                    devices = _devices_from_features(fallback_features)
                else:
                    self.error_message = f"Failed to fetch devices: {str(e)}"
                    return False
            except (ProviderAuthError, ProviderDataError) as e:
                self.error_message = f"Failed to fetch devices: {str(e)}"
                return False
            except Exception as e:
                self.error_message = f"Unexpected error fetching devices: {str(e)}"
                return False

            # Check for cancellation
            if self.isCanceled():
                return False

            # Update progress
            self.setProgress(33)

            # Fetch current positions with session
            try:
                current = self.provider.get_current(session=session)
            except ProviderNetworkError as e:
                if fallback_features is None and getattr(self.provider, 'enable_last_good_cache', False):
                    fallback_features = self.provider._load_last_good_cache()
                if fallback_features:
                    print(f"[TRACCAR_TASK] Using cached positions due to network error: {e}")
                    current = fallback_features
                else:
                    self.error_message = f"Failed to fetch current positions: {str(e)}"
                    return False
            except (ProviderAuthError, ProviderDataError) as e:
                self.error_message = f"Failed to fetch current positions: {str(e)}"
                return False
            except Exception as e:
                print(f"[TRACCAR_TASK] Error fetching current positions: {e}")
                self.error_message = f"Failed to fetch current positions: {str(e)}"
                return False

            # Check for cancellation
            if self.isCanceled():
                return False

            # Update progress
            self.setProgress(66)

            # Fetch breadcrumbs with session
            try:
                if fallback_features:
                    breadcrumbs = []
                else:
                    breadcrumbs = self.provider.get_breadcrumbs(session=session)
            except ProviderNetworkError as e:
                print(f"[TRACCAR_TASK] Network error fetching breadcrumbs: {e}")
                breadcrumbs = []
            except (ProviderAuthError, ProviderDataError) as e:
                self.error_message = f"Failed to fetch breadcrumbs: {str(e)}"
                return False
            except Exception as e:
                print(f"[TRACCAR_TASK] Error fetching breadcrumbs: {e}")
                breadcrumbs = []

            # Check for cancellation
            if self.isCanceled():
                return False

            # Store results for main thread retrieval
            self.results = {
                'current': current,
                'breadcrumbs': breadcrumbs,
                'devices': devices
            }

            # Update progress to 100%
            self.setProgress(100)

            return True

        except Exception as e:
            # Capture error for main thread handling
            # CRITICAL: Do NOT show error dialogs here - we're in background thread
            self.error_message = str(e)
            return False

        finally:
            # CRITICAL: Close session to release connections
            try:
                session.close()
            except Exception as e:
                print(f"Warning: Error closing session in TraccarRefreshTask: {e}")
