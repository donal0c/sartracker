# -*- coding: utf-8 -*-
"""
Provider Refresh Tasks

Base class and implementations for provider-specific background tasks.

Qt5/Qt6 Compatible: Uses QgsTask API.
"""

from typing import Dict, List, Optional, Any, Callable
from collections import defaultdict
from datetime import datetime
from abc import ABC, abstractmethod
from qgis.core import QgsTask

from ..utils.exceptions import ProviderNetworkError, ProviderAuthError, ProviderDataError

# Default line-break threshold (minutes) for breadcrumb segmentation.
# Mirrors TrackingLayerManager.update_breadcrumbs default to keep UI behavior consistent.
DEFAULT_BREADCRUMB_GAP_MINUTES = 5.0


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


def _normalize_iso_timestamp(ts: Any) -> datetime:
    """
    Normalize ISO8601 strings so datetime.fromisoformat can parse them reliably.
    """
    if not isinstance(ts, str):
        raise ValueError("Timestamp must be a string")

    ts = ts.strip()
    if not ts:
        raise ValueError("Timestamp cannot be empty")

    if ts.endswith('Z'):
        ts = ts[:-1] + '+00:00'

    return datetime.fromisoformat(ts)


def _validate_coordinate(value: Any, min_val: float, max_val: float, field_name: str) -> float:
    """Convert coordinate to float and ensure it lies within bounds."""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be a float-compatible value") from None

    if not (min_val <= numeric <= max_val):
        raise ValueError(f"{field_name} must be between {min_val} and {max_val}, got {numeric}")
    return numeric


def prepare_breadcrumb_segments(
    raw_positions: Optional[List[Dict[str, Any]]],
    time_gap_minutes: float = DEFAULT_BREADCRUMB_GAP_MINUTES,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Convert raw breadcrumb positions into contiguous segments grouped by device.

    Args:
        raw_positions: List of normalized provider position dicts.
        time_gap_minutes: Maximum allowed gap between consecutive points before
                          starting a new segment.
        cancel_check: Optional callable returning True if processing should abort.

    Returns:
        Dict containing:
            - segments: List of contiguous segments ready for layer creation
            - stats: Processing statistics for diagnostics
            - time_gap_minutes: Gap size used during segmentation

        Returns None if no valid positions are provided.
    """
    if not raw_positions:
        return None

    def _check_cancel() -> bool:
        return bool(cancel_check and cancel_check())

    if _check_cancel():
        return None

    if time_gap_minutes <= 0:
        raise ValueError("time_gap_minutes must be greater than zero")

    stats = {
        'input_points': len(raw_positions),
        'valid_points': 0,
        'skipped_points': 0,
        'segments': 0
    }

    device_positions: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    for pos in raw_positions:
        if _check_cancel():
            return None
        if not isinstance(pos, dict):
            stats['skipped_points'] += 1
            continue

        try:
            device_id = str(pos['device_id']).strip()
            if not device_id:
                raise ValueError("device_id missing")
            name = pos.get('name') or f"Device {device_id}"
            lat = _validate_coordinate(pos.get('lat'), -90.0, 90.0, 'latitude')
            lon = _validate_coordinate(pos.get('lon'), -180.0, 180.0, 'longitude')
            timestamp = pos.get('ts')
            ts_dt = _normalize_iso_timestamp(timestamp)
        except Exception:
            stats['skipped_points'] += 1
            continue

        stats['valid_points'] += 1
        device_positions[device_id].append({
            'device_id': device_id,
            'name': str(name),
            'lat': lat,
            'lon': lon,
            'ts': str(timestamp),
            'ts_dt': ts_dt
        })

    segments: List[Dict[str, Any]] = []

    for device_id, points in device_positions.items():
        if _check_cancel():
            return None
        points.sort(key=lambda p: p['ts_dt'])
        current_segment: List[Dict[str, Any]] = []

        for idx, point in enumerate(points):
            if _check_cancel():
                return None
            if idx == 0:
                current_segment = [point]
                continue

            prev_point = points[idx - 1]
            gap_minutes = (point['ts_dt'] - prev_point['ts_dt']).total_seconds() / 60.0

            if gap_minutes > time_gap_minutes:
                if len(current_segment) > 1:
                    segments.append(_build_segment_payload(current_segment))
                    stats['segments'] += 1
                current_segment = [point]
            else:
                current_segment.append(point)

        if len(current_segment) > 1:
            segments.append(_build_segment_payload(current_segment))
            stats['segments'] += 1

    return {
        'segments': segments,
        'stats': stats,
        'time_gap_minutes': float(time_gap_minutes)
    }


def _build_segment_payload(points: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Create a serializable payload for a contiguous breadcrumb segment."""
    return {
        'device_id': points[0]['device_id'],
        'name': points[0]['name'],
        'start_ts': points[0]['ts'],
        'end_ts': points[-1]['ts'],
        'point_count': len(points),
        'points': [
            {
                'lon': pt['lon'],
                'lat': pt['lat'],
                'ts': pt['ts']
            }
            for pt in points
        ]
    }


class BreadcrumbProcessingTask(QgsTask):
    """
    Background task for processing raw breadcrumb data into contiguous segments.

    Converts raw provider payloads into geometry-ready structures so the main
    thread only handles QgsFeature creation.
    """

    def __init__(
        self,
        raw_breadcrumbs: List[Dict[str, Any]],
        device_colors: Optional[Dict[str, str]] = None,
        description: str = "Processing breadcrumbs",
        time_gap_minutes: float = DEFAULT_BREADCRUMB_GAP_MINUTES,
        cancel_check: Optional[Callable[[], bool]] = None,
    ):
        super().__init__(description, QgsTask.CanCancel)
        self.raw_breadcrumbs = raw_breadcrumbs or []
        self.device_colors = device_colors or {}
        self.time_gap_minutes = time_gap_minutes or DEFAULT_BREADCRUMB_GAP_MINUTES
        self.cancel_check = cancel_check
        self.processed_payload: Optional[Dict[str, Any]] = None
        self.processed_segments: List[Dict[str, Any]] = []
        # Backward compatibility: some callers expect `processed_features`
        self.processed_features: List[Dict[str, Any]] = []
        self.processing_stats: Dict[str, Any] = {}
        self.error_message: Optional[str] = None

    def run(self) -> bool:
        """
        Process breadcrumbs in background.
        """
        if self._should_cancel():
            return False

        try:
            payload = self.process_payload(
                self.raw_breadcrumbs,
                time_gap_minutes=self.time_gap_minutes,
                cancel_check=self._should_cancel
            )
            if payload is None:
                return False

            self.processed_payload = payload
            self.processed_segments = payload.get('segments', [])
            self.processing_stats = payload.get('stats', {})
            self.processed_features = self.processed_segments
            return True

        except Exception as e:
            self.error_message = str(e)
            return False

    def _should_cancel(self) -> bool:
        if self.isCanceled():
            return True
        if self.cancel_check:
            try:
                return bool(self.cancel_check())
            except Exception as cancel_err:
                print(f"[BREADCRUMB_TASK] Warning: cancel_check raised error: {cancel_err}")
        return False

    @classmethod
    def process_payload(
        cls,
        raw_breadcrumbs: Optional[List[Dict[str, Any]]],
        time_gap_minutes: float = DEFAULT_BREADCRUMB_GAP_MINUTES,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Synchronously process breadcrumbs into contiguous segments.

        Returns:
            Dict payload with segments/stats, empty payload when no data, or
            None when processing was aborted (typically due to cancellation).
        """
        raw_count = len(raw_breadcrumbs or [])

        payload = prepare_breadcrumb_segments(
            raw_breadcrumbs,
            time_gap_minutes=time_gap_minutes,
            cancel_check=cancel_check
        )

        if payload is None:
            if raw_count > 0:
                # Non-empty data but no payload -> treat as aborted (likely cancel)
                return None
            return {
                'segments': [],
                'stats': {},
                'time_gap_minutes': float(time_gap_minutes)
            }

        return payload


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
            except (ProviderNetworkError, ProviderDataError) as e:
                if fallback_features is None and getattr(self.provider, 'enable_last_good_cache', False):
                    fallback_features = self.provider._load_last_good_cache()
                if fallback_features:
                    print(f"[TRACCAR_TASK] Using cached devices due to {e.__class__.__name__}: {e}")
                    devices = _devices_from_features(fallback_features)
                else:
                    self.error_message = f"Failed to fetch devices: {str(e)}"
                    return False
            except ProviderAuthError as e:
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
            except (ProviderNetworkError, ProviderDataError) as e:
                if fallback_features is None and getattr(self.provider, 'enable_last_good_cache', False):
                    fallback_features = self.provider._load_last_good_cache()
                if fallback_features:
                    print(f"[TRACCAR_TASK] Using cached positions due to {e.__class__.__name__}: {e}")
                    current = fallback_features
                else:
                    self.error_message = f"Failed to fetch current positions: {str(e)}"
                    return False
            except ProviderAuthError as e:
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

            # Fetch breadcrumbs with session (always attempt, even when using cached positions)
            breadcrumb_processing = None
            try:
                breadcrumbs = self.provider.get_breadcrumbs(session=session)
            except (ProviderNetworkError, ProviderDataError) as e:
                print(f"[TRACCAR_TASK] {e.__class__.__name__} fetching breadcrumbs: {e}")
                breadcrumbs = []
            except ProviderAuthError as e:
                self.error_message = f"Failed to fetch breadcrumbs: {str(e)}"
                return False
            except Exception as e:
                print(f"[TRACCAR_TASK] Error fetching breadcrumbs: {e}")
                breadcrumbs = []

            # Check for cancellation
            if self.isCanceled():
                return False

            # Pre-process breadcrumbs so the main thread only builds QgsFeatures
            try:
                breadcrumb_processing = BreadcrumbProcessingTask.process_payload(
                    breadcrumbs,
                    time_gap_minutes=DEFAULT_BREADCRUMB_GAP_MINUTES,
                    cancel_check=self.isCanceled
                )
                if breadcrumb_processing is None:
                    if self.isCanceled():
                        print("[TRACCAR_TASK] Breadcrumb processing canceled")
                        return False
                    # Fall back to empty payload if processing failed without cancellation
                    breadcrumb_processing = {
                        'segments': [],
                        'stats': {},
                        'time_gap_minutes': float(DEFAULT_BREADCRUMB_GAP_MINUTES)
                    }
            except Exception as proc_err:
                print(f"[TRACCAR_TASK] Breadcrumb preprocessing failed: {proc_err}")
                breadcrumb_processing = None

            # Store results for main thread retrieval
            self.results = {
                'current': current,
                'breadcrumbs': breadcrumbs,
                'devices': devices,
                'breadcrumb_processing': breadcrumb_processing
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
