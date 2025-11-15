"""
HTTP Traccar Provider

Production provider that connects to Traccar Server HTTP API.
Based on Kerry Mountain Rescue Team's existing Traccar setup.

Phase 1 - Provider Abstraction Hardening:
Updated to use ProviderError hierarchy for consistent error handling.
Raises ProviderAuthError, ProviderNetworkError, and ProviderDataError
instead of generic RuntimeError.

Existing limitations documented (per-device /api/reports/route loops)
to be addressed in Phase 4 (WebSocket provider).

Qt5/Qt6 Compatible: Pure Python implementation, no Qt dependencies.
"""

import requests
from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta
from .base import Provider, FeatureDict
from ..utils.exceptions import ProviderAuthError, ProviderNetworkError, ProviderDataError


class HttpTraccarProvider(Provider):
    """
    Provider for Traccar Server HTTP API.

    Implements the Traccar REST API endpoints:
    - GET /api/devices - List all devices
    - GET /api/reports/route - Get position history

    LIMITATIONS (Phase 1 documentation, to be addressed in Phase 4):
    Current implementation uses per-device /api/reports/route loops which
    can be slow for many devices. Phase 4 will introduce WebSocket-based
    provider for real-time updates without polling overhead.

    THREAD-SAFETY (Phase 1):
    HTTP provider is thread-safe. Each background task creates its own
    requests.Session (Issue #1 fix) to avoid sharing connection pools
    across threads. Methods accept optional 'session' parameter for
    background task usage.

    ERROR HANDLING (Phase 1):
    Raises specific ProviderError subclasses:
    - ProviderAuthError: HTTP 401/403 authentication failures
    - ProviderNetworkError: Timeouts, connection refused, DNS failures
    - ProviderDataError: Invalid API responses, malformed JSON

    Qt5/Qt6 Compatible: Pure Python implementation, no Qt dependencies.
    """

    def __init__(self, server_url: str, username: str, password: str, timeout: int = 10):
        """
        Initialize Traccar HTTP provider.

        Args:
            server_url: Base URL of Traccar server (e.g., "http://kmrtsar.eu:8082")
            username: API username
            password: API password/token
            timeout: HTTP request timeout in seconds

        THREAD-SAFETY (Issue #1 fix):
        Does NOT create a shared session - sessions are created per-task
        to avoid thread contention on connection pools.
        """
        self.server_url = server_url.rstrip('/')
        self.username = username
        self.password = password
        self.timeout = timeout
        # Do NOT create session here - sessions are per-task now (Issue #1)
        # Each background task creates its own session for thread isolation

    def _create_session(self) -> requests.Session:
        """
        Create a new requests.Session for this thread.

        THREAD-SAFETY (Issue #1 fix):
        Each background task must create its own session to avoid
        sharing connection pools and mutable state across threads.

        Returns:
            Fresh requests.Session instance configured for Traccar API
        """
        session = requests.Session()
        session.auth = (self.username, self.password)
        session.headers.update({'Accept': 'application/json'})
        return session

    def _make_request(self, endpoint: str, params: Optional[Dict] = None,
                      session: Optional[requests.Session] = None) -> List[Dict]:
        """
        Make HTTP request to Traccar API.

        Args:
            endpoint: API endpoint (e.g., "/api/devices")
            params: Optional query parameters
            session: Optional requests.Session (for thread-safe task execution).
                     If None, creates a temporary session (legacy compatibility).

        Returns:
            Parsed JSON response as list of dicts

        Raises:
            ProviderAuthError: On HTTP 401/403 authentication failures
            ProviderNetworkError: On network/timeout errors
            ProviderDataError: On invalid JSON or unexpected response format

        THREAD-SAFETY (Issue #1 fix):
        Background tasks MUST pass their own session to avoid thread contention.
        """
        url = f"{self.server_url}{endpoint}"

        # Use provided session or create temporary one (backwards compatibility)
        if session is None:
            # Legacy path: create temporary session for synchronous calls
            # (e.g., test_connection, get_devices from main thread)
            session = self._create_session()

        try:
            response = session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            return response.json()

        except requests.exceptions.HTTPError as e:
            # HTTP status code errors (4xx, 5xx)
            status_code = e.response.status_code if e.response else None

            if status_code in (401, 403):
                raise ProviderAuthError(
                    f"Authentication failed for {url}: {str(e)}",
                    provider_name='http_traccar',
                    recoverable=True
                )
            else:
                raise ProviderNetworkError(
                    f"HTTP error {status_code} for {url}: {str(e)}",
                    provider_name='http_traccar',
                    recoverable=True
                )

        except requests.exceptions.Timeout as e:
            raise ProviderNetworkError(
                f"Request timeout for {url} (>{self.timeout}s): {str(e)}",
                provider_name='http_traccar',
                recoverable=True
            )

        except requests.exceptions.ConnectionError as e:
            raise ProviderNetworkError(
                f"Connection failed for {url}: {str(e)}",
                provider_name='http_traccar',
                recoverable=True
            )

        except requests.exceptions.RequestException as e:
            # Catch-all for other requests errors (DNS, SSL, etc.)
            raise ProviderNetworkError(
                f"Network error for {url}: {str(e)}",
                provider_name='http_traccar',
                recoverable=True
            )

        except ValueError as e:
            # JSON parsing failed
            raise ProviderDataError(
                f"Invalid JSON response from {url}: {str(e)}",
                provider_name='http_traccar',
                recoverable=False
            )

    def _get_raw_devices(self, session: Optional[requests.Session] = None) -> List[Dict]:
        """
        Get raw devices from Traccar API (internal method).

        This is an internal method used by get_current() and get_breadcrumbs()
        which need the raw Traccar device IDs for API calls.

        Args:
            session: Optional requests.Session for thread-safe execution.
                     If None, creates temporary session.

        Returns:
            List of raw device dicts from Traccar API

        Raises:
            ProviderAuthError: If authentication fails
            ProviderNetworkError: If network request fails
            ProviderDataError: If response has invalid format

        THREAD-SAFETY (Issue #1 fix):
        Background tasks should pass their own session instance.
        """
        try:
            raw_devices = self._make_request('/api/devices', session=session)

            # Validate response type
            if not isinstance(raw_devices, list):
                raise ProviderDataError(
                    f"Invalid API response from /api/devices: expected list, got {type(raw_devices)}",
                    provider_name='http_traccar',
                    recoverable=False
                )

            return raw_devices

        except (ProviderAuthError, ProviderNetworkError, ProviderDataError):
            # Re-raise provider errors
            raise
        except Exception as e:
            # Wrap unexpected errors
            raise ProviderDataError(
                f"Unexpected error fetching devices: {str(e)}",
                provider_name='http_traccar',
                recoverable=False
            )

    def get_devices(self, session: Optional[requests.Session] = None) -> List[Dict[str, Any]]:
        """
        Get all devices from Traccar server.

        Args:
            session: Optional requests.Session for thread-safe execution.
                     If None, creates temporary session.

        Returns:
            List of normalized device dicts with keys:
                - device_id: str
                - name: str
                - status: str ('online', 'offline', 'unknown')
                - last_update: Optional[str] (ISO timestamp)

        Raises:
            ProviderAuthError: If authentication fails
            ProviderNetworkError: If network request fails
            ProviderDataError: If response has invalid format

        THREAD-SAFETY (Issue #1 fix):
        Background tasks should pass their own session instance.

        DATA NORMALIZATION (Issue #3 fix):
        Transforms raw Traccar API response to Base Provider schema
        for consistent UI display and diagnostics.
        """
        try:
            # Fetch raw devices from Traccar API
            raw_devices = self._get_raw_devices(session=session)

            # Normalize each device to Base Provider schema (Issue #3 fix)
            normalized_devices = []
            for raw_device in raw_devices:
                normalized = self._normalize_device(raw_device)
                normalized_devices.append(normalized)

            return normalized_devices

        except (ProviderAuthError, ProviderNetworkError, ProviderDataError):
            # Re-raise provider errors
            raise
        except Exception as e:
            # Wrap unexpected errors
            raise ProviderDataError(
                f"Unexpected error fetching devices: {str(e)}",
                provider_name='http_traccar',
                recoverable=False
            )

    def _normalize_device(self, raw_device: Dict) -> Dict[str, Any]:
        """
        Normalize Traccar API device response to Base Provider schema.

        Transforms raw /api/devices response to consistent schema expected by UI.
        Handles missing fields, type conversions, and status mapping.

        Args:
            raw_device: Raw device dict from Traccar API with fields:
                - id: int (Traccar device ID)
                - name: str (device name)
                - uniqueId: str (unique device identifier)
                - status: str (Traccar status: 'online', 'offline', 'disabled', etc.)
                - lastUpdate: str (ISO timestamp of last update)
                - ... other Traccar-specific fields

        Returns:
            Normalized device dict with keys:
                - device_id: str (string version of id or uniqueId)
                - name: str (device name, defaulted if missing)
                - status: str ('online', 'offline', 'unknown')
                - last_update: Optional[str] (ISO timestamp or None)

        MANDATORY PATTERNS:
            - Input Validation: All fields validated before use
            - Error Handling: Exceptions caught, safe defaults returned
            - Life-Safety: Invalid data defaults to 'unknown' status

        Qt5/Qt6 Compatible: Pure Python implementation.

        Issue #3 Fix: Ensures HTTP provider returns consistent schema.
        """
        try:
            # === VALIDATE INPUT ===
            if not isinstance(raw_device, dict):
                raise ValueError(f"Invalid device: expected dict, got {type(raw_device)}")

            # === EXTRACT device_id ===
            # Traccar uses 'id' (int) and 'uniqueId' (str)
            device_id = None

            # Try 'id' first (convert to string)
            if 'id' in raw_device and raw_device['id'] is not None:
                try:
                    device_id = str(raw_device['id'])
                except (ValueError, TypeError):
                    pass

            # Fallback to 'uniqueId'
            if not device_id and 'uniqueId' in raw_device:
                unique_id = raw_device.get('uniqueId')
                if unique_id and isinstance(unique_id, str):
                    device_id = unique_id.strip()

            # Final fallback
            if not device_id:
                device_id = 'Unknown'

            # === EXTRACT name ===
            name = raw_device.get('name', '').strip() if isinstance(raw_device.get('name'), str) else ''
            if not name:
                name = f"Device {device_id}"

            # === NORMALIZE status ===
            raw_status_value = raw_device.get('status', '')
            # Safely convert to lowercase string
            if isinstance(raw_status_value, str):
                raw_status = raw_status_value.lower().strip()
            else:
                raw_status = ''

            # Map Traccar status to Base Provider schema
            if raw_status == 'online':
                status = 'online'
            elif raw_status in ('offline', 'disabled'):
                # Treat disabled devices as offline for UI purposes
                status = 'offline'
            else:
                # Unknown, null, or unrecognized status
                status = 'unknown'

            # === EXTRACT last_update ===
            last_update = raw_device.get('lastUpdate')

            # Validate timestamp format (basic check)
            if last_update:
                if not isinstance(last_update, str) or len(last_update) < 10:
                    # Invalid format
                    last_update = None

            # === RETURN NORMALIZED DICT ===
            return {
                'device_id': device_id,
                'name': name,
                'status': status,
                'last_update': last_update
            }

        except Exception as e:
            # CRITICAL: Don't let normalization failure crash the refresh
            # Return safe default so UI can display something

            # Safely extract ID for logging (raw_device might not be dict)
            try:
                device_id_for_log = raw_device.get('id', 'unknown') if isinstance(raw_device, dict) else 'unknown'
                device_id_for_return = str(raw_device.get('id', 'Unknown')) if isinstance(raw_device, dict) else 'Unknown'
            except Exception:
                device_id_for_log = 'unknown'
                device_id_for_return = 'Unknown'

            print(f"Warning: Error normalizing device {device_id_for_log}: {e}")

            return {
                'device_id': device_id_for_return,
                'name': f"Device {device_id_for_return}",
                'status': 'unknown',
                'last_update': None
            }

    def get_current(self, session: Optional[requests.Session] = None) -> List[FeatureDict]:
        """
        Get current positions for all devices.

        Uses /api/positions endpoint or gets latest from recent routes.

        Args:
            session: Optional requests.Session for thread-safe execution.
                     If None, creates temporary session.

        Returns:
            List of current position features

        Raises:
            ProviderAuthError: If authentication fails
            ProviderNetworkError: If network request fails
            ProviderDataError: If response has invalid format

        THREAD-SAFETY (Issue #1 fix):
        Background tasks should pass their own session instance.
        """
        try:
            # Get raw devices (need Traccar IDs for API calls)
            devices = self._get_raw_devices(session=session)

            # Get positions for last hour to find latest per device
            current_time = datetime.utcnow()
            from_time = current_time - timedelta(hours=1)

            positions = []
            device_map = {str(d['id']): d for d in devices}

            for device in devices:
                device_id = str(device['id'])
                device_name = device.get('name', f"Device {device_id}")

                try:
                    # Get recent route for this device
                    params = {
                        'deviceId': device['id'],
                        'from': from_time.strftime('%Y-%m-%dT%H:%M:%SZ'),
                        'to': current_time.strftime('%Y-%m-%dT%H:%M:%SZ')
                    }
                    routes = self._make_request('/api/reports/route', params, session=session)

                    if routes:
                        # Get the most recent position
                        latest = max(routes, key=lambda x: x.get('fixTime', ''))

                        positions.append({
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
                    # Skip devices that error
                    print(f"Warning: Could not fetch position for device {device_name}: {e}")
                    continue

            return positions

        except (ProviderAuthError, ProviderNetworkError, ProviderDataError):
            # Re-raise provider errors
            raise
        except Exception as e:
            # Wrap unexpected errors
            raise ProviderDataError(
                f"Unexpected error fetching current positions: {str(e)}",
                provider_name='http_traccar',
                recoverable=False
            )

    def get_breadcrumbs(self, since_iso: Optional[str] = None,
                        session: Optional[requests.Session] = None) -> List[FeatureDict]:
        """
        Get historical breadcrumb trail for all devices.

        Args:
            since_iso: ISO timestamp to fetch from (default: last 3 hours)
            session: Optional requests.Session for thread-safe execution.
                     If None, creates temporary session.

        Returns:
            List of position features ordered by device then time

        Raises:
            ProviderAuthError: If authentication fails
            ProviderNetworkError: If network request fails
            ProviderDataError: If response has invalid format

        THREAD-SAFETY (Issue #1 fix):
        Background tasks should pass their own session instance.
        """
        try:
            # Get raw devices (need Traccar IDs for API calls)
            devices = self._get_raw_devices(session=session)

            # Determine time range
            current_time = datetime.utcnow()
            if since_iso:
                from_time = datetime.fromisoformat(since_iso.replace('Z', '+00:00'))
            else:
                from_time = current_time - timedelta(hours=3)

            all_positions = []

            for device in devices:
                device_id = str(device['id'])
                device_name = device.get('name', f"Device {device_id}")

                try:
                    params = {
                        'deviceId': device['id'],
                        'from': from_time.strftime('%Y-%m-%dT%H:%M:%SZ'),
                        'to': current_time.strftime('%Y-%m-%dT%H:%M:%SZ')
                    }
                    routes = self._make_request('/api/reports/route', params, session=session)

                    for pos in routes:
                        all_positions.append({
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
                    print(f"Warning: Could not fetch breadcrumbs for {device_name}: {e}")
                    continue

            # Sort by device_id then timestamp
            all_positions.sort(key=lambda x: (x['device_id'], x['ts']))

            return all_positions

        except (ProviderAuthError, ProviderNetworkError, ProviderDataError):
            # Re-raise provider errors
            raise
        except Exception as e:
            # Wrap unexpected errors
            raise ProviderDataError(
                f"Unexpected error fetching breadcrumbs: {str(e)}",
                provider_name='http_traccar',
                recoverable=False
            )

    def save_casualty(self, mission_id: int, name: str,
                     lat: float, lon: float,
                     irish_grid_e: Optional[float] = None,
                     irish_grid_n: Optional[float] = None,
                     description: str = "") -> int:
        """
        HTTP provider does not support saving casualties.

        Raises:
            NotImplementedError
        """
        raise NotImplementedError("HTTP Traccar provider does not support saving casualties")

    def save_poi(self, mission_id: int, name: str,
                lat: float, lon: float,
                poi_type: str = "",
                irish_grid_e: Optional[float] = None,
                irish_grid_n: Optional[float] = None,
                description: str = "",
                color: str = "#007BFF") -> int:
        """
        HTTP provider does not support saving POIs.

        Raises:
            NotImplementedError
        """
        raise NotImplementedError("HTTP Traccar provider does not support saving POIs")

    def test_connection(self, session: Optional[requests.Session] = None) -> bool:
        """
        Test connection to Traccar server.

        Args:
            session: Optional requests.Session for thread-safe execution.
                     If None, creates temporary session.

        Returns:
            True if connection successful, False otherwise

        THREAD-SAFETY (Issue #1 fix):
        Background tasks should pass their own session instance.
        """
        try:
            # Simple API call to verify connectivity
            self._make_request('/api/devices', session=session)
            return True
        except Exception:
            return False

    def create_refresh_task(self, description: str) -> 'ProviderRefreshTask':
        """
        Create HTTP-specific refresh task with retry logic.

        Args:
            description: Task description for progress display

        Returns:
            HTTPRefreshTask instance for background fetching

        Qt5/Qt6 Compatible: Returns QgsTask subclass.
        """
        from .tasks import HTTPRefreshTask
        return HTTPRefreshTask(self, description)


# ============================================================================
# Provider Self-Registration
# ============================================================================

def _create_http_traccar_provider(config: Dict) -> HttpTraccarProvider:
    """
    Factory function for HTTP Traccar provider.

    Args:
        config: Configuration dict with required keys:
            - server_url: Traccar server URL (required)
            - username: API username (required)
            - password: API password (required)
            - timeout: Request timeout in seconds (optional, default: 10)

    Returns:
        HttpTraccarProvider instance

    Raises:
        ProviderDataError: If required config keys are missing or invalid
    """
    # Validate config before creating provider (Phase 1 requirement)
    if not isinstance(config, dict):
        raise ProviderDataError(
            "HTTP Traccar provider requires config dict",
            provider_name='http_traccar',
            recoverable=False
        )

    required = ['server_url', 'username', 'password']
    for key in required:
        if key not in config:
            raise ProviderDataError(
                f"HTTP Traccar provider requires '{key}' in config",
                provider_name='http_traccar',
                recoverable=False
            )

        # Validate non-empty strings
        if not isinstance(config[key], str) or not config[key].strip():
            raise ProviderDataError(
                f"HTTP Traccar provider '{key}' must be non-empty string",
                provider_name='http_traccar',
                recoverable=False
            )

    # Validate timeout if provided
    timeout = config.get('timeout', 10)
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        raise ProviderDataError(
            f"HTTP Traccar provider 'timeout' must be positive number, got: {timeout}",
            provider_name='http_traccar',
            recoverable=False
        )

    return HttpTraccarProvider(
        server_url=config['server_url'],
        username=config['username'],
        password=config['password'],
        timeout=timeout
    )


# Register HTTP Traccar provider with global registry
from .registry import registry, ProviderMetadata

registry.register(
    ProviderMetadata(
        name='http_traccar',
        display_name='Traccar Server (HTTP)',
        description='Real-time tracking from Traccar Server HTTP API',
        requires_config=True,
        config_schema={
            'server_url': {
                'type': 'string',
                'description': 'Traccar server URL (e.g., http://kmrtsar.eu:8082)',
                'required': True
            },
            'username': {
                'type': 'string',
                'description': 'API username',
                'required': True
            },
            'password': {
                'type': 'password',
                'description': 'API password/token',
                'required': True
            },
            'timeout': {
                'type': 'integer',
                'description': 'HTTP request timeout (seconds)',
                'required': False,
                'default': 10
            }
        },
        # Phase 1: Provider capabilities
        supports_polling=True,  # HTTP polling via background tasks
        supports_streaming=False,  # WebSocket streaming in Phase 4
        auth_modes=['basic']  # HTTP Basic Authentication
    ),
    _create_http_traccar_provider
)
