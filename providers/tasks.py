# -*- coding: utf-8 -*-
"""
Provider Refresh Tasks

Base class and implementations for provider-specific background tasks.

Qt5/Qt6 Compatible: Uses QgsTask API.
"""

import logging
import math
from typing import Dict, List, Optional, Any, Callable
from collections import defaultdict
from datetime import datetime
from abc import ABC, abstractmethod
from qgis.core import QgsTask

from ..utils.exceptions import ProviderNetworkError, ProviderAuthError, ProviderDataError

logger = logging.getLogger(__name__)

# Default line-break threshold (minutes) for breadcrumb segmentation.
# Mirrors TrackingLayerManager.update_breadcrumbs default to keep UI behavior consistent.
DEFAULT_BREADCRUMB_GAP_MINUTES = 5.0
MAX_BREADCRUMB_POSITIONS = 100000


def derive_current_from_breadcrumbs(breadcrumbs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Derive current positions from breadcrumbs by finding latest per device.

    In replay mode, we cannot use the live API for "current" positions because
    that would mix live data with historical breadcrumbs. Instead, we derive
    "current" as the latest position per device within the replay window.

    Args:
        breadcrumbs: List of breadcrumb dicts, each containing at minimum:
            - device_id: str (device identifier)
            - ts: str (ISO8601 timestamp)
            Plus any other position fields (lat, lon, name, etc.)

    Returns:
        List of position dicts, one per device, representing the latest
        position for each device within the breadcrumbs.

    Edge cases:
        - Empty breadcrumbs: returns []
        - Missing device_id or ts: entry is skipped
        - Multiple devices: returns one entry per device

    Thread-safe: Pure function with no side effects.
    """
    from ..utils.timeparse import parse_iso

    if not breadcrumbs:
        return []

    latest_by_device: Dict[str, Dict[str, Any]] = {}
    latest_ts_by_device: Dict[str, datetime] = {}

    for bc in breadcrumbs:
        device_id = bc.get('device_id')
        ts_str = bc.get('ts')

        # Skip entries without required fields
        if not device_id or not ts_str:
            continue

        try:
            ts = parse_iso(ts_str)
        except (ValueError, TypeError):
            # Skip entries with unparseable timestamps
            logger.debug("Skipping breadcrumb with unparseable timestamp: device_id=%s, ts=%s",
                        device_id, ts_str)
            continue

        # Update if this is the first entry or later than current latest
        if device_id not in latest_ts_by_device or ts > latest_ts_by_device[device_id]:
            latest_ts_by_device[device_id] = ts
            latest_by_device[device_id] = bc

    return list(latest_by_device.values())


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

    BUG-036 FIX: Provides centralized cancellation management via
    check_cancellation() method for consistent state handling.

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
        # BUG-079 FIX: Track error type for structured error handling
        # Possible values: "auth", "network", "data", "cancelled", "unknown"
        self.error_type: str = "unknown"
        # BUG-036 FIX: Track if cancellation cleanup has been performed
        self._cancellation_cleanup_done = False

    def check_cancellation(self, context: str = "") -> bool:
        """
        BUG-036 FIX: Centralized cancellation check with consistent state management.

        Use this method instead of isCanceled() directly to ensure:
        1. Consistent logging of cancellation events
        2. Single point for cancellation state management
        3. Optional context for debugging cancellation points

        Args:
            context: Optional description of where cancellation is being checked

        Returns:
            True if task has been cancelled, False otherwise
        """
        if self.isCanceled():
            if context and not self._cancellation_cleanup_done:
                logger.debug("Cancellation detected at: %s", context)
            return True
        return False

    def mark_cancellation_cleanup_done(self):
        """
        BUG-036 FIX: Mark that cancellation cleanup has been performed.

        Call this after performing cleanup in finally blocks to prevent
        duplicate cleanup operations and logging.
        """
        self._cancellation_cleanup_done = True

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

    def __init__(self, provider: 'Provider', description: str = "Refreshing data",
                 since_iso: Optional[str] = None, until_iso: Optional[str] = None):
        super().__init__(provider, description)
        self.since_iso = since_iso
        self.until_iso = until_iso

    def run(self) -> bool:
        """
        Run CSV parsing in background thread.

        Returns:
            True if successful, False if error occurred
        """
        try:
            # BUG-054 FIX: Use centralized cancellation check for consistent logging
            # Check for cancellation before starting
            if self.check_cancellation("CSV task start"):
                return False

            # BUG-FIX: Copy to local variable to prevent TOCTOU race condition
            # Between check and use, self.provider could become None during shutdown
            # (Same fix as TraccarRefreshTask)
            provider = self.provider
            if not provider:
                self.error_message = "Provider no longer available"
                return False

            # Parse current positions (uses file-level caching)
            current = provider.get_current(cancel_cb=self.isCanceled)

            # Check for cancellation after each major operation
            if self.check_cancellation("CSV after get_current"):
                return False

            # Parse breadcrumbs (historical trail)
            breadcrumbs = provider.get_breadcrumbs(
                since_iso=self.since_iso,
                until_iso=self.until_iso,
                cancel_cb=self.isCanceled
            )

            if self.check_cancellation("CSV after get_breadcrumbs"):
                return False

            # Get device list
            devices = provider.get_devices(cancel_cb=self.isCanceled)

            if self.check_cancellation("CSV after get_devices"):
                return False

            if self.check_cancellation("CSV finalize"):
                self.error_message = "Task cancelled"
                self.error_type = "cancelled"
                return False

            # Store results for main thread retrieval
            self.results = {
                'current': current,
                'breadcrumbs': breadcrumbs,
                'devices': devices
            }

            return True

        except ProviderDataError as e:
            # BUG-079 FIX: Specific handling for data errors (malformed CSV, missing columns, etc.)
            self.error_message = f"[DATA_ERROR] {str(e)}"
            self.error_type = "data"
            return False
        except (IOError, OSError, FileNotFoundError, PermissionError) as e:
            # BUG-079 FIX: Specific handling for file system errors
            self.error_message = f"[FILE_ERROR] {str(e)}"
            self.error_type = "file"
            return False
        except Exception as e:
            # BUG-079 FIX: Generic error with type information
            # Capture error for main thread handling
            # CRITICAL: DO NOT show error dialogs here - we're in background thread
            self.error_message = f"[{type(e).__name__}] {str(e)}"
            self.error_type = "unknown"
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

            def _update_error_from_status():
                status_getter = getattr(self.provider, "get_connection_status", None)
                if callable(status_getter):
                    try:
                        status = status_getter()
                    except Exception:
                        return
                    if status:
                        message = status.get('message')
                        if message:
                            self.error_message = message

            # For HTTP providers, pass a thread-local session (Issue #1 fix)
            # For other providers (CSV), test_connection() doesn't need session
            if hasattr(self.provider, '_create_session'):
                # HTTP provider - create thread-local session
                session = self.provider._create_session()
                try:
                    self.success = self.provider.test_connection(session=session)
                    if self.isCanceled():
                        self.error_message = "Task cancelled"
                        self.success = False
                        return False
                    if not self.success:
                        _update_error_from_status()
                finally:
                    # BUG-026 FIX: Comprehensive session cleanup
                    # CRITICAL: Close session to release connections regardless of success/failure
                    was_cancelled = self.isCanceled()
                    try:
                        if session:
                            session.close()
                            if was_cancelled:
                                logger.debug("CONNECTION_TEST: Session closed after cancellation")
                    except Exception as e:
                        # BUG-061 FIX: Use proper logging for session close errors
                        logger.warning(
                            "BUG-061: Error closing session in ConnectionTestTask: %s - "
                            "potential connection pool resource leak",
                            e
                        )
            else:
                # CSV or other provider without session support
                self.success = self.provider.test_connection()
                if self.isCanceled():
                    self.error_message = "Task cancelled"
                    self.success = False
                    return False
                if not self.success:
                    _update_error_from_status()

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
    """Convert coordinate to float and ensure it lies within bounds.

    LIFE-SAFETY CRITICAL: Validates coordinates from Traccar HTTP provider.
    Invalid coordinates could lead rescue teams to wrong locations.
    """
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be a float-compatible value") from None

    # CRITICAL: Check NaN/Inf BEFORE range check (NaN comparisons always return False)
    # This matches validation pattern in utils/exceptions.py and providers/csv.py
    if math.isnan(numeric):
        raise ValueError(f"{field_name} is NaN")
    if math.isinf(numeric):
        raise ValueError(f"{field_name} is Infinite")

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
    raw_count = len(raw_positions)
    truncated = 0
    if raw_count > MAX_BREADCRUMB_POSITIONS:
        truncated = raw_count - MAX_BREADCRUMB_POSITIONS
        logger.warning(
            "Breadcrumb preprocessing memory guard: truncating %d positions to %d (keeping most recent)",
            raw_count,
            MAX_BREADCRUMB_POSITIONS
        )
        raw_positions = raw_positions[-MAX_BREADCRUMB_POSITIONS:]

    def _check_cancel() -> bool:
        return bool(cancel_check and cancel_check())

    if _check_cancel():
        return None

    if time_gap_minutes <= 0:
        raise ValueError("time_gap_minutes must be greater than zero")

    stats = {
        'input_points': raw_count,
        'valid_points': 0,
        'skipped_points': 0,
        'segments': 0
    }
    if truncated:
        stats['truncated_points'] = truncated

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
            if abs(lat) < 0.0001 and abs(lon) < 0.0001:
                raise ValueError("Null Island (0,0) rejected")
            timestamp = pos.get('ts')
            ts_dt = _normalize_iso_timestamp(timestamp)
        except Exception as e:
            logger.warning(f"Skipping point for device {device_id if 'device_id' in locals() else 'unknown'}: {str(e)}")
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
        device_segments: List[Dict[str, Any]] = []

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
                    device_segments.append(_build_segment_payload(current_segment))
                    stats['segments'] += 1
                current_segment = [point]
            else:
                current_segment.append(point)

        if len(current_segment) > 1:
            device_segments.append(_build_segment_payload(current_segment))
            stats['segments'] += 1

        if not device_segments and len(points) >= 2:
            for idx in range(1, len(points)):
                device_segments.append(_build_segment_payload([points[idx - 1], points[idx]]))
            stats['segments'] += len(device_segments)

        segments.extend(device_segments)

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
                logger.warning("Breadcrumb task cancel_check raised error: %s", cancel_err)
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

    Phase 3 (SAR-4vs) Addition:
    - device_timestamps parameter for incremental breadcrumb fetching
    - Reduces duplicate position fetching across refresh cycles

    Qt5/Qt6 Compatible: Uses QgsTask API.
    """

    def __init__(self, provider: 'TraccarHttpProvider', description: str = "Fetching Traccar data",
                 since_iso: Optional[str] = None,
                 until_iso: Optional[str] = None,
                 device_timestamps: Optional[Dict[str, str]] = None,
                 replay_enabled: bool = False):
        """
        Initialize Traccar refresh task.

        Args:
            provider: TraccarHttpProvider instance (thread-safe)
            description: Task description for progress display
            since_iso: Optional ISO8601 timestamp to filter breadcrumbs from.
                       If provided (e.g., mission start time), breadcrumbs will
                       be fetched from this time instead of the default 3 hours.
            until_iso: Optional ISO8601 timestamp to cap breadcrumbs (replay window).
            device_timestamps: Optional dict mapping device_id to ISO8601 timestamp.
                              When provided, enables incremental fetch mode where
                              each device fetches positions only after its last known
                              timestamp, reducing duplicate data transfer.
            replay_enabled: If True, derive current positions from breadcrumbs
                           instead of fetching live data. This ensures consistency
                           when viewing historical data in replay mode.
        """
        super().__init__(provider, description)
        self.since_iso = since_iso
        self.until_iso = until_iso
        self._device_timestamps = device_timestamps
        self.replay_enabled = replay_enabled

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
        # BUG-049 fix: Check provider exists before calling methods
        # BUG-FIX: Copy to local variable to prevent TOCTOU race condition
        # Between the check and use, self.provider could become None during shutdown
        provider = self.provider
        if not provider:
            self.error_message = "Provider no longer available"
            return False

        # Create thread-local session for this task
        # Use local reference to prevent race condition
        session = provider._create_session()
        fallback_features = None

        try:
            # BUG-054 FIX: Use centralized cancellation check for consistent logging
            # Check for cancellation before starting
            if self.check_cancellation("Traccar task start"):
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
                devices = provider.get_devices(session=session)
            except (ProviderNetworkError, ProviderDataError) as e:
                if fallback_features is None and getattr(provider, 'enable_last_good_cache', False):
                    fallback_features = provider._load_last_good_cache()
                if fallback_features:
                    logger.info("Using cached devices due to %s: %s", e.__class__.__name__, e)
                    devices = _devices_from_features(fallback_features)
                else:
                    self.error_message = f"Failed to fetch devices: {str(e)}"
                    return False
            except ProviderAuthError as e:
                # SAR-5vu FIX: Add recovery guidance
                self.error_message = f"Failed to fetch devices: {str(e)} - Check Provider Settings to re-authenticate."
                return False
            except Exception as e:
                self.error_message = f"Unexpected error fetching devices: {str(e)}"
                return False

            # BUG-054 FIX: Check for cancellation with context
            if self.check_cancellation("Traccar after get_devices"):
                return False

            # Update progress
            self.setProgress(33)

            # SAR-zh9y: In replay mode, fetch breadcrumbs first, then derive current
            # In normal mode, fetch current positions first for responsiveness
            breadcrumb_processing = None
            current = []
            breadcrumbs = []

            def _breadcrumb_progress(fraction: float):
                try:
                    fraction_val = max(0.0, min(1.0, float(fraction)))
                except Exception:
                    fraction_val = 0.0
                # In replay mode, breadcrumbs are fetched first (33-80%)
                # In normal mode, breadcrumbs are fetched after current (66-95%)
                if self.replay_enabled:
                    start, end = 33.0, 80.0
                else:
                    start, end = 66.0, 95.0
                self.setProgress(start + (end - start) * fraction_val)

            if self.replay_enabled:
                # SAR-zh9y CRITICAL: Replay mode derives current from breadcrumbs ONLY.
                # We must NOT fall back to last-good cache because:
                # 1. Cache contains LIVE positions (today's data)
                # 2. Breadcrumbs contain HISTORICAL positions (replay window)
                # Mixing these would show misleading data on the map, which is
                # dangerous for training and after-action review scenarios.
                logger.info("Replay mode: deriving current positions from breadcrumbs")

                try:
                    breadcrumbs = provider.get_breadcrumbs(
                        since_iso=self.since_iso,
                        until_iso=self.until_iso,
                        device_timestamps=self._device_timestamps,
                        session=session,
                        cancel_check=self.isCanceled,
                        progress_callback=_breadcrumb_progress
                    )
                except (ProviderNetworkError, ProviderDataError) as e:
                    logger.info("%s fetching breadcrumbs: %s", e.__class__.__name__, e)
                    # In replay mode, do NOT fall back to live cache - that would mix data
                    breadcrumbs = []
                    _breadcrumb_progress(1.0)
                except ProviderAuthError as e:
                    self.error_message = f"Failed to fetch breadcrumbs: {str(e)} - Check Provider Settings to re-authenticate."
                    return False
                except Exception as e:
                    logger.error("Error fetching breadcrumbs: %s", e)
                    breadcrumbs = []
                    _breadcrumb_progress(1.0)
                else:
                    _breadcrumb_progress(1.0)

                if self.check_cancellation("Traccar after get_breadcrumbs (replay)"):
                    return False

                # Derive current from breadcrumbs (latest position per device)
                current = derive_current_from_breadcrumbs(breadcrumbs)
                logger.info("Replay mode: derived %d current positions from %d breadcrumbs",
                           len(current), len(breadcrumbs))

                # Warn if replay mode produces no data (helps troubleshooting)
                if not current:
                    logger.warning("Replay mode: no positions to display - "
                                  "breadcrumb data may be empty or unavailable for the selected time window")

                self.setProgress(85)

            else:
                # NORMAL MODE: Fetch current positions first for responsiveness
                try:
                    current = provider.get_current(session=session)
                except (ProviderNetworkError, ProviderDataError) as e:
                    if fallback_features is None and getattr(provider, 'enable_last_good_cache', False):
                        fallback_features = provider._load_last_good_cache()
                    if fallback_features:
                        logger.info("Using cached positions due to %s: %s", e.__class__.__name__, e)
                        current = fallback_features
                    else:
                        self.error_message = f"Failed to fetch current positions: {str(e)}"
                        return False
                except ProviderAuthError as e:
                    self.error_message = f"Failed to fetch current positions: {str(e)} - Check Provider Settings to re-authenticate."
                    return False
                except Exception as e:
                    logger.error("Error fetching current positions: %s", e)
                    self.error_message = f"Failed to fetch current positions: {str(e)}"
                    return False

                if self.check_cancellation("Traccar after get_current"):
                    return False

                self.setProgress(66)

                # Fetch breadcrumbs
                try:
                    breadcrumbs = provider.get_breadcrumbs(
                        since_iso=self.since_iso,
                        until_iso=self.until_iso,
                        device_timestamps=self._device_timestamps,
                        session=session,
                        cancel_check=self.isCanceled,
                        progress_callback=_breadcrumb_progress
                    )
                except (ProviderNetworkError, ProviderDataError) as e:
                    logger.info("%s fetching breadcrumbs: %s", e.__class__.__name__, e)
                    breadcrumbs = provider._load_last_good_breadcrumbs() if getattr(provider, 'enable_last_good_cache', False) else []
                    if breadcrumbs:
                        logger.info("Using cached breadcrumbs (%d points)", len(breadcrumbs))
                    _breadcrumb_progress(1.0)
                except ProviderAuthError as e:
                    self.error_message = f"Failed to fetch breadcrumbs: {str(e)} - Check Provider Settings to re-authenticate."
                    return False
                except Exception as e:
                    logger.error("Error fetching breadcrumbs: %s", e)
                    breadcrumbs = []
                    _breadcrumb_progress(1.0)
                else:
                    _breadcrumb_progress(1.0)

            # BUG-054 FIX: Check for cancellation with context
            if self.check_cancellation("Traccar after get_breadcrumbs"):
                return False

            # Pre-process breadcrumbs so the main thread only builds QgsFeatures
            try:
                breadcrumb_processing = BreadcrumbProcessingTask.process_payload(
                    breadcrumbs,
                    time_gap_minutes=DEFAULT_BREADCRUMB_GAP_MINUTES,
                    cancel_check=self.isCanceled
                )
                if breadcrumb_processing is None:
                    # BUG-054 FIX: Use check_cancellation for consistent logging
                    if self.check_cancellation("Traccar breadcrumb processing"):
                        return False
                    # Fall back to empty payload if processing failed without cancellation
                    breadcrumb_processing = {
                        'segments': [],
                        'stats': {},
                        'time_gap_minutes': float(DEFAULT_BREADCRUMB_GAP_MINUTES)
                    }
            except Exception as proc_err:
                # BUG-065 FIX: Enhanced error logging and fallback for breadcrumb processing failure
                logger.error(
                    "BUG-065: Breadcrumb preprocessing failed: %s - "
                    "falling back to empty payload. Historical tracking data may be incomplete.",
                    proc_err,
                    exc_info=True
                )
                # Provide empty fallback payload instead of None to prevent downstream errors
                breadcrumb_processing = {
                    'segments': [],
                    'stats': {'error': str(proc_err)},
                    'time_gap_minutes': float(DEFAULT_BREADCRUMB_GAP_MINUTES)
                }

            # BUG-050 FIX: Validate results before storing
            # Ensure all lists are actual lists to prevent downstream errors
            if not isinstance(current, list):
                logger.warning("BUG-050: Invalid current type %s, using empty list", type(current).__name__)
                current = []
            if not isinstance(breadcrumbs, list):
                logger.warning("BUG-050: Invalid breadcrumbs type %s, using empty list", type(breadcrumbs).__name__)
                breadcrumbs = []
            if not isinstance(devices, list):
                logger.warning("BUG-050: Invalid devices type %s, using empty list", type(devices).__name__)
                devices = []

            # SAR-nzf FIX: Include breadcrumb failures for UI notification
            breadcrumb_failures = []
            try:
                with provider._cache_lock:
                    breadcrumb_failures = list(provider._last_breadcrumb_failures)
            except Exception:
                pass  # Silently ignore if provider doesn't have this field

            if self.check_cancellation("Traccar finalize"):
                self.error_message = "Task cancelled"
                self.error_type = "cancelled"
                return False

            # Store results for main thread retrieval
            self.results = {
                'current': current,
                'breadcrumbs': breadcrumbs,
                'devices': devices,
                'breadcrumb_processing': breadcrumb_processing,
                'breadcrumb_failures': breadcrumb_failures  # SAR-nzf: Surface partial failures
            }

            # Persist last-good payload (positions + breadcrumbs) for offline resilience
            try:
                if getattr(provider, 'enable_last_good_cache', False):
                    provider._save_last_good_cache(current, breadcrumbs)
            except Exception as cache_err:
                logger.warning("Failed to persist last-good cache: %s", cache_err)

            # Update progress to 100%
            self.setProgress(100)

            return True

        except ProviderAuthError as e:
            # BUG-079 FIX: Specific handling for authentication errors
            # SAR-5vu FIX: Add recovery guidance for mid-mission auth failures
            self.error_message = (
                f"[AUTH_ERROR] {str(e)} - "
                "Check Provider Settings to verify credentials and re-test connection."
            )
            self.error_type = "auth"
            return False
        except ProviderNetworkError as e:
            # BUG-079 FIX: Specific handling for network errors
            self.error_message = f"[NETWORK_ERROR] {str(e)}"
            self.error_type = "network"
            return False
        except ProviderDataError as e:
            # BUG-079 FIX: Specific handling for data errors
            self.error_message = f"[DATA_ERROR] {str(e)}"
            self.error_type = "data"
            return False
        except (ConnectionError, TimeoutError) as e:
            # BUG-079 FIX: Specific handling for low-level network errors
            self.error_message = f"[CONNECTION_ERROR] {str(e)}"
            self.error_type = "network"
            return False
        except Exception as e:
            # BUG-079 FIX: Generic error with type information
            # Capture error for main thread handling
            # CRITICAL: DO NOT show error dialogs here - we're in background thread
            self.error_message = f"[{type(e).__name__}] {str(e)}"
            self.error_type = "unknown"
            return False

        finally:
            # BUG-026 FIX: Comprehensive resource cleanup on completion or cancellation
            # This ensures sessions are ALWAYS closed and resources released.
            was_cancelled = self.isCanceled()
            if was_cancelled:
                logger.debug("Task was cancelled - cleaning up resources")
                # Clear any partial results to prevent stale data usage
                self.results = None

            # CRITICAL: Close session to release connections
            try:
                if session:
                    session.close()
                    if was_cancelled:
                        logger.debug("TRACCAR_TASK: Session closed after cancellation")
            except Exception as e:
                # BUG-061 FIX: Use proper logging for session close errors
                logger.warning(
                    "BUG-061: Error closing session in TraccarRefreshTask: %s - "
                    "potential connection pool resource leak",
                    e
                )
