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
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta, timezone
import json
import os

from .base import Provider, FeatureDict
from ..utils.http import HttpClient
from ..utils.timeparse import parse_iso, format_iso, window
from ..utils.exceptions import (
    ProviderError, ProviderAuthError, ProviderNetworkError, ProviderDataError,
    validate_coordinate_pair
)

# Cache file location (OS-specific)
_CACHE_DIR = os.path.expanduser("~/.local/share/QGIS/sartracker")
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
        enable_last_good_cache: bool = True
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

        # Initialize HttpClient
        self.http_client = HttpClient(
            base_url=self.base_url,
            timeout_s=self.timeout_s,
            max_retries=3
        )

        # Device cache: {device_id: device_name, ...}
        self._device_cache: Dict[str, str] = {}
        self._device_cache_timestamp: Optional[datetime] = None

        print(f"[TRACCAR_HTTP] Initialized: {base_url} (auth={auth_type}, timeout={timeout_s}s, cache_ttl={cache_ttl}s)")

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

        if not force and self._device_cache_timestamp:
            age = (now - self._device_cache_timestamp).total_seconds()
            if age < self.cache_ttl:
                print(f"[TRACCAR_HTTP] Using cached devices (age={age:.1f}s, ttl={self.cache_ttl}s)")
                return self._device_cache

        # Cache miss or expired - fetch from API
        print(f"[TRACCAR_HTTP] Fetching devices from /api/devices (cache {'forced' if force else 'expired'})")

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

                # Build device map: {id: name}
                device_map = {}
                for device in data:
                    if not isinstance(device, dict):
                        print(f"[TRACCAR_HTTP] Warning: Skipping invalid device: {device}")
                        continue

                    # Extract device ID (prefer 'id', fallback to 'uniqueId')
                    device_id = device.get('id')
                    if device_id is None:
                        print(f"[TRACCAR_HTTP] Warning: Device missing 'id': {device}")
                        continue

                    # Convert to string for consistent handling
                    device_id_str = str(device_id)

                    # Extract device name
                    device_name = device.get('name', '').strip()
                    if not device_name:
                        device_name = f"Device {device_id_str}"

                    device_map[device_id_str] = device_name

                # Update cache
                self._device_cache = device_map
                self._device_cache_timestamp = now

                print(f"[TRACCAR_HTTP] Device cache updated: {len(device_map)} devices")
                return device_map

            finally:
                # Close session if we created it
                if close_session:
                    try:
                        session.close()
                    except Exception as e:
                        print(f"[TRACCAR_HTTP] Warning: Error closing session: {e}")

        except (ProviderAuthError, ProviderNetworkError, ProviderDataError):
            # Re-raise provider errors
            raise
        except Exception as e:
            # Wrap unexpected errors
            raise ProviderDataError(
                f"Unexpected error loading devices: {str(e)}",
                provider_name='traccar_http',
                recoverable=False
            )

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
        print("[TRACCAR_HTTP] Fetching current positions from /api/positions")

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
                        print(f"[TRACCAR_HTTP] Warning: Failed to normalize position for device {device_id}: {e}")
                        continue

                # Sort by timestamp (most recent first)
                features.sort(key=lambda x: x['ts'], reverse=True)

                print(f"[TRACCAR_HTTP] Fetched {len(features)} current positions")

                # Save to last-good cache
                if self.enable_last_good_cache and features:
                    self._save_last_good_cache(features)

                return features

            finally:
                # Close session if we created it
                if close_session:
                    try:
                        session.close()
                    except Exception as e:
                        print(f"[TRACCAR_HTTP] Warning: Error closing session: {e}")

        except (ProviderAuthError, ProviderNetworkError, ProviderDataError) as e:
            # Try loading from last-good cache on network errors
            if self.enable_last_good_cache and isinstance(e, ProviderNetworkError):
                print(f"[TRACCAR_HTTP] Network error, attempting to load last-good cache: {e}")
                cached = self._load_last_good_cache()
                if cached:
                    print(f"[TRACCAR_HTTP] Loaded {len(cached)} positions from last-good cache")
                    return cached

            # Re-raise provider errors
            raise
        except Exception as e:
            # Wrap unexpected errors
            raise ProviderDataError(
                f"Unexpected error fetching current positions: {str(e)}",
                provider_name='traccar_http',
                recoverable=False
            )

    def get_breadcrumbs(self, since_iso: Optional[str] = None, mission_id: Optional[int] = None, session=None) -> List[FeatureDict]:
        """
        Get breadcrumb trail for all devices.

        Uses per-device /api/positions?deviceId=X&from=...&to=... queries.
        For each device, fetches positions within time window and normalizes.

        Args:
            since_iso: Optional ISO8601 timestamp to filter from (default: last 3 hours)
            mission_id: Optional mission ID (ignored by HTTP provider)
            session: Optional requests.Session for thread-safe execution

        Returns:
            List of position features sorted by (device_id, timestamp)

        Raises:
            ProviderAuthError: If authentication fails
            ProviderNetworkError: If network request fails
            ProviderDataError: If API response invalid

        Thread-Safety:
            Safe when each task creates its own session.
        """
        print(f"[TRACCAR_HTTP] Fetching breadcrumbs (since={since_iso or 'last 3 hours'})")

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

                print(f"[TRACCAR_HTTP] Time window: {from_iso} to {to_iso}")

                # Fetch breadcrumbs for each device
                all_positions = []

                for device_id_str, device_name in device_map.items():
                    try:
                        # Query parameters
                        params = {
                            'deviceId': device_id_str,
                            'from': from_iso,
                            'to': to_iso
                        }

                        # Fetch positions for this device
                        data = self.http_client.get("/api/positions", session=session, params=params, expect_json=True)

                        # Validate response type
                        if not isinstance(data, list):
                            print(f"[TRACCAR_HTTP] Warning: Invalid response for device {device_id_str}: expected list, got {type(data).__name__}")
                            continue

                        # Normalize each position
                        for pos in data:
                            try:
                                feature = self._normalize_position(pos, device_map)
                                all_positions.append(feature)
                            except Exception as e:
                                print(f"[TRACCAR_HTTP] Warning: Failed to normalize breadcrumb position for device {device_id_str}: {e}")
                                continue

                    except (ProviderAuthError, ProviderNetworkError):
                        # Network/auth errors are fatal - re-raise
                        raise
                    except Exception as e:
                        # Log error but continue with other devices (graceful degradation)
                        print(f"[TRACCAR_HTTP] Warning: Failed to fetch breadcrumbs for device {device_name}: {e}")
                        continue

                # Sort by (device_id, timestamp)
                all_positions.sort(key=lambda x: (x['device_id'], x['ts']))

                print(f"[TRACCAR_HTTP] Fetched {len(all_positions)} breadcrumb positions for {len(device_map)} devices")

                return all_positions

            finally:
                # Close session if we created it
                if close_session:
                    try:
                        session.close()
                    except Exception as e:
                        print(f"[TRACCAR_HTTP] Warning: Error closing session: {e}")

        except (ProviderAuthError, ProviderNetworkError, ProviderDataError):
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
        print("[TRACCAR_HTTP] Fetching devices from /api/devices")

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

                # Normalize each device
                devices = []
                for raw_device in data:
                    try:
                        normalized = self._normalize_device(raw_device)
                        devices.append(normalized)
                    except Exception as e:
                        # Log error but continue with other devices
                        device_id = raw_device.get('id', 'unknown')
                        print(f"[TRACCAR_HTTP] Warning: Failed to normalize device {device_id}: {e}")
                        continue

                print(f"[TRACCAR_HTTP] Fetched {len(devices)} devices")
                return devices

            finally:
                # Close session if we created it
                if close_session:
                    try:
                        session.close()
                    except Exception as e:
                        print(f"[TRACCAR_HTTP] Warning: Error closing session: {e}")

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
        name = device_map.get(device_id_str, f"Device {device_id_str}")

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
        name = raw_device.get('name', '').strip()
        if not name:
            name = f"Device {device_id_str}"

        # NORMALIZE status
        raw_status = raw_device.get('status', '').lower().strip()
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

    def _save_last_good_cache(self, features: List[FeatureDict]):
        """
        Save last-good positions to cache file for offline resilience.

        Args:
            features: List of feature dicts to cache
        """
        if not self.enable_last_good_cache:
            return

        try:
            # Ensure cache directory exists
            os.makedirs(_CACHE_DIR, exist_ok=True)

            # Write cache file
            cache_data = {
                'timestamp': format_iso(datetime.now(timezone.utc)),
                'features': features
            }

            with open(_CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, indent=2)

            print(f"[TRACCAR_HTTP] Saved {len(features)} positions to last-good cache")

        except Exception as e:
            # Don't let cache save failures propagate - log and continue
            print(f"[TRACCAR_HTTP] Warning: Failed to save last-good cache: {e}")

    def _load_last_good_cache(self) -> Optional[List[FeatureDict]]:
        """
        Load last-good positions from cache file.

        Returns:
            List of feature dicts from cache, or None if cache unavailable
        """
        if not self.enable_last_good_cache:
            return None

        try:
            # Check if cache file exists
            if not os.path.exists(_CACHE_FILE):
                print("[TRACCAR_HTTP] No last-good cache file found")
                return None

            # Read cache file
            with open(_CACHE_FILE, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)

            # Validate cache structure
            if not isinstance(cache_data, dict) or 'features' not in cache_data:
                print("[TRACCAR_HTTP] Invalid cache file structure")
                return None

            features = cache_data['features']
            timestamp = cache_data.get('timestamp', 'unknown')

            print(f"[TRACCAR_HTTP] Loaded {len(features)} positions from cache (saved: {timestamp})")
            return features

        except Exception as e:
            # Don't let cache load failures propagate - log and continue
            print(f"[TRACCAR_HTTP] Warning: Failed to load last-good cache: {e}")
            return None

    def save_casualty(self, mission_id: int, name: str, lat: float, lon: float,
                     irish_grid_e: Optional[float] = None, irish_grid_n: Optional[float] = None,
                     description: str = "") -> int:
        """
        HTTP provider does not support saving casualties.

        Raises:
            NotImplementedError
        """
        raise NotImplementedError("Traccar HTTP provider does not support saving casualties")

    def save_poi(self, mission_id: int, name: str, lat: float, lon: float,
                poi_type: str = "", irish_grid_e: Optional[float] = None,
                irish_grid_n: Optional[float] = None, description: str = "",
                color: str = "#007BFF") -> int:
        """
        HTTP provider does not support saving POIs.

        Raises:
            NotImplementedError
        """
        raise NotImplementedError("Traccar HTTP provider does not support saving POIs")

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
                    print(f"[TRACCAR_HTTP] Connection test failed: invalid response type")
                    return False

                print(f"[TRACCAR_HTTP] Connection test successful ({len(data)} devices)")
                return True

            finally:
                # Close session if we created it
                if close_session:
                    try:
                        session.close()
                    except Exception as e:
                        print(f"[TRACCAR_HTTP] Warning: Error closing session in test_connection: {e}")

        except Exception as e:
            # Catch all exceptions and return False (per contract)
            print(f"[TRACCAR_HTTP] Connection test failed: {e}")
            return False

    def create_refresh_task(self, description: str) -> 'ProviderRefreshTask':
        """
        Create Traccar-specific refresh task for background data fetching.

        Args:
            description: Human-readable task description for QGIS task manager

        Returns:
            TraccarRefreshTask instance (inherits from ProviderRefreshTask)

        Qt5/Qt6 Compatible: Returns QgsTask subclass.
        """
        from .tasks import TraccarRefreshTask
        return TraccarRefreshTask(self, description)


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

    # CREATE PROVIDER INSTANCE
    return TraccarHttpProvider(
        base_url=config['base_url'],
        auth_type=config['auth_type'],
        username=config.get('username'),
        password=config.get('password'),
        token=config.get('token'),
        timeout_s=int(timeout_s),
        cache_ttl=cache_ttl,
        enable_last_good_cache=enable_last_good_cache
    )


# Register Traccar HTTP provider with global registry
from .registry import registry, ProviderMetadata

registry.register(
    ProviderMetadata(
        name='traccar_http',
        display_name='Traccar Server (HTTP - Phase 4 MVP)',
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
            }
        },
        # Phase 4 capabilities
        supports_polling=True,
        supports_streaming=False,  # WebSocket streaming in future phase
        auth_modes=['basic', 'bearer']
    ),
    _create_traccar_http_provider
)
