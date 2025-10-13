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
        """
        self.server_url = server_url.rstrip('/')
        self.username = username
        self.password = password
        self.timeout = timeout
        self.session = requests.Session()
        self.session.auth = (username, password)
        self.session.headers.update({'Accept': 'application/json'})

    def _make_request(self, endpoint: str, params: Optional[Dict] = None) -> List[Dict]:
        """
        Make HTTP request to Traccar API.

        Args:
            endpoint: API endpoint (e.g., "/api/devices")
            params: Optional query parameters

        Returns:
            Parsed JSON response as list of dicts

        Raises:
            requests.RequestException: On network or HTTP errors
        """
        url = f"{self.server_url}{endpoint}"
        response = self.session.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def get_devices(self) -> List[Dict[str, object]]:
        """
        Get all devices from Traccar server.

        Returns:
            List of device dicts with id, name, status, etc.
        """
        try:
            return self._make_request('/api/devices')
        except Exception as e:
            raise RuntimeError(f"Failed to fetch devices: {str(e)}")

    def get_current(self) -> List[FeatureDict]:
        """
        Get current positions for all devices.

        Uses /api/positions endpoint or gets latest from recent routes.

        Returns:
            List of current position features
        """
        try:
            # Get all devices first
            devices = self.get_devices()

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
                    routes = self._make_request('/api/reports/route', params)

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

    def get_breadcrumbs(self, since_iso: Optional[str] = None) -> List[FeatureDict]:
        """
        Get historical breadcrumb trail for all devices.

        Args:
            since_iso: ISO timestamp to fetch from (default: last 3 hours)

        Returns:
            List of position features ordered by device then time
        """
        try:
            # Get all devices
            devices = self.get_devices()

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
                    routes = self._make_request('/api/reports/route', params)

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
