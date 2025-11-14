"""
HTTP Traccar Provider

Production provider that connects to Traccar Server HTTP API.
Based on Kerry Mountain Rescue Team's existing Traccar setup.
"""

import requests
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from .base import Provider, FeatureDict


class HttpTraccarProvider(Provider):
    """
    Provider for Traccar Server HTTP API.

    Implements the Traccar REST API endpoints:
    - GET /api/devices - List all devices
    - GET /api/reports/route - Get position history
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
            requests.RequestException: On network or HTTP errors

        THREAD-SAFETY (Issue #1 fix):
        Background tasks MUST pass their own session to avoid thread contention.
        """
        url = f"{self.server_url}{endpoint}"

        # Use provided session or create temporary one (backwards compatibility)
        if session is None:
            # Legacy path: create temporary session for synchronous calls
            # (e.g., test_connection, get_devices from main thread)
            session = self._create_session()

        response = session.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def get_devices(self, session: Optional[requests.Session] = None) -> List[Dict[str, object]]:
        """
        Get all devices from Traccar server.

        Args:
            session: Optional requests.Session for thread-safe execution.
                     If None, creates temporary session.

        Returns:
            List of device dicts with id, name, status, etc.

        THREAD-SAFETY (Issue #1 fix):
        Background tasks should pass their own session instance.
        """
        try:
            return self._make_request('/api/devices', session=session)
        except Exception as e:
            raise RuntimeError(f"Failed to fetch devices: {str(e)}")

    def get_current(self, session: Optional[requests.Session] = None) -> List[FeatureDict]:
        """
        Get current positions for all devices.

        Uses /api/positions endpoint or gets latest from recent routes.

        Args:
            session: Optional requests.Session for thread-safe execution.
                     If None, creates temporary session.

        Returns:
            List of current position features

        THREAD-SAFETY (Issue #1 fix):
        Background tasks should pass their own session instance.
        """
        try:
            # Get all devices first
            devices = self.get_devices(session=session)

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

        except Exception as e:
            raise RuntimeError(f"Failed to fetch current positions: {str(e)}")

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

        THREAD-SAFETY (Issue #1 fix):
        Background tasks should pass their own session instance.
        """
        try:
            # Get all devices
            devices = self.get_devices(session=session)

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

        except Exception as e:
            raise RuntimeError(f"Failed to fetch breadcrumbs: {str(e)}")

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
        ValueError: If required config keys are missing
    """
    required = ['server_url', 'username', 'password']
    for key in required:
        if key not in config:
            raise ValueError(f"HTTP Traccar provider requires '{key}' in config")

    return HttpTraccarProvider(
        server_url=config['server_url'],
        username=config['username'],
        password=config['password'],
        timeout=config.get('timeout', 10)
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
        }
    ),
    _create_http_traccar_provider
)
