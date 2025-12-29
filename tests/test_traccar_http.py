# -*- coding: utf-8 -*-
"""
Unit tests for Traccar HTTP Provider (Phase 4 MVP).

Tests provider functionality without live network using mocked HTTP responses.
Verifies input validation, device caching, last-good cache, and error handling.
"""
import unittest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timezone, timedelta
import tempfile
import os
import json

# Import provider (will fail if QGIS not available, which is expected for standalone tests)
try:
    from providers.traccar_http import TraccarHttpProvider, _create_traccar_http_provider
    from utils.exceptions import ProviderAuthError, ProviderNetworkError, ProviderDataError
    IMPORTS_AVAILABLE = True
except ImportError:
    IMPORTS_AVAILABLE = False


@unittest.skipUnless(IMPORTS_AVAILABLE, "QGIS imports not available")
class TestTraccarHttpProvider(unittest.TestCase):
    """Test suite for TraccarHttpProvider (Phase 4)."""

    def setUp(self):
        """Set up test fixtures."""
        self.base_url = "http://test.example.com:8082"
        self.username = "testuser"
        self.password = "testpass"
        self.token = "test_token_123"

    def test_init_basic_auth_valid(self):
        """Test provider initialization with valid basic auth."""
        provider = TraccarHttpProvider(
            base_url=self.base_url,
            auth_type="basic",
            username=self.username,
            password=self.password
        )

        self.assertEqual(provider.base_url, self.base_url)
        self.assertEqual(provider.auth_type, "basic")
        self.assertEqual(provider.username, self.username)
        self.assertEqual(provider.password, self.password)
        self.assertEqual(provider.timeout_s, 10)
        self.assertEqual(provider.cache_ttl, 300)

    def test_init_bearer_auth_valid(self):
        """Test provider initialization with valid bearer auth."""
        provider = TraccarHttpProvider(
            base_url=self.base_url,
            auth_type="bearer",
            token=self.token
        )

        self.assertEqual(provider.auth_type, "bearer")
        self.assertEqual(provider.token, self.token)

    def test_init_basic_auth_missing_credentials(self):
        """Test provider initialization fails with missing basic auth credentials."""
        with self.assertRaises(ValueError) as cm:
            TraccarHttpProvider(
                base_url=self.base_url,
                auth_type="basic",
                username="",  # Missing username
                password=self.password
            )
        self.assertIn("username required for basic auth", str(cm.exception))

    def test_init_bearer_auth_missing_token(self):
        """Test provider initialization fails with missing bearer token."""
        with self.assertRaises(ValueError) as cm:
            TraccarHttpProvider(
                base_url=self.base_url,
                auth_type="bearer",
                token=""  # Missing token
            )
        self.assertIn("token required for bearer auth", str(cm.exception))

    def test_init_whitespace_only_base_url(self):
        """Test provider initialization fails with whitespace-only base URL."""
        with self.assertRaises(ValueError) as cm:
            TraccarHttpProvider(
                base_url="   ",  # Whitespace only
                auth_type="basic",
                username=self.username,
                password=self.password
            )
        self.assertIn("base_url cannot be empty", str(cm.exception))

    def test_init_whitespace_only_username(self):
        """Test provider initialization fails with whitespace-only username."""
        with self.assertRaises(ValueError) as cm:
            TraccarHttpProvider(
                base_url=self.base_url,
                auth_type="basic",
                username="   ",  # Whitespace only
                password=self.password
            )
        self.assertIn("username required for basic auth", str(cm.exception))

    def test_init_whitespace_only_password(self):
        """Test provider initialization fails with whitespace-only password."""
        with self.assertRaises(ValueError) as cm:
            TraccarHttpProvider(
                base_url=self.base_url,
                auth_type="basic",
                username=self.username,
                password="   "  # Whitespace only
            )
        self.assertIn("password required for basic auth", str(cm.exception))

    def test_init_whitespace_only_token(self):
        """Test provider initialization fails with whitespace-only token."""
        with self.assertRaises(ValueError) as cm:
            TraccarHttpProvider(
                base_url=self.base_url,
                auth_type="bearer",
                token="   "  # Whitespace only
            )
        self.assertIn("token required for bearer auth", str(cm.exception))

    def test_init_invalid_auth_type(self):
        """Test provider initialization fails with invalid auth type."""
        with self.assertRaises(ValueError) as cm:
            TraccarHttpProvider(
                base_url=self.base_url,
                auth_type="invalid",  # Invalid auth type
                username=self.username,
                password=self.password
            )
        self.assertIn("auth_type must be 'basic' or 'bearer'", str(cm.exception))

    def test_init_empty_base_url(self):
        """Test provider initialization fails with empty base URL."""
        with self.assertRaises(ValueError) as cm:
            TraccarHttpProvider(
                base_url="",  # Empty URL
                auth_type="basic",
                username=self.username,
                password=self.password
            )
        self.assertIn("base_url cannot be empty", str(cm.exception))

    def test_init_invalid_timeout(self):
        """Test provider initialization fails with invalid timeout."""
        with self.assertRaises(ValueError) as cm:
            TraccarHttpProvider(
                base_url=self.base_url,
                auth_type="basic",
                username=self.username,
                password=self.password,
                timeout_s=-1  # Invalid timeout
            )
        self.assertIn("timeout_s must be positive integer", str(cm.exception))

    @patch('providers.traccar_http.TraccarHttpProvider._create_session')
    @patch('providers.traccar_http.TraccarHttpProvider.http_client')
    def test_get_current_success(self, mock_http_client, mock_create_session):
        """Test get_current with successful API response."""
        # Setup provider
        provider = TraccarHttpProvider(
            base_url=self.base_url,
            auth_type="basic",
            username=self.username,
            password=self.password
        )

        # Mock session
        mock_session = Mock()
        mock_create_session.return_value = mock_session

        # Mock device response
        mock_devices = [
            {'id': 1, 'name': 'Device 1', 'status': 'online'},
            {'id': 2, 'name': 'Device 2', 'status': 'offline'}
        ]

        # Mock positions response
        mock_positions = [
            {
                'deviceId': 1,
                'latitude': 53.3498,
                'longitude': -6.2603,
                'fixTime': '2025-11-15T14:30:00Z',
                'altitude': 100.0,
                'speed': 50.0,
                'attributes': {'batteryLevel': 80.0}
            },
            {
                'deviceId': 2,
                'latitude': 53.3500,
                'longitude': -6.2600,
                'fixTime': '2025-11-15T14:25:00Z',
                'altitude': 95.0,
                'speed': 45.0,
                'attributes': {'batteryLevel': 60.0}
            }
        ]

        # Configure mock HTTP client
        provider.http_client.get = Mock(side_effect=[
            mock_devices,  # First call: get devices
            mock_positions  # Second call: get positions
        ])

        # Call get_current
        features = provider.get_current(session=mock_session)

        # Verify results
        self.assertEqual(len(features), 2)

        # Check first feature
        self.assertEqual(features[0]['device_id'], '2')  # Sorted by timestamp, most recent first
        self.assertEqual(features[0]['name'], 'Device 2')
        self.assertEqual(features[0]['lat'], 53.3500)
        self.assertEqual(features[0]['lon'], -6.2600)
        self.assertEqual(features[0]['ts'], '2025-11-15T14:25:00Z')

    @patch('providers.traccar_http.TraccarHttpProvider._create_session')
    def test_device_cache_ttl(self, mock_create_session):
        """Test device cache respects TTL."""
        provider = TraccarHttpProvider(
            base_url=self.base_url,
            auth_type="basic",
            username=self.username,
            password=self.password,
            cache_ttl=10  # 10 second TTL
        )

        mock_session = Mock()
        mock_create_session.return_value = mock_session

        mock_devices = [{'id': 1, 'name': 'Device 1'}]
        provider.http_client.get = Mock(return_value=mock_devices)

        # First call - cache miss
        device_map1 = provider._load_devices(force=False, session=mock_session)
        self.assertEqual(len(device_map1), 1)
        self.assertEqual(provider.http_client.get.call_count, 1)

        # Second call immediately - cache hit (no new API call)
        device_map2 = provider._load_devices(force=False, session=mock_session)
        self.assertEqual(len(device_map2), 1)
        self.assertEqual(provider.http_client.get.call_count, 1)  # Still 1, not 2

        # Force refresh - bypasses cache
        device_map3 = provider._load_devices(force=True, session=mock_session)
        self.assertEqual(len(device_map3), 1)
        self.assertEqual(provider.http_client.get.call_count, 2)  # Now 2

    def test_normalize_position_valid(self):
        """Test position normalization with valid data."""
        provider = TraccarHttpProvider(
            base_url=self.base_url,
            auth_type="basic",
            username=self.username,
            password=self.password
        )

        raw_pos = {
            'deviceId': 123,
            'latitude': 53.3498,
            'longitude': -6.2603,
            'fixTime': '2025-11-15T14:30:00Z',
            'altitude': 100.0,
            'speed': 50.0,
            'attributes': {'batteryLevel': 80.0}
        }

        device_map = {'123': 'Test Device'}

        feature = provider._normalize_position(raw_pos, device_map)

        self.assertEqual(feature['device_id'], '123')
        self.assertEqual(feature['name'], 'Test Device')
        self.assertEqual(feature['lat'], 53.3498)
        self.assertEqual(feature['lon'], -6.2603)
        self.assertEqual(feature['ts'], '2025-11-15T14:30:00Z')
        self.assertEqual(feature['altitude'], 100.0)
        self.assertEqual(feature['speed'], 50.0)
        self.assertEqual(feature['battery'], 80.0)

    def test_normalize_position_missing_coords(self):
        """Test position normalization fails with missing coordinates."""
        provider = TraccarHttpProvider(
            base_url=self.base_url,
            auth_type="basic",
            username=self.username,
            password=self.password
        )

        raw_pos = {
            'deviceId': 123,
            'fixTime': '2025-11-15T14:30:00Z',
            # Missing latitude and longitude
        }

        device_map = {'123': 'Test Device'}

        with self.assertRaises(ValueError) as cm:
            provider._normalize_position(raw_pos, device_map)
        self.assertIn("missing coordinates", str(cm.exception))

    def test_normalize_position_invalid_coords(self):
        """Test position normalization fails with invalid coordinates."""
        provider = TraccarHttpProvider(
            base_url=self.base_url,
            auth_type="basic",
            username=self.username,
            password=self.password
        )

        raw_pos = {
            'deviceId': 123,
            'latitude': 999.0,  # Invalid latitude
            'longitude': -6.2603,
            'fixTime': '2025-11-15T14:30:00Z'
        }

        device_map = {'123': 'Test Device'}

        with self.assertRaises(Exception):  # Should raise CoordinateError
            provider._normalize_position(raw_pos, device_map)

    def test_factory_function_valid_basic(self):
        """Test factory function with valid basic auth config."""
        config = {
            'base_url': self.base_url,
            'auth_type': 'basic',
            'username': self.username,
            'password': self.password
        }

        provider = _create_traccar_http_provider(config)

        self.assertIsInstance(provider, TraccarHttpProvider)
        self.assertEqual(provider.base_url, self.base_url)
        self.assertEqual(provider.auth_type, 'basic')

    def test_factory_function_missing_field(self):
        """Test factory function fails with missing required field."""
        config = {
            'base_url': self.base_url,
            # Missing auth_type
            'username': self.username,
            'password': self.password
        }

        with self.assertRaises(ProviderDataError) as cm:
            _create_traccar_http_provider(config)
        self.assertIn("requires 'auth_type'", str(cm.exception))

    def test_factory_function_invalid_timeout(self):
        """Test factory function fails with invalid timeout."""
        config = {
            'base_url': self.base_url,
            'auth_type': 'basic',
            'username': self.username,
            'password': self.password,
            'timeout_s': 'invalid'  # Invalid type
        }

        with self.assertRaises(ProviderDataError) as cm:
            _create_traccar_http_provider(config)
        self.assertIn("timeout_s", str(cm.exception))

    @patch('providers.traccar_http.TraccarHttpProvider._load_last_good_cache_with_metadata')
    @patch('providers.traccar_http.TraccarHttpProvider._load_devices')
    def test_get_current_network_error_uses_cache(self, mock_load_devices, mock_load_cache):
        """Ensure get_current falls back to cached payload when offline."""
        provider = TraccarHttpProvider(
            base_url=self.base_url,
            auth_type="basic",
            username=self.username,
            password=self.password
        )

        mock_load_devices.side_effect = ProviderNetworkError(
            "offline",
            provider_name='traccar_http',
            recoverable=True
        )
        cached_features = [
            {
                'device_id': '1',
                'name': 'Device 1',
                'lat': 53.0,
                'lon': -6.0,
                'ts': '2025-11-15T12:00:00Z'
            }
        ]
        cache_timestamp = datetime.now(timezone.utc) - timedelta(minutes=5)
        mock_load_cache.return_value = (cached_features, cache_timestamp)

        features = provider.get_current(session=Mock())
        self.assertEqual(len(features), 1)
        self.assertEqual(features[0]['device_id'], '1')
        self.assertEqual(features[0]['data_origin'], 'cache')
        self.assertIn('cache_age_seconds', features[0])
        mock_load_cache.assert_called_once()

    def test_last_good_cache_roundtrip(self):
        """Verify last-good cache saves and loads payloads."""
        provider = TraccarHttpProvider(
            base_url=self.base_url,
            auth_type="basic",
            username=self.username,
            password=self.password
        )

        cached_features = [
            {
                'device_id': '7',
                'name': 'Test Device',
                'lat': 12.34,
                'lon': 56.78,
                'ts': '2025-11-15T14:00:00Z'
            }
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_file = os.path.join(tmpdir, "cache.json")
            with patch('providers.traccar_http._CACHE_DIR', tmpdir), patch('providers.traccar_http._CACHE_FILE', cache_file):
                provider._save_last_good_cache(cached_features)
                loaded = provider._load_last_good_cache()
                self.assertEqual(loaded, cached_features)

    def test_last_good_cache_future_timestamp_purged(self):
        """Future cache timestamps should be rejected to avoid negative age."""
        provider = TraccarHttpProvider(
            base_url=self.base_url,
            auth_type="basic",
            username=self.username,
            password=self.password
        )

        future_ts = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        cache_payload = {
            'timestamp': future_ts,
            'features': [{
                'device_id': '1',
                'name': 'Device 1',
                'lat': 53.0,
                'lon': -6.0,
                'ts': '2025-11-15T12:00:00Z'
            }]
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_file = os.path.join(tmpdir, "cache.json")
            with patch('providers.traccar_http._CACHE_DIR', tmpdir), patch('providers.traccar_http._CACHE_FILE', cache_file):
                with open(cache_file, 'w', encoding='utf-8') as fh:
                    json.dump(cache_payload, fh)
                loaded = provider._load_last_good_cache()
                self.assertIsNone(loaded)
                self.assertFalse(os.path.exists(cache_file))

    def test_last_good_cache_filters_invalid_entries(self):
        """Invalid cached coords/timestamps are filtered out."""
        provider = TraccarHttpProvider(
            base_url=self.base_url,
            auth_type="basic",
            username=self.username,
            password=self.password
        )

        cache_payload = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'features': [
                {'device_id': '1', 'name': 'Device 1', 'lat': 53.0, 'lon': -6.0, 'ts': '2025-11-15T12:00:00Z'},
                {'device_id': '2', 'name': 'Device 2', 'lat': 999.0, 'lon': -6.0, 'ts': 'bad-ts'}
            ],
            'breadcrumbs': [
                {'device_id': '1', 'name': 'Device 1', 'lat': 53.1, 'lon': -6.1, 'ts': '2025-11-15T12:05:00Z'},
                {'device_id': '2', 'name': 'Device 2', 'lat': 0.0, 'lon': 0.0, 'ts': '2025-11-15T12:06:00Z'}
            ]
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_file = os.path.join(tmpdir, "cache.json")
            with patch('providers.traccar_http._CACHE_DIR', tmpdir), patch('providers.traccar_http._CACHE_FILE', cache_file):
                with open(cache_file, 'w', encoding='utf-8') as fh:
                    json.dump(cache_payload, fh)
                loaded_features = provider._load_last_good_cache()
                loaded_breadcrumbs = provider._load_last_good_breadcrumbs()

                self.assertEqual(len(loaded_features), 1)
                self.assertEqual(loaded_features[0]['device_id'], '1')
                self.assertEqual(len(loaded_breadcrumbs), 1)
                self.assertEqual(loaded_breadcrumbs[0]['device_id'], '1')

    @patch('providers.traccar_http.TraccarHttpProvider._load_devices')
    def test_get_breadcrumbs_success(self, mock_load_devices):
        """Test get_breadcrumbs builds normalized feature list."""
        provider = TraccarHttpProvider(
            base_url=self.base_url,
            auth_type="basic",
            username=self.username,
            password=self.password
        )

        mock_load_devices.return_value = {'1': 'Device 1'}
        provider.http_client = Mock()
        provider.http_client.get.return_value = [
            {
                'deviceId': 1,
                'latitude': 53.0,
                'longitude': -6.0,
                'fixTime': '2025-11-15T10:00:00Z',
                'attributes': {}
            },
            {
                'deviceId': 1,
                'latitude': 53.1,
                'longitude': -6.1,
                'fixTime': '2025-11-15T10:05:00Z',
                'attributes': {}
            }
        ]

        breadcrumbs = provider.get_breadcrumbs(session=Mock())
        self.assertEqual(len(breadcrumbs), 2)
        self.assertEqual(breadcrumbs[0]['device_id'], '1')
        self.assertLessEqual(breadcrumbs[0]['ts'], breadcrumbs[1]['ts'])

    def test_save_casualty_not_implemented(self):
        """Test save_casualty raises NotImplementedError."""
        provider = TraccarHttpProvider(
            base_url=self.base_url,
            auth_type="basic",
            username=self.username,
            password=self.password
        )

        with self.assertRaises(NotImplementedError):
            provider.save_casualty(
                mission_id=1,
                name="Test Casualty",
                lat=53.3498,
                lon=-6.2603
            )

    def test_save_poi_not_implemented(self):
        """Test save_poi raises NotImplementedError."""
        provider = TraccarHttpProvider(
            base_url=self.base_url,
            auth_type="basic",
            username=self.username,
            password=self.password
        )

        with self.assertRaises(NotImplementedError):
            provider.save_poi(
                mission_id=1,
                name="Test POI",
                lat=53.3498,
                lon=-6.2603
            )

    def test_save_last_good_cache_persists_breadcrumbs(self):
        """Ensure breadcrumbs are persisted alongside positions."""
        provider = TraccarHttpProvider(
            base_url=self.base_url,
            auth_type="basic",
            username=self.username,
            password=self.password
        )

        features = [{'device_id': '1', 'name': 'A', 'lat': 1.0, 'lon': 1.0, 'ts': '2025-11-15T10:00:00Z'}]
        breadcrumbs = [{'device_id': '1', 'name': 'A', 'lat': 1.0, 'lon': 1.0, 'ts': '2025-11-15T09:55:00Z'}]

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_file = os.path.join(tmpdir, "cache.json")
            with patch('providers.traccar_http._CACHE_DIR', tmpdir), patch('providers.traccar_http._CACHE_FILE', cache_file):
                provider._save_last_good_cache(features, breadcrumbs)
                loaded_breadcrumbs = provider._load_last_good_breadcrumbs(max_age_s=9999)
                self.assertEqual(len(loaded_breadcrumbs), 1)
                self.assertEqual(loaded_breadcrumbs[0]['ts'], breadcrumbs[0]['ts'])

    @patch('providers.traccar_http.TraccarHttpProvider._load_devices')
    def test_get_breadcrumbs_uses_cache_on_error(self, mock_load_devices):
        """Breadcrumb fetch falls back to cached breadcrumbs on network error."""
        provider = TraccarHttpProvider(
            base_url=self.base_url,
            auth_type="basic",
            username=self.username,
            password=self.password
        )

        mock_load_devices.side_effect = ProviderNetworkError(
            "offline",
            provider_name='traccar_http',
            recoverable=True
        )

        cached = [{'device_id': '1', 'name': 'Device 1', 'lat': 1.0, 'lon': 1.0, 'ts': '2025-11-15T10:00:00Z'}]
        with patch.object(provider, '_load_last_good_breadcrumbs', return_value=cached):
            breadcrumbs = provider.get_breadcrumbs(session=Mock())
            self.assertEqual(len(breadcrumbs), 1)
            self.assertEqual(breadcrumbs[0]['device_id'], '1')
            self.assertEqual(breadcrumbs[0]['data_origin'], 'cache')

    @patch('providers.traccar_http.TraccarHttpProvider._load_last_good_breadcrumbs')
    @patch('providers.traccar_http.TraccarHttpProvider._load_devices')
    def test_get_breadcrumbs_auth_error_raises(self, mock_load_devices, mock_load_cache):
        """Auth failures must surface, not use cached breadcrumbs."""
        provider = TraccarHttpProvider(
            base_url=self.base_url,
            auth_type="basic",
            username=self.username,
            password=self.password
        )

        mock_load_devices.return_value = {'1': 'Device 1'}
        provider.http_client.get = Mock(side_effect=ProviderAuthError(
            "unauthorized",
            provider_name='http',
            recoverable=True
        ))

        with self.assertRaises(ProviderAuthError):
            provider.get_breadcrumbs(session=Mock())

        mock_load_cache.assert_not_called()

    def test_bulk_breadcrumbs_path(self):
        """When enabled, bulk breadcrumb fetch should be attempted."""
        provider = TraccarHttpProvider(
            base_url=self.base_url,
            auth_type="basic",
            username=self.username,
            password=self.password,
            enable_bulk_breadcrumbs=True
        )

        provider._load_devices = Mock(return_value={'1': 'Device 1'})
        provider.http_client = Mock()
        provider.http_client.get.return_value = [
            {
                'deviceId': 1,
                'latitude': 53.0,
                'longitude': -6.0,
                'fixTime': '2025-11-15T10:00:00Z',
                'attributes': {}
            }
        ]

        breadcrumbs = provider.get_breadcrumbs(session=Mock())
        self.assertEqual(len(breadcrumbs), 1)
        provider.http_client.get.assert_called_once()
        args, kwargs = provider.http_client.get.call_args
        self.assertEqual(args[0], "/api/positions")
        self.assertIn('params', kwargs)
        self.assertNotIn('deviceId', kwargs['params'])

    def test_cache_stats_reports_last_good(self):
        """Cache stats include last-good positions and breadcrumbs counts."""
        provider = TraccarHttpProvider(
            base_url=self.base_url,
            auth_type="basic",
            username=self.username,
            password=self.password
        )

        provider._device_cache = {'1': 'Device 1'}
        from datetime import datetime, timezone
        provider._device_cache_timestamp = datetime.now(timezone.utc)

        cache_payload = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'features': [{'device_id': '1'}],
            'breadcrumbs': [{'device_id': '1'}]
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_file = os.path.join(tmpdir, "cache.json")
            with patch('providers.traccar_http._CACHE_DIR', tmpdir), patch('providers.traccar_http._CACHE_FILE', cache_file):
                with open(cache_file, 'w', encoding='utf-8') as fh:
                    json.dump(cache_payload, fh)
                stats = provider.get_cache_stats()
                self.assertEqual(stats['device_cache_size'], 1)
                self.assertEqual(stats['last_good_positions'], 1)
                self.assertEqual(stats['last_good_breadcrumbs'], 1)


if __name__ == '__main__':
    unittest.main()
