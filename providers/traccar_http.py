# -*- coding: utf-8 -*-
"""
Traccar HTTP provider.

Phase 4 - Traccar HTTP MVP:
Production-ready provider using HttpClient, device caching, last-good cache,
and optimized API access patterns. Polls /api/positions for current data and
/api/positions?deviceId=X&from=...&to=... for breadcrumbs.

Uses utils.http.HttpClient for REST polling.
Qt5/Qt6 Compatible: no Qt imports; safe for background threads (AI_CODE_REFERENCE.md).

Classification: CRITICAL - LIFE SAFETY SYSTEM
"""
from typing import List, Dict, Any, Optional, Callable
from datetime import datetime, timedelta, timezone
import json
import os
import sys
import time
import concurrent.futures
import queue
from pathlib import Path
import logging
import threading
from threading import RLock
import contextlib

from .base import Provider, FeatureDict
from ..utils.http import HttpClient
from ..utils.timeparse import parse_iso, format_iso, window
from ..utils.exceptions import (
    ProviderError, ProviderAuthError, ProviderNetworkError, ProviderDataError,
    validate_coordinate_pair
)

logger = logging.getLogger(__name__)

# Cache file location (OS-specific)
def _default_cache_dir() -> str:
    """Return per-platform cache directory within the user profile."""
    home = Path.home()
    if sys.platform.startswith("win"):
        base_dir = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base_dir = Path(os.environ.get("XDG_DATA_HOME", home / "Library" / "Application Support"))
    else:
        base_dir = Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share"))
    return str(base_dir / "QGIS" / "sartracker")


_CACHE_DIR = _default_cache_dir()
_CACHE_FILE = os.path.join(_CACHE_DIR, "traccar_cache.json")


class TraccarHttpProvider(Provider):
    """
    Traccar HTTP provider with device caching and resilient design.

    Features:
    - Uses HttpClient for retry logic and structured error handling
    - Device name cache with configurable TTL (reduces API calls)
    - Last-good payload cache for offline resilience
    - Optimized API access: /api/positions for current, per-device breadcrumbs
    - Full input validation and defensive error handling

    Thread-Safety:
    - Provider methods may be called from background threads (QgsTask)
    - Device cache uses simple dict (single-threaded provider instance)
    - HttpClient creates per-task sessions for thread isolation

    Qt5/Qt6 Compatible: No Qt dependencies.
    """

    def __init__(
        self,
        base_url: str,
        auth_type: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
        token: Optional[str] = None,
        timeout_s: int = 10,
        cache_ttl: int = 300,
        enable_last_good_cache: bool = True,
        breadcrumb_workers: int = 10,
        enable_bulk_breadcrumbs: bool = False
    ):
        """
        Initialize Traccar HTTP provider.

        Args:
            base_url: Traccar server base URL (e.g., "http://kmrtsar.eu:8082")
            auth_type: Authentication type ("basic" or "bearer")
            username: Username for basic auth (required if auth_type="basic")
            password: Password for basic auth (required if auth_type="basic")
            token: Bearer token for token auth (required if auth_type="bearer")
            timeout_s: HTTP request timeout in seconds (default: 10)
            cache_ttl: Device cache TTL in seconds (default: 300 = 5 minutes)
            enable_last_good_cache: Whether to enable last-good payload caching (default: True)
            breadcrumb_workers: Max parallel workers for breadcrumb fetch (default: 10)
            enable_bulk_breadcrumbs: Try bulk /api/positions?from=&to= for breadcrumbs before per-device (default: False)

        Raises:
            ValueError: If inputs invalid or auth credentials missing
        """
        # INPUT VALIDATION (AI_CODE_REFERENCE.md - mandatory pattern)
        if not base_url or not isinstance(base_url, str) or not base_url.strip():
            raise ValueError("base_url cannot be empty")

        base_url = base_url.strip()

        if not auth_type or not isinstance(auth_type, str) or not auth_type.strip():
            raise ValueError("auth_type cannot be empty")

        auth_type = auth_type.strip()

        if auth_type not in ["basic", "bearer"]:
            raise ValueError(f"auth_type must be 'basic' or 'bearer', got: {auth_type}")

        if auth_type == "basic":
            if not username or not isinstance(username, str) or not username.strip():
                raise ValueError("username required for basic auth and cannot be empty")
            if not password or not isinstance(password, str) or not password.strip():
                raise ValueError("password required for basic auth and cannot be empty")
            username = username.strip()
            password = password.strip()

        if auth_type == "bearer":
            if not token or not isinstance(token, str) or not token.strip():
                raise ValueError("token required for bearer auth and cannot be empty")
            token = token.strip()

        if not isinstance(timeout_s, int) or timeout_s <= 0:
            raise ValueError(f"timeout_s must be positive integer, got: {timeout_s}")

        if not isinstance(cache_ttl, int) or cache_ttl < 0:
            raise ValueError(f"cache_ttl must be non-negative integer, got: {cache_ttl}")

        if not isinstance(breadcrumb_workers, int) or breadcrumb_workers <= 0:
            raise ValueError(f"breadcrumb_workers must be positive integer, got: {breadcrumb_workers}")

        if not isinstance(enable_bulk_breadcrumbs, bool):
            raise ValueError(f"enable_bulk_breadcrumbs must be boolean, got: {enable_bulk_breadcrumbs}")

        # Store configuration
        # Traccar URLs copied from browsers may include '/#/' fragments; strip
        # the hash portion so API endpoints are formed correctly.
        self.base_url = base_url.split('#')[0].rstrip('/')
        self.auth_type = auth_type
        self.username = username
        self.password = password
        self.token = token
        self.timeout_s = timeout_s
        self.cache_ttl = cache_ttl
        self.enable_last_good_cache = enable_last_good_cache
        self.breadcrumb_workers = breadcrumb_workers
        self.enable_bulk_breadcrumbs = enable_bulk_breadcrumbs

        # Initialize HttpClient
        self.http_client = HttpClient(
            base_url=self.base_url,
            timeout_s=self.timeout_s,
            max_retries=3
        )

        # BUG-075 FIX: Device cache with clear expiration policy and size limits
        # Cache expires after cache_ttl seconds (default 300s / 5 minutes)
        # Maximum cache size prevents memory issues with large device counts
        self._device_cache: Dict[str, str] = {}  # {device_id: device_name}
        self._device_cache_timestamp: Optional[datetime] = None
        self._device_cache_stale: bool = False
        self._device_cache_warning: Optional[str] = None
        self._cache_lock: RLock = RLock()
        # BUG-075 FIX: Maximum devices to cache (safety limit)
        self.MAX_DEVICE_CACHE_SIZE = 10000  # Reasonable limit for rescue operations
        # SAR-l07 FIX: Longer cache expiration for extended SAR operations
        # 4 hours allows for extended connectivity issues in remote mountain areas
        # Stale data with warnings is preferable to no data in life-safety scenarios
        self.LAST_GOOD_CACHE_MAX_AGE_S = 14400  # 4 hours (was 1 hour)
        self._last_breadcrumb_failures: List[str] = []
        self._last_connection_status: Dict[str, Any] = {
            'success': None,
            'message': None,
            'timestamp': None
        }

        logger.info(
            "Traccar HTTP initialized: base_url=%s auth=%s timeout=%ss cache_ttl=%ss",
            base_url,
            auth_type,
            timeout_s,
            cache_ttl
        )

    def _create_session(self):
        """
        Create authenticated session for this thread.

        Returns:
            requests.Session configured with authentication

        Thread-Safety:
            Each background task should create its own session using this method.
        """
        return self.http_client.create_session(
            auth_type=self.auth_type,
            username=self.username,
            password=self.password,
            token=self.token
        )

    def _load_devices(self, force: bool = False, session=None) -> Dict[str, str]:
        """
        Load devices from API with caching.

        Fetches /api/devices and builds {device_id: device_name} map.
        Results are cached for cache_ttl seconds unless force=True.

        Args:
            force: If True, bypass cache and force refresh (default: False)
            session: Optional requests.Session for thread-safe execution

        Returns:
            Dict mapping device_id (str) to device_name (str)

        Raises:
            ProviderAuthError: If authentication fails
            ProviderNetworkError: If network request fails
            ProviderDataError: If API response invalid

        Thread-Safety:
            Safe when each task creates its own session.
        """
        # Check cache validity
        now = datetime.now(timezone.utc)

        # BUG-PF-002 fix: Protect device cache access with lock
        with self._cache_lock:
            if not force and self._device_cache_timestamp:
                age = (now - self._device_cache_timestamp).total_seconds()
                if age < self.cache_ttl:
                    logger.debug(
                        "Using cached devices (age=%.1fs ttl=%ss)",
                        age,
                        self.cache_ttl
                    )
                    return self._device_cache.copy()  # Return copy to avoid external modification

        # Cache miss or expired - fetch from API
        logger.info(
            "Fetching devices from /api/devices (cache %s)",
            "forced" if force else "expired"
        )

        try:
            # Create session if not provided
            if session is None:
                session = self._create_session()
                close_session = True
            else:
                close_session = False

            try:
                # Fetch devices
                data = self.http_client.get("/api/devices", session=session, expect_json=True)

                # Validate response type
                if not isinstance(data, list):
                    raise ProviderDataError(
                        f"Invalid /api/devices response: expected list, got {type(data).__name__}",
                        provider_name='traccar_http',
                        recoverable=False
                    )

                device_map = self._build_device_map(data)
                self._set_device_cache(device_map, timestamp=now)

                logger.info("Device cache updated: %s devices", len(device_map))
                return device_map

            finally:
                # Close session if we created it
                if close_session:
                    try:
                        session.close()
                    except Exception as e:
                        logger.warning("Error closing session after /api/devices fetch: %s", e)

        except ProviderAuthError:
            # Auth failures must always bubble up
            raise
        except (ProviderNetworkError, ProviderDataError) as exc:
            # BUG-PF-002 fix: Protect cache access with lock
            with self._cache_lock:
                if self._device_cache:
                    self._device_cache_stale = True
                    self._device_cache_warning = f"{exc.__class__.__name__}: {exc}"
                    cache_size = len(self._device_cache)
                    cache_copy = self._device_cache.copy()
                else:
                    cache_copy = None

            if cache_copy:
                logger.warning(
                    "Device fetch failed (%s): %s; using stale cache with %s entries",
                    exc.__class__.__name__,
                    exc,
                    cache_size
                )
                return cache_copy
            raise
        except Exception as exc:
            # BUG-PF-002 fix: Protect cache access with lock
            with self._cache_lock:
                if self._device_cache:
                    self._device_cache_stale = True
                    self._device_cache_warning = f"{exc.__class__.__name__}: {exc}"
                    cache_size = len(self._device_cache)
                    cache_copy = self._device_cache.copy()
                else:
                    cache_copy = None

            if cache_copy:
                logger.warning(
                    "Unexpected device fetch error (%s): %s; using stale cache with %s entries",
                    exc.__class__.__name__,
                    exc,
                    cache_size
                )
                return cache_copy
            # Wrap unexpected errors when no cache available
            raise ProviderDataError(
                f"Unexpected error loading devices: {str(exc)}",
                provider_name='traccar_http',
                recoverable=False
            )

    def _set_device_cache(self, device_map: Dict[str, str], timestamp: Optional[datetime] = None):
        """
        Update the in-memory device cache with a normalized map.

        BUG-075 FIX: Enforces maximum cache size limit to prevent memory issues.

        Args:
            device_map: Mapping of device IDs to names.
            timestamp: Optional datetime to record as cache timestamp.
        """
        # BUG-PF-002 fix: Protect device cache updates with lock
        with self._cache_lock:
            # BUG-075 FIX: Enforce maximum cache size
            if len(device_map) > self.MAX_DEVICE_CACHE_SIZE:
                logger.warning(
                    "BUG-075: Device map exceeds cache limit (%d > %d), truncating to most recently updated devices",
                    len(device_map), self.MAX_DEVICE_CACHE_SIZE
                )
                # Keep only the first MAX_DEVICE_CACHE_SIZE entries
                # (in practice, device counts shouldn't exceed this in rescue operations)
                device_map = dict(list(device_map.items())[:self.MAX_DEVICE_CACHE_SIZE])

            self._device_cache = device_map or {}
            if timestamp is None:
                timestamp = datetime.now(timezone.utc)
            self._device_cache_timestamp = timestamp
            self._device_cache_stale = False
            self._device_cache_warning = None

    def _annotate_origin(self, records: Optional[List[Dict[str, Any]]], origin: str) -> List[Dict[str, Any]]:
        """
        Attach a data_origin flag so downstream layers know live vs cached data.

        Args:
            records: List of feature/device dicts.
            origin: String flag such as 'live' or 'cache'.

        Returns:
            New list with data_origin applied (invalid entries skipped).
        """
        if not records:
            return []

        annotated: List[Dict[str, Any]] = []
        for record in records:
            if not isinstance(record, dict):
                continue

            if record.get('data_origin') == origin:
                annotated.append(record)
            else:
                annotated.append({**record, 'data_origin': origin})
        return annotated

    def _build_device_map(self, raw_devices: List[Dict[str, Any]]) -> Dict[str, str]:
        """
        Build a {device_id: name} mapping from raw /api/devices payload.

        Invalid entries are skipped with diagnostic logging.
        """
        device_map: Dict[str, str] = {}
        for device in raw_devices or []:
            if not isinstance(device, dict):
                logger.warning("Skipping invalid device entry: %s", device)
                continue

            device_id = device.get('id')
            if device_id is None:
                logger.warning("Device payload missing 'id': %s", device)
                continue

            device_id_str = str(device_id)
            name_val = device.get('name')
            if isinstance(name_val, str) and name_val.strip():
                device_name = name_val.strip()
            else:
                device_name = f"Device {device_id_str}"

            device_map[device_id_str] = device_name

        return device_map

    def get_current(self, session=None) -> List[FeatureDict]:
        """
        Get latest position per device.

        Uses /api/positions endpoint which returns current positions for all devices.
        Much more efficient than per-device loops.

        Args:
            session: Optional requests.Session for thread-safe execution

        Returns:
            List of feature dicts with normalized schema:
                - device_id: str (unique device identifier)
                - name: str (device display name from cache)
                - lat: float (latitude WGS84)
                - lon: float (longitude WGS84)
                - ts: str (ISO8601 timestamp)
                - altitude: Optional[float]
                - speed: Optional[float]
                - battery: Optional[float]

        Raises:
            ProviderAuthError: If authentication fails
            ProviderNetworkError: If network request fails
            ProviderDataError: If API response invalid

        Thread-Safety:
            Safe when each task creates its own session.
        """
        logger.info("Fetching current positions from /api/positions")

        try:
            # Create session if not provided
            if session is None:
                session = self._create_session()
                close_session = True
            else:
                close_session = False

            try:
                # Load device cache first (for name resolution)
                device_map = self._load_devices(force=False, session=session)

                # Fetch current positions
                data = self.http_client.get("/api/positions", session=session, expect_json=True)

                # Validate response type
                if not isinstance(data, list):
                    raise ProviderDataError(
                        f"Invalid /api/positions response: expected list, got {type(data).__name__}",
                        provider_name='traccar_http',
                        recoverable=False
                    )

                # Normalize each position
                features = []
                for pos in data:
                    try:
                        feature = self._normalize_position(pos, device_map)
                        features.append(feature)
                    except Exception as e:
                        # Log error but continue with other positions (graceful degradation)
                        device_id = pos.get('deviceId', 'unknown')
                        logger.warning(
                            "Failed to normalize position for device %s: %s",
                            device_id,
                            e
                        )
                        continue

                # Sort by timestamp (most recent first)
                features.sort(key=lambda x: x['ts'], reverse=True)

                # SAR-e5h FIX: Deduplicate by device_id, keeping most recent position
                # Traccar API can return multiple positions per device in rapid update scenarios
                seen_devices = set()
                unique_features = []
                for feature in features:
                    device_id = feature['device_id']
                    if device_id not in seen_devices:
                        seen_devices.add(device_id)
                        unique_features.append(feature)
                if len(unique_features) < len(features):
                    logger.debug(
                        "SAR-e5h: Deduplicated %d -> %d positions (removed %d duplicates)",
                        len(features), len(unique_features), len(features) - len(unique_features)
                    )
                features = unique_features

                logger.info("Fetched %s current positions", len(features))

                annotated_features = self._annotate_origin(features, origin='live')

                # Save to last-good cache
                if self.enable_last_good_cache and annotated_features:
                    self._save_last_good_cache(annotated_features)

                return annotated_features

            finally:
                # Close session if we created it
                if close_session:
                    try:
                        session.close()
                    except Exception as e:
                        logger.warning("Error closing session after /api/positions fetch: %s", e)

        except ProviderAuthError:
            # Auth errors must be surfaced to the operator immediately
            raise
        except (ProviderNetworkError, ProviderDataError) as e:
            if self.enable_last_good_cache:
                logger.warning(
                    "%s fetching current positions, loading last-good cache: %s",
                    e.__class__.__name__,
                    e
                )
                cache_result = self._load_last_good_cache_with_metadata()
                if cache_result:
                    cached, cache_timestamp = cache_result
                    # BUG-C3 fix: Calculate and log cache age to make stale data visible
                    now = datetime.now(timezone.utc)
                    age_seconds = (now - cache_timestamp).total_seconds()
                    age_minutes = age_seconds / 60
                    age_hours = age_minutes / 60

                    # Log at ERROR level so it's highly visible
                    if age_hours >= 1:
                        logger.error(
                            "⚠️  SERVING STALE CACHED DATA: %s positions from cache (%.1f hours old) - Network unavailable",
                            len(cached),
                            age_hours
                        )
                    else:
                        logger.error(
                            "⚠️  SERVING STALE CACHED DATA: %s positions from cache (%.0f minutes old) - Network unavailable",
                            len(cached),
                            age_minutes
                        )

                    # Annotate with both origin and cache age for UI to use
                    annotated = self._annotate_origin(cached, origin='cache')

                    # SAR-1zb FIX: Also mark if device cache is stale
                    # This warns coordinators that team roster may have changed
                    with self._cache_lock:
                        device_cache_is_stale = self._device_cache_stale

                    for record in annotated:
                        record['cache_age_seconds'] = age_seconds
                        record['cache_timestamp'] = format_iso(cache_timestamp)
                        record['device_cache_stale'] = device_cache_is_stale

                    if device_cache_is_stale:
                        logger.warning(
                            "SAR-1zb: Device cache also stale - team roster may have changed"
                        )

                    return annotated

            raise
        except Exception as e:
            # Wrap unexpected errors
            raise ProviderDataError(
                f"Unexpected error fetching current positions: {str(e)}",
                provider_name='traccar_http',
                recoverable=False
            )

    def get_breadcrumbs(
        self,
        since_iso: Optional[str] = None,
        mission_id: Optional[int] = None,
        session=None,
        cancel_check: Optional[Callable[[], bool]] = None,
        progress_callback: Optional[Callable[[float], None]] = None
    ) -> List[FeatureDict]:
        """
        Get breadcrumb trail for all devices.

        Uses per-device /api/positions?deviceId=X&from=...&to=... queries.
        For each device, fetches positions within time window and normalizes.

        Args:
            since_iso: Optional ISO8601 timestamp to filter from (default: last 3 hours)
            mission_id: Optional mission ID (ignored by HTTP provider)
            session: Optional requests.Session for thread-safe execution
            cancel_check: Optional callable returning True to request cancellation
            progress_callback: Optional callable receiving progress (0.0-1.0)

        Returns:
            List of position features sorted by (device_id, timestamp)

        Raises:
            ProviderAuthError: If authentication fails
            ProviderNetworkError: If network request fails
            ProviderDataError: If API response invalid

        Thread-Safety:
            Safe when each task creates its own session.
        """
        logger.info("Fetching breadcrumbs (since=%s)", since_iso or "last 3 hours")
        # BUG-PF-001 fix: Protect list access with lock
        with self._cache_lock:
            self._last_breadcrumb_failures = []

        def _should_cancel() -> bool:
            return bool(cancel_check and cancel_check())

        def _report_progress(completed: int, total: int):
            if not progress_callback:
                return
            total = max(total, 1)
            fraction = max(0.0, min(1.0, completed / total))
            try:
                progress_callback(fraction)
            except Exception as progress_err:
                message = f"Breadcrumb progress callback failed: {progress_err}"
                logger.error(message)
                raise ProviderError(message) from progress_err

        if _should_cancel():
            logger.info("Breadcrumb fetch canceled before start")
            return []

        session_pool = None
        executor = None
        all_sessions = []  # SAR-vk6: Track all sessions for guaranteed cleanup
        all_sessions_lock = threading.Lock()
        try:
            # Create session if not provided
            if session is None:
                session = self._create_session()
                close_session = True
            else:
                close_session = False

            try:
                # Load device cache first
                device_map = self._load_devices(force=False, session=session)
                device_count = len(device_map)

                if _should_cancel():
                    logger.info("Breadcrumb fetch canceled before time window setup")
                    return []

                # Determine time range using timeparse utilities
                if since_iso:
                    # Parse user-provided timestamp
                    from_dt = parse_iso(since_iso)
                    from_iso = format_iso(from_dt)
                else:
                    # Default: last 3 hours
                    from_iso, _ = window(hours=3)

                # Current time
                to_iso = format_iso(datetime.now(timezone.utc))

                logger.debug("Breadcrumb time window: %s -> %s", from_iso, to_iso)

                # Optional bulk fetch (single request) to reduce API load
                if self.enable_bulk_breadcrumbs:
                    try:
                        bulk_params = {'from': from_iso, 'to': to_iso}
                        bulk_data = self.http_client.get(
                            "/api/positions",
                            session=session,
                            params=bulk_params,
                            expect_json=True
                        )
                        if isinstance(bulk_data, list):
                            bulk_positions = []
                            for pos in bulk_data:
                                try:
                                    feature = self._normalize_position(pos, device_map)
                                    bulk_positions.append(feature)
                                except Exception as e:
                                    logger.warning("Failed to normalize bulk breadcrumb record: %s", e)
                            bulk_positions.sort(key=lambda x: (x['device_id'], x['ts']))
                            logger.info("Bulk breadcrumbs fetched: %s positions", len(bulk_positions))
                            annotated_bulk = self._annotate_origin(bulk_positions, origin='live')
                            _report_progress(1, 1)
                            return annotated_bulk
                        else:
                            logger.warning(
                                "Bulk breadcrumb response invalid (type=%s); falling back to per-device",
                                type(bulk_data).__name__
                            )
                    except Exception as bulk_err:
                        logger.warning(
                            "Bulk breadcrumb fetch failed: %s; falling back to per-device",
                            bulk_err
                        )

                # Fetch breadcrumbs for each device in parallel
                all_positions = []
                session_pool = queue.Queue()
                total_devices = max(device_count, 1)

                if device_count == 0:
                    _report_progress(1, 1)
                    return []

                pool_size = max(1, min(self.breadcrumb_workers, device_count))
                for _ in range(pool_size):
                    s = self._create_session()
                    with all_sessions_lock:
                        all_sessions.append(s)
                    session_pool.put(s)

                cancel_requested = False
                processed_devices = 0
                executor = concurrent.futures.ThreadPoolExecutor(max_workers=pool_size)

                # SAR-anf: Track slow devices to identify timeout cascade sources
                slow_device_threshold_s = 5.0  # Log if device takes longer than 5 seconds

                # Helper function for parallel execution
                def fetch_device_breadcrumbs(device_id_str, device_name):
                    # SAR-anf: Time the fetch to detect slow devices
                    fetch_start = time.monotonic()
                    try:
                        if _should_cancel():
                            return []

                        # Query parameters
                        params = {
                            'deviceId': device_id_str,
                            'from': from_iso,
                            'to': to_iso
                        }

                        # Fetch positions for this device using pooled session
                        try:
                            worker_session = session_pool.get_nowait()
                            from_pool = True
                        except queue.Empty:
                            # SAR-vk6: Track ad-hoc sessions for guaranteed cleanup
                            worker_session = self._create_session()
                            with all_sessions_lock:
                                all_sessions.append(worker_session)
                            from_pool = False

                        try:
                            data = self.http_client.get(
                                "/api/positions",
                                session=worker_session,
                                params=params,
                                expect_json=True
                            )
                        except Exception as http_err:
                            message = f"{device_name}: HTTP error {http_err}"
                            # BUG-PF-001 fix: Protect list access with lock
                            with self._cache_lock:
                                self._last_breadcrumb_failures.append(message)
                            logger.warning("Failed HTTP breadcrumb fetch for %s: %s", device_name, http_err)
                            return []
                        finally:
                            # SAR-vk6: Return pooled sessions; ad-hoc sessions are cleaned up
                            # at shutdown via all_sessions list (no early close needed)
                            if from_pool:
                                session_pool.put(worker_session)

                        # Validate response type
                        if not isinstance(data, list):
                            message = (
                                f"{device_name}: invalid response type {type(data).__name__}"
                            )
                            # BUG-PF-001 fix: Protect list access with lock
                            with self._cache_lock:
                                self._last_breadcrumb_failures.append(message)
                            logger.warning(
                                "Invalid breadcrumb response for device %s: expected list, got %s",
                                device_id_str,
                                type(data).__name__
                            )
                            return []

                        # Normalize each position
                        device_positions = []
                        for pos in data:
                            try:
                                feature = self._normalize_position(pos, device_map)
                                device_positions.append(feature)
                            except Exception as e:
                                # BUG-PF-001 fix: Protect list access with lock
                                with self._cache_lock:
                                    self._last_breadcrumb_failures.append(
                                        f"{device_name}: invalid position payload ({e})"
                                    )
                                continue

                        # SAR-anf: Log slow devices that may cause timeout cascades
                        fetch_duration = time.monotonic() - fetch_start
                        if fetch_duration > slow_device_threshold_s:
                            logger.warning(
                                "SAR-anf: Slow breadcrumb fetch for '%s' took %.1fs (threshold: %.1fs) - "
                                "may cause timeout cascade",
                                device_name, fetch_duration, slow_device_threshold_s
                            )

                        return device_positions

                    except Exception as e:
                        message = f"{device_name}: unexpected error {e}"
                        # BUG-PF-001 fix: Protect list access with lock
                        with self._cache_lock:
                            self._last_breadcrumb_failures.append(message)
                        logger.warning(
                            "Failed to fetch breadcrumbs for device %s: %s",
                            device_name,
                            e
                        )
                        return []

                # Execute in parallel
                future_to_device = {
                    executor.submit(fetch_device_breadcrumbs, d_id, d_name): (d_id, d_name)
                    for d_id, d_name in device_map.items()
                }

                try:
                    for future in concurrent.futures.as_completed(future_to_device):
                        device_id_str, device_name = future_to_device[future]
                        try:
                            results = future.result()
                        except Exception as worker_exc:
                            message = f"{device_name}: worker error {worker_exc}"
                            # BUG-PF-001 fix: Protect list access with lock
                            with self._cache_lock:
                                self._last_breadcrumb_failures.append(message)
                            logger.warning(
                                "Breadcrumb worker failed for device %s: %s",
                                device_name,
                                worker_exc
                            )
                            results = []

                        if results:
                            all_positions.extend(results)

                        processed_devices += 1
                        _report_progress(processed_devices, total_devices)

                        if _should_cancel():
                            cancel_requested = True
                            break
                finally:
                    # SAR-vk6: ALWAYS wait for workers to finish before cleanup
                    # to prevent session pool exhaustion. Use cancel_futures to
                    # prevent queued work from starting, but still wait for in-flight.
                    # Python 3.8 compatibility: cancel_futures was added in 3.9.
                    try:
                        executor.shutdown(wait=True, cancel_futures=cancel_requested)
                    except TypeError:
                        # Python 3.8: no cancel_futures, just wait for completion
                        executor.shutdown(wait=True)

                # Sort by (device_id, timestamp)
                all_positions.sort(key=lambda x: (x['device_id'], x['ts']))

                logger.info(
                    "Fetched %s breadcrumb positions for %s devices",
                    len(all_positions),
                    len(device_map)
                )

                if cancel_requested:
                    logger.info(
                        "Breadcrumb fetch canceled after %s/%s devices; returning partial data",
                        processed_devices,
                        device_count
                    )
                    _report_progress(processed_devices, total_devices)
                    return self._annotate_origin(all_positions, origin='live')

                _report_progress(total_devices, total_devices)
                annotated_positions = self._annotate_origin(all_positions, origin='live')

                return annotated_positions

            finally:
                # SAR-vk6: Close ALL tracked sessions (both pooled and ad-hoc).
                # This runs AFTER executor.shutdown(wait=True), so all workers
                # have finished and returned their sessions.
                if all_sessions:
                    for tracked_session in all_sessions:
                        try:
                            tracked_session.close()
                        except Exception:
                            pass

                # Close session if we created it
                if close_session:
                    try:
                        session.close()
                    except Exception as e:
                        logger.warning("Error closing session after breadcrumbs fetch: %s", e)

        except (ProviderAuthError, ProviderNetworkError, ProviderDataError) as prov_err:
            if self.enable_last_good_cache:
                cached_breadcrumbs = self._load_last_good_breadcrumbs()
                if cached_breadcrumbs:
                    logger.warning(
                        "%s fetching breadcrumbs; using cached breadcrumbs (%s points)",
                        prov_err.__class__.__name__,
                        len(cached_breadcrumbs)
                    )
                    _report_progress(1, 1)
                    return self._annotate_origin(cached_breadcrumbs, origin='cache')
            # Re-raise provider errors
            raise
        except Exception as e:
            # Wrap unexpected errors
            raise ProviderDataError(
                f"Unexpected error fetching breadcrumbs: {str(e)}",
                provider_name='traccar_http',
                recoverable=False
            )

    def get_devices(self, session=None) -> List[Dict[str, Any]]:
        """
        Get list of all devices.

        Fetches devices from API and normalizes to Base Provider schema.

        Args:
            session: Optional requests.Session for thread-safe execution

        Returns:
            List of device metadata dicts with keys:
                - device_id: str (unique identifier)
                - name: str (display name)
                - status: str ('online', 'offline', 'unknown')
                - last_update: Optional[str] (ISO8601 timestamp)

        Raises:
            ProviderAuthError: If authentication fails
            ProviderNetworkError: If network request fails
            ProviderDataError: If API response invalid

        Thread-Safety:
            Safe when each task creates its own session.
        """
        logger.info("Fetching devices from /api/devices")

        try:
            # Create session if not provided
            if session is None:
                session = self._create_session()
                close_session = True
            else:
                close_session = False

            try:
                # Fetch devices
                data = self.http_client.get("/api/devices", session=session, expect_json=True)

                # Validate response type
                if not isinstance(data, list):
                    raise ProviderDataError(
                        f"Invalid /api/devices response: expected list, got {type(data).__name__}",
                        provider_name='traccar_http',
                        recoverable=False
                    )

                # Update device cache so subsequent calls during this refresh don't re-fetch
                device_map = self._build_device_map(data)
                self._set_device_cache(device_map)
                logger.info("Device cache updated via get_devices: %s devices", len(device_map))

                # Normalize each device
                devices = []
                for raw_device in data:
                    try:
                        normalized = self._normalize_device(raw_device)
                        devices.append(normalized)
                    except Exception as e:
                        # Log error but continue with other devices
                        device_id = raw_device.get('id', 'unknown')
                        logger.warning(
                            "Failed to normalize device %s: %s",
                            device_id,
                            e
                        )
                        continue

                logger.info("Fetched %s devices", len(devices))
                return devices

            finally:
                # Close session if we created it
                if close_session:
                    try:
                        session.close()
                    except Exception as e:
                        logger.warning("Error closing session after /api/devices in get_devices: %s", e)

        except (ProviderAuthError, ProviderNetworkError, ProviderDataError):
            # Re-raise provider errors
            raise
        except Exception as e:
            # Wrap unexpected errors
            raise ProviderDataError(
                f"Unexpected error fetching devices: {str(e)}",
                provider_name='traccar_http',
                recoverable=False
            )

    def _normalize_position(self, raw_pos: Dict, device_map: Dict[str, str]) -> FeatureDict:
        """
        Normalize Traccar API position response to Base Provider schema.

        Args:
            raw_pos: Raw position dict from Traccar API
            device_map: Device ID to name mapping

        Returns:
            Normalized feature dict with standardized schema

        Raises:
            ValueError: If position data invalid or missing required fields
        """
        # VALIDATE INPUT
        if not isinstance(raw_pos, dict):
            raise ValueError(f"Invalid position: expected dict, got {type(raw_pos).__name__}")

        # EXTRACT device_id
        device_id = raw_pos.get('deviceId')
        if device_id is None:
            raise ValueError("Position missing required 'deviceId' field")
        device_id_str = str(device_id)

        # EXTRACT device name from cache
        # SAR-5h1 FIX: Track when fallback name is used so UI can indicate unknown devices
        name_from_cache = device_map.get(device_id_str)
        if name_from_cache:
            name = name_from_cache
            name_unresolved = False
        else:
            name = f"Device {device_id_str}"
            name_unresolved = True
            logger.warning(
                "SAR-5h1: Unknown device %s - using fallback name '%s' (device may be new or cache stale)",
                device_id_str, name
            )

        # EXTRACT coordinates
        lat = raw_pos.get('latitude')
        lon = raw_pos.get('longitude')

        if lat is None or lon is None:
            raise ValueError(f"Position missing coordinates: lat={lat}, lon={lon}")

        # VALIDATE coordinates (AI_CODE_REFERENCE.md - mandatory pattern)
        lat, lon = validate_coordinate_pair(lat, lon)

        # EXTRACT timestamp (prefer fixTime, fallback to serverTime/deviceTime)
        timestamp = raw_pos.get('fixTime') or raw_pos.get('serverTime') or raw_pos.get('deviceTime')
        if not timestamp:
            raise ValueError("Position missing timestamp (fixTime/serverTime/deviceTime)")

        # VALIDATE timestamp format (basic check - parse_iso will validate fully if needed)
        if not isinstance(timestamp, str) or len(timestamp) < 10:
            raise ValueError(f"Invalid timestamp format: {timestamp}")

        # EXTRACT optional attributes
        altitude = raw_pos.get('altitude')
        speed = raw_pos.get('speed')

        # Battery level may be in attributes dict
        attributes = raw_pos.get('attributes', {})
        battery = attributes.get('batteryLevel') if isinstance(attributes, dict) else None

        # RETURN NORMALIZED DICT
        return {
            'device_id': device_id_str,
            'name': name,
            'name_unresolved': name_unresolved,  # SAR-5h1: Flag for UI to indicate unknown devices
            'lat': lat,
            'lon': lon,
            'ts': timestamp,
            'altitude': altitude,
            'speed': speed,
            'battery': battery
        }

    def _normalize_device(self, raw_device: Dict) -> Dict[str, Any]:
        """
        Normalize Traccar API device response to Base Provider schema.

        Args:
            raw_device: Raw device dict from Traccar API

        Returns:
            Normalized device dict with standardized schema
        """
        # VALIDATE INPUT
        if not isinstance(raw_device, dict):
            raise ValueError(f"Invalid device: expected dict, got {type(raw_device).__name__}")

        # EXTRACT device_id
        device_id = raw_device.get('id')
        if device_id is None:
            raise ValueError("Device missing required 'id' field")
        device_id_str = str(device_id)

        # EXTRACT name
        name_val = raw_device.get('name')
        if isinstance(name_val, str) and name_val.strip():
            name = name_val.strip()
        else:
            name = f"Device {device_id_str}"

        # NORMALIZE status
        raw_status_val = raw_device.get('status')
        if isinstance(raw_status_val, str):
            raw_status = raw_status_val.lower().strip()
        else:
            raw_status = 'unknown'

        if raw_status == 'online':
            status = 'online'
        elif raw_status in ('offline', 'disabled'):
            status = 'offline'
        else:
            status = 'unknown'

        # EXTRACT last_update
        last_update = raw_device.get('lastUpdate')

        # RETURN NORMALIZED DICT
        return {
            'device_id': device_id_str,
            'name': name,
            'status': status,
            'last_update': last_update
        }

    def _save_last_good_cache(self, features: List[FeatureDict], breadcrumbs: Optional[List[FeatureDict]] = None):
        """
        Save last-good positions to cache file for offline resilience.

        Args:
            features: List of feature dicts to cache
            breadcrumbs: Optional list of breadcrumb feature dicts to cache
        """
        if not self.enable_last_good_cache:
            return

        try:
            cache_data = {
                'timestamp': format_iso(datetime.now(timezone.utc)),
                'features': features
            }
            if breadcrumbs is not None:
                cache_data['breadcrumbs'] = breadcrumbs

            tmp_file = f"{_CACHE_FILE}.tmp"
            with self._cache_lock:
                os.makedirs(_CACHE_DIR, exist_ok=True)
                try:
                    with open(tmp_file, 'w', encoding='utf-8') as f:
                        json.dump(cache_data, f, indent=2)
                        f.flush()
                        os.fsync(f.fileno())
                    os.replace(tmp_file, _CACHE_FILE)
                    # BUG-C1 fix: Fsync parent directory to ensure directory entry is persisted
                    try:
                        dir_fd = os.open(_CACHE_DIR, os.O_RDONLY)
                        try:
                            os.fsync(dir_fd)
                        finally:
                            os.close(dir_fd)
                    except (OSError, AttributeError):
                        # OSError: Can't open directory (some filesystems)
                        # AttributeError: O_RDONLY not available on Windows
                        pass
                finally:
                    with contextlib.suppress(FileNotFoundError):
                        os.remove(tmp_file)

            if breadcrumbs is not None:
                logger.info(
                    "Saved %s positions and %s breadcrumbs to last-good cache",
                    len(features),
                    len(breadcrumbs)
                )
            else:
                logger.info(
                    "Saved %s positions to last-good cache",
                    len(features)
                )

        except Exception as e:
            # Don't let cache save failures propagate - log and continue
            logger.warning("Failed to save last-good cache: %s", e)

    def _purge_cache_file(self, reason: str):
        """
        Remove corrupt cache file to allow clean recreation.

        Args:
            reason: Human-readable reason for purge.
        """
        with self._cache_lock:
            try:
                if os.path.exists(_CACHE_FILE):
                    os.remove(_CACHE_FILE)
                    logger.warning("Removed corrupt last-good cache (%s)", reason)
            except Exception as exc:
                logger.warning("Failed to remove corrupt cache after %s: %s", reason, exc)

    def _load_last_good_cache(self, max_age_s: Optional[int] = None) -> Optional[List[FeatureDict]]:
        """
        Load last-good positions from cache file.

        Args:
            max_age_s: Maximum age of cache in seconds (default: LAST_GOOD_CACHE_MAX_AGE_S)

        Returns:
            List of feature dicts from cache, or None if cache unavailable or expired
        """
        # SAR-l07 FIX: Use configurable instance variable for default
        if max_age_s is None:
            max_age_s = self.LAST_GOOD_CACHE_MAX_AGE_S
        cache = self._read_last_good_cache(max_age_s=max_age_s)
        if cache:
            logger.info(
                "Loaded %s positions from cache (saved: %s)",
                len(cache.get('features', [])),
                cache.get('timestamp')
            )
            return cache.get('features')
        return None

    def _load_last_good_cache_with_metadata(self, max_age_s: Optional[int] = None):
        """
        Load last-good positions from cache file with timestamp metadata.

        Args:
            max_age_s: Maximum age of cache in seconds (default: LAST_GOOD_CACHE_MAX_AGE_S)

        Returns:
            Tuple of (features list, cache datetime), or None if cache unavailable or expired
        """
        # SAR-l07 FIX: Use configurable instance variable for default
        if max_age_s is None:
            max_age_s = self.LAST_GOOD_CACHE_MAX_AGE_S
        cache = self._read_last_good_cache(max_age_s=max_age_s)
        if cache:
            features = cache.get('features')
            timestamp_str = cache.get('timestamp')
            try:
                cache_timestamp = parse_iso(timestamp_str)
                return (features, cache_timestamp)
            except Exception as e:
                logger.warning("Failed to parse cache timestamp: %s", e)
                return None
        return None

    def _load_last_good_breadcrumbs(self, max_age_s: Optional[int] = None) -> Optional[List[FeatureDict]]:
        """
        Load last-good breadcrumbs from cache file (if saved).

        Args:
            max_age_s: Maximum age of cache in seconds (default: LAST_GOOD_CACHE_MAX_AGE_S)

        Returns:
            List of breadcrumb feature dicts, or None if unavailable/expired.
        """
        # SAR-l07 FIX: Use configurable instance variable for default
        if max_age_s is None:
            max_age_s = self.LAST_GOOD_CACHE_MAX_AGE_S
        cache = self._read_last_good_cache(max_age_s=max_age_s)
        if cache and cache.get('breadcrumbs'):
            logger.info(
                "Loaded %s breadcrumbs from cache (saved: %s)",
                len(cache.get('breadcrumbs', [])),
                cache.get('timestamp')
            )
            return cache.get('breadcrumbs')
        return None

    def _read_last_good_cache(self, max_age_s: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """
        Internal helper to read cache file and enforce age limits.

        Args:
            max_age_s: Maximum age of cache in seconds (default: LAST_GOOD_CACHE_MAX_AGE_S)
        """
        # SAR-l07 FIX: Use configurable instance variable for default
        if max_age_s is None:
            max_age_s = self.LAST_GOOD_CACHE_MAX_AGE_S
        if not self.enable_last_good_cache:
            return None

        with self._cache_lock:
            if not os.path.exists(_CACHE_FILE):
                logger.debug("No last-good cache file found at %s", _CACHE_FILE)
                return None

            try:
                with open(_CACHE_FILE, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
            except json.JSONDecodeError as exc:
                logger.warning("JSON decode error reading last-good cache: %s", exc)
                self._purge_cache_file(f"JSON decode error: {exc}")
                return None
            except Exception as exc:
                logger.warning("Failed to read last-good cache: %s", exc)
                return None

            if not isinstance(cache_data, dict) or 'features' not in cache_data or 'timestamp' not in cache_data:
                logger.warning("Invalid cache file structure at %s", _CACHE_FILE)
                self._purge_cache_file("Invalid cache structure")
                return None

            # BUG-066 FIX: Granular validation of cached feature data
            features = cache_data.get('features')
            if not isinstance(features, list):
                logger.warning("BUG-066: Cache features is not a list, purging cache")
                self._purge_cache_file("features not a list")
                return None

            # Validate each feature has minimum required fields
            valid_features = []
            for i, feat in enumerate(features):
                if not isinstance(feat, dict):
                    logger.debug("BUG-066: Cache feature %d is not a dict, skipping", i)
                    continue
                # Must have at least lat/lon to be useful
                if 'lat' in feat and 'lon' in feat:
                    valid_features.append(feat)
                else:
                    logger.debug("BUG-066: Cache feature %d missing lat/lon, skipping", i)

            if len(valid_features) < len(features):
                logger.warning(
                    "BUG-066: Filtered %d invalid features from cache (%d -> %d valid)",
                    len(features) - len(valid_features), len(features), len(valid_features)
                )
            cache_data['features'] = valid_features

            timestamp_str = cache_data.get('timestamp')
            try:
                cache_time = parse_iso(timestamp_str)
            except Exception as exc:
                logger.warning("Invalid cache timestamp '%s': %s", timestamp_str, exc)
                self._purge_cache_file("Invalid timestamp format")
                return None

            if cache_time.tzinfo is None:
                cache_time = cache_time.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            age = (now - cache_time).total_seconds()

            if max_age_s is not None and age > max_age_s:
                logger.info(
                    "Cache expired (age=%.1fs > max=%ss), ignoring",
                    age,
                    max_age_s
                )
                return None

            cache_data['age_seconds'] = age
            cache_data['timestamp'] = timestamp_str
            return cache_data

    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Return cache-related diagnostics for diagnostics panel/status APIs.
        """
        now = datetime.now(timezone.utc)

        cache_info = self._read_last_good_cache(max_age_s=None)
        last_good_age = None
        last_good_ts = None
        last_good_positions = None
        last_good_breadcrumbs = None
        if cache_info:
            last_good_age = cache_info.get('age_seconds')
            last_good_ts = cache_info.get('timestamp')
            last_good_positions = len(cache_info.get('features', []) or [])
            last_good_breadcrumbs = len(cache_info.get('breadcrumbs', []) or [])

        # BUG-PF-001 & BUG-PF-002 fix: Protect all cache access with lock
        with self._cache_lock:
            device_cache_size = len(self._device_cache)
            device_cache_age = None
            if self._device_cache_timestamp:
                device_cache_age = (now - self._device_cache_timestamp).total_seconds()
            device_cache_stale = self._device_cache_stale
            device_cache_warning = self._device_cache_warning
            breadcrumb_failures_copy = list(self._last_breadcrumb_failures)

        return {
            'cache_ttl_s': self.cache_ttl,
            'device_cache_size': device_cache_size,
            'device_cache_age_s': device_cache_age,
            'device_cache_stale': device_cache_stale,
            'device_cache_warning': device_cache_warning,
            'last_good_cache_age_s': last_good_age,
            'last_good_cache_ts': last_good_ts,
            'last_good_positions': last_good_positions,
            'last_good_breadcrumbs': last_good_breadcrumbs,
            'breadcrumb_workers': self.breadcrumb_workers,
            'bulk_breadcrumbs_enabled': self.enable_bulk_breadcrumbs,
            'breadcrumb_failures': breadcrumb_failures_copy
        }

    def save_casualty(self, mission_id: int, name: str, lat: float, lon: float,
                     irish_grid_e: Optional[float] = None, irish_grid_n: Optional[float] = None,
                     description: str = "") -> int:
        """
        HTTP provider does not support saving casualties.

        Raises:
            NotImplementedError
        """
        raise ProviderDataError(
            "Traccar HTTP provider does not support saving casualties",
            provider_name='traccar_http',
            recoverable=False
        )

    def save_poi(self, mission_id: int, name: str, lat: float, lon: float,
                poi_type: str = "", irish_grid_e: Optional[float] = None,
                irish_grid_n: Optional[float] = None, description: str = "",
                color: str = "#007BFF") -> int:
        """
        HTTP provider does not support saving POIs.

        Raises:
            NotImplementedError
        """
        raise ProviderDataError(
            "Traccar HTTP provider does not support saving POIs",
            provider_name='traccar_http',
            recoverable=False
        )

    def test_connection(self, session=None) -> bool:
        """
        Test connection to Traccar server.

        Performs lightweight check by fetching /api/devices and validating response.

        Args:
            session: Optional requests.Session for thread-safe execution

        Returns:
            True if connection successful, False otherwise

        Note:
            Must NOT raise exceptions (per Base Provider contract).
            All errors are caught and return False.
        """
        try:
            # Create session if not provided
            if session is None:
                session = self._create_session()
                close_session = True
            else:
                close_session = False

            try:
                # Simple API call to verify connectivity
                data = self.http_client.get("/api/devices", session=session, expect_json=True)

                # Validate response is a list
                if not isinstance(data, list):
                    message = "Connection test failed: invalid response type"
                    logger.warning(message)
                    self._last_connection_status = {
                        'success': False,
                        'message': message,
                        'timestamp': format_iso(datetime.now(timezone.utc))
                    }
                    return False

                success_message = f"Connection test successful ({len(data)} devices)"
                logger.info(success_message)
                self._last_connection_status = {
                    'success': True,
                    'message': success_message,
                    'timestamp': format_iso(datetime.now(timezone.utc))
                }
                return True

            finally:
                # Close session if we created it
                if close_session:
                    try:
                        session.close()
                    except Exception as e:
                        logger.warning("Error closing session in test_connection: %s", e)

        except Exception as e:
            # Catch all exceptions and return False (per contract)
            logger.error("Connection test failed: %s", e)
            self._last_connection_status = {
                'success': False,
                'message': str(e),
                'timestamp': format_iso(datetime.now(timezone.utc))
            }
            return False

    def get_connection_status(self) -> Dict[str, Any]:
        """
        Return last connection test status for diagnostics panels.
        """
        return dict(self._last_connection_status)

    def create_refresh_task(self, description: str,
                            since_iso: Optional[str] = None) -> 'ProviderRefreshTask':
        """
        Create Traccar-specific refresh task for background data fetching.

        Args:
            description: Human-readable task description for QGIS task manager
            since_iso: Optional ISO8601 timestamp to filter breadcrumbs from.
                       If provided (e.g., mission start time), breadcrumbs will
                       be fetched from this time instead of the default 3 hours.

        Returns:
            TraccarRefreshTask instance (inherits from ProviderRefreshTask)

        Qt5/Qt6 Compatible: Returns QgsTask subclass.
        """
        from .tasks import TraccarRefreshTask
        return TraccarRefreshTask(self, description, since_iso=since_iso)


# ============================================================================
# Provider Self-Registration
# ============================================================================

def _create_traccar_http_provider(config: Dict) -> TraccarHttpProvider:
    """
    Factory function for Traccar HTTP provider.

    Args:
        config: Configuration dict with required keys:
            - base_url: Traccar server URL (required)
            - auth_type: Authentication type ("basic" or "bearer", required)
            - username: API username (required if auth_type="basic")
            - password: API password (required if auth_type="basic")
            - token: Bearer token (required if auth_type="bearer")
            - timeout_s: Request timeout in seconds (optional, default: 10)
            - cache_ttl: Device cache TTL in seconds (optional, default: 300)
            - enable_last_good_cache: Enable offline cache (optional, default: True)

    Returns:
        TraccarHttpProvider instance

    Raises:
        ProviderDataError: If required config keys are missing or invalid
    """
    # VALIDATE CONFIG (AI_CODE_REFERENCE.md - mandatory pattern)
    if not isinstance(config, dict):
        raise ProviderDataError(
            "Traccar HTTP provider requires config dict",
            provider_name='traccar_http',
            recoverable=False
        )

    # Required fields
    required = ['base_url', 'auth_type']
    for key in required:
        if key not in config:
            raise ProviderDataError(
                f"Traccar HTTP provider requires '{key}' in config",
                provider_name='traccar_http',
                recoverable=False
            )

        if not isinstance(config[key], str) or not config[key].strip():
            raise ProviderDataError(
                f"Traccar HTTP provider '{key}' must be non-empty string",
                provider_name='traccar_http',
                recoverable=False
            )

    # Validate auth_type and required credentials
    auth_type = config['auth_type']
    if auth_type not in ['basic', 'bearer']:
        raise ProviderDataError(
            f"Traccar HTTP provider 'auth_type' must be 'basic' or 'bearer', got: {auth_type}",
            provider_name='traccar_http',
            recoverable=False
        )

    if auth_type == 'basic':
        for key in ['username', 'password']:
            if key not in config or not isinstance(config[key], str) or not config[key].strip():
                raise ProviderDataError(
                    f"Traccar HTTP provider requires '{key}' for basic auth",
                    provider_name='traccar_http',
                    recoverable=False
                )

    if auth_type == 'bearer':
        if 'token' not in config or not isinstance(config['token'], str) or not config['token'].strip():
            raise ProviderDataError(
                "Traccar HTTP provider requires 'token' for bearer auth",
                provider_name='traccar_http',
                recoverable=False
            )

    # Optional fields with defaults
    timeout_s = config.get('timeout_s', 10)
    if not isinstance(timeout_s, (int, float)) or timeout_s <= 0:
        raise ProviderDataError(
            f"Traccar HTTP provider 'timeout_s' must be positive number, got: {timeout_s}",
            provider_name='traccar_http',
            recoverable=False
        )

    cache_ttl = config.get('cache_ttl', 300)
    if not isinstance(cache_ttl, int) or cache_ttl < 0:
        raise ProviderDataError(
            f"Traccar HTTP provider 'cache_ttl' must be non-negative integer, got: {cache_ttl}",
            provider_name='traccar_http',
            recoverable=False
        )

    enable_last_good_cache = config.get('enable_last_good_cache', True)
    if not isinstance(enable_last_good_cache, bool):
        raise ProviderDataError(
            f"Traccar HTTP provider 'enable_last_good_cache' must be boolean, got: {enable_last_good_cache}",
            provider_name='traccar_http',
            recoverable=False
        )

    breadcrumb_workers = config.get('breadcrumb_workers', 10)
    if not isinstance(breadcrumb_workers, int) or breadcrumb_workers <= 0:
        raise ProviderDataError(
            f"Traccar HTTP provider 'breadcrumb_workers' must be positive integer, got: {breadcrumb_workers}",
            provider_name='traccar_http',
            recoverable=False
        )

    enable_bulk_breadcrumbs = config.get('enable_bulk_breadcrumbs', False)
    if not isinstance(enable_bulk_breadcrumbs, bool):
        raise ProviderDataError(
            f"Traccar HTTP provider 'enable_bulk_breadcrumbs' must be boolean, got: {enable_bulk_breadcrumbs}",
            provider_name='traccar_http',
            recoverable=False
        )

    # CREATE PROVIDER INSTANCE
    return TraccarHttpProvider(
        base_url=config['base_url'],
        auth_type=config['auth_type'],
        username=config.get('username'),
        password=config.get('password'),
        token=config.get('token'),
        timeout_s=int(timeout_s),
        cache_ttl=cache_ttl,
        enable_last_good_cache=enable_last_good_cache,
        breadcrumb_workers=breadcrumb_workers,
        enable_bulk_breadcrumbs=enable_bulk_breadcrumbs
    )


# Register Traccar HTTP provider with global registry
from .registry import registry, ProviderMetadata

registry.register(
    ProviderMetadata(
        name='traccar_http',
        display_name='Traccar Server (HTTP)',
        description='Optimized Traccar REST API polling with device caching and offline resilience',
        requires_config=True,
        config_schema={
            'base_url': {
                'type': 'string',
                'description': 'Traccar server URL (e.g., http://kmrtsar.eu:8082)',
                'required': True
            },
            'auth_type': {
                'type': 'string',
                'description': 'Authentication type (basic or bearer)',
                'required': True,
                'enum': ['basic', 'bearer']
            },
            'username': {
                'type': 'string',
                'description': 'API username (required for basic auth)',
                'required': False
            },
            'password': {
                'type': 'password',
                'description': 'API password (required for basic auth)',
                'required': False
            },
            'token': {
                'type': 'password',
                'description': 'Bearer token (required for bearer auth)',
                'required': False
            },
            'timeout_s': {
                'type': 'integer',
                'description': 'HTTP request timeout (seconds)',
                'required': False,
                'default': 10
            },
            'cache_ttl': {
                'type': 'integer',
                'description': 'Device cache TTL (seconds)',
                'required': False,
                'default': 300
            },
            'enable_last_good_cache': {
                'type': 'boolean',
                'description': 'Enable last-good payload cache for offline resilience',
                'required': False,
                'default': True
            },
            'breadcrumb_workers': {
                'type': 'integer',
                'description': 'Parallel workers for breadcrumb fetch (default 10)',
                'required': False,
                'default': 10
            },
            'enable_bulk_breadcrumbs': {
                'type': 'boolean',
                'description': 'Attempt bulk /api/positions for breadcrumbs before per-device',
                'required': False,
                'default': False
            }
        },
        # Phase 4 capabilities
        supports_polling=True,
        supports_streaming=False,  # WebSocket streaming in future phase
        auth_modes=['basic', 'bearer']
    ),
    _create_traccar_http_provider
)
