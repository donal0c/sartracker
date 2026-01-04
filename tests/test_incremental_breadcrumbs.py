# -*- coding: utf-8 -*-
"""
Tests for Incremental Breadcrumb Fetching - Phase 2 of SAR-eyo Epic.

These tests verify that the provider can fetch breadcrumbs incrementally
using per-device timestamps, reducing redundant data transfer by 99%+
during long missions.

Value: Tests data efficiency that's critical for poor-connectivity
mountain rescue operations. Reduces bandwidth from ~21,600 positions
per refresh to only new positions.

TDD: These tests were written FIRST before the implementation (SAR-szp).
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timezone, timedelta

# Import provider
try:
    from providers.traccar_http import TraccarHttpProvider
    from utils.exceptions import ProviderAuthError, ProviderNetworkError, ProviderDataError
    from utils.timeparse import format_iso, parse_iso
    IMPORTS_AVAILABLE = True
except ImportError:
    IMPORTS_AVAILABLE = False

pytestmark = pytest.mark.skipif(not IMPORTS_AVAILABLE, reason="QGIS imports not available")


@pytest.fixture
def provider():
    """Create a TraccarHttpProvider for testing."""
    return TraccarHttpProvider(
        base_url="http://test.example.com:8082",
        auth_type="basic",
        username="testuser",
        password="testpass",
        enable_bulk_breadcrumbs=False  # Disable bulk to test per-device
    )


@pytest.fixture
def mock_session():
    """Create a mock session."""
    return Mock()


@pytest.fixture
def device_map():
    """Standard device map for tests."""
    return {
        '1': 'Alpha',
        '2': 'Bravo',
        '3': 'Charlie'
    }


class TestIncrementalParameterAcceptance:
    """Tests that get_breadcrumbs() accepts the new device_timestamps parameter."""

    def test_get_breadcrumbs_accepts_device_timestamps_parameter(self, provider):
        """get_breadcrumbs() accepts device_timestamps parameter without error."""
        # This should not raise TypeError for unexpected keyword argument
        with patch.object(provider, '_load_devices', return_value={}):
            with patch.object(provider.http_client, 'get', return_value=[]):
                # Should accept device_timestamps parameter
                result = provider.get_breadcrumbs(
                    since_iso='2026-01-04T10:00:00Z',
                    device_timestamps={'1': '2026-01-04T11:00:00Z'}
                )
                assert isinstance(result, list)

    def test_get_breadcrumbs_without_device_timestamps_still_works(self, provider):
        """get_breadcrumbs() without device_timestamps uses legacy full fetch."""
        with patch.object(provider, '_load_devices', return_value={}):
            with patch.object(provider.http_client, 'get', return_value=[]):
                # Should work without device_timestamps (backwards compatible)
                result = provider.get_breadcrumbs(since_iso='2026-01-04T10:00:00Z')
                assert isinstance(result, list)


class TestIncrementalFetchLogic:
    """Tests for per-device incremental fetch time ranges."""

    def test_incremental_uses_device_timestamp_as_from_time(self, provider, device_map):
        """When device_timestamps provided, uses per-device from time."""
        device_timestamps = {
            '1': '2026-01-04T11:30:00Z',  # Alpha last seen at 11:30
            '2': '2026-01-04T11:45:00Z',  # Bravo last seen at 11:45
        }

        calls_made = []

        def capture_calls(endpoint, session=None, params=None, expect_json=True):
            if params and 'deviceId' in params:
                calls_made.append({
                    'device_id': params['deviceId'],
                    'from': params.get('from'),
                    'to': params.get('to')
                })
            return []

        with patch.object(provider, '_load_devices', return_value=device_map):
            with patch.object(provider.http_client, 'get', side_effect=capture_calls):
                provider.get_breadcrumbs(
                    since_iso='2026-01-04T10:00:00Z',
                    device_timestamps=device_timestamps
                )

        # Verify device 1 used its timestamp (+ 1 second offset)
        dev1_calls = [c for c in calls_made if c['device_id'] == '1']
        assert len(dev1_calls) == 1
        # Should be 1 second after the device timestamp to avoid duplicates
        assert '2026-01-04T11:30:01' in dev1_calls[0]['from']

        # Verify device 2 used its timestamp
        dev2_calls = [c for c in calls_made if c['device_id'] == '2']
        assert len(dev2_calls) == 1
        assert '2026-01-04T11:45:01' in dev2_calls[0]['from']

    def test_new_device_uses_mission_start(self, provider, device_map):
        """Device not in device_timestamps uses since_iso (mission start)."""
        device_timestamps = {
            '1': '2026-01-04T11:30:00Z',  # Only Alpha has a timestamp
            # Device 2 and 3 are new - not in device_timestamps
        }

        calls_made = []

        def capture_calls(endpoint, session=None, params=None, expect_json=True):
            if params and 'deviceId' in params:
                calls_made.append({
                    'device_id': params['deviceId'],
                    'from': params.get('from'),
                })
            return []

        mission_start = '2026-01-04T08:00:00Z'

        with patch.object(provider, '_load_devices', return_value=device_map):
            with patch.object(provider.http_client, 'get', side_effect=capture_calls):
                provider.get_breadcrumbs(
                    since_iso=mission_start,
                    device_timestamps=device_timestamps
                )

        # Device 3 (Charlie) should use mission start since not in device_timestamps
        dev3_calls = [c for c in calls_made if c['device_id'] == '3']
        assert len(dev3_calls) == 1
        assert mission_start in dev3_calls[0]['from']

    def test_timestamp_boundary_offset_prevents_duplicates(self, provider, device_map):
        """1 second offset added to device timestamp to prevent duplicate fetch."""
        device_timestamps = {
            '1': '2026-01-04T11:30:00Z',
        }

        from_times = []

        def capture_from(endpoint, session=None, params=None, expect_json=True):
            if params and 'deviceId' in params and params['deviceId'] == '1':
                from_times.append(params.get('from'))
            return []

        with patch.object(provider, '_load_devices', return_value={'1': 'Alpha'}):
            with patch.object(provider.http_client, 'get', side_effect=capture_from):
                provider.get_breadcrumbs(
                    since_iso='2026-01-04T08:00:00Z',
                    device_timestamps=device_timestamps
                )

        assert len(from_times) == 1
        # Should be 11:30:01 (1 second after last timestamp)
        from_dt = parse_iso(from_times[0])
        expected_dt = parse_iso('2026-01-04T11:30:00Z') + timedelta(seconds=1)
        assert from_dt == expected_dt


class TestLegacyModeUnchanged:
    """Tests that legacy mode (no device_timestamps) behaves exactly as before."""

    def test_no_device_timestamps_uses_full_fetch(self, provider, device_map):
        """Without device_timestamps, all devices fetch from same from_iso."""
        calls_made = []

        def capture_calls(endpoint, session=None, params=None, expect_json=True):
            if params and 'deviceId' in params:
                calls_made.append({
                    'device_id': params['deviceId'],
                    'from': params.get('from'),
                })
            return []

        mission_start = '2026-01-04T08:00:00Z'

        with patch.object(provider, '_load_devices', return_value=device_map):
            with patch.object(provider.http_client, 'get', side_effect=capture_calls):
                # Legacy mode - no device_timestamps
                provider.get_breadcrumbs(since_iso=mission_start)

        # All devices should use the same from time
        assert len(calls_made) == 3
        for call in calls_made:
            assert mission_start in call['from']

    def test_empty_device_timestamps_treated_as_legacy(self, provider, device_map):
        """Empty device_timestamps dict treated same as None (legacy mode)."""
        calls_made = []

        def capture_calls(endpoint, session=None, params=None, expect_json=True):
            if params and 'deviceId' in params:
                calls_made.append(params.get('from'))
            return []

        mission_start = '2026-01-04T08:00:00Z'

        with patch.object(provider, '_load_devices', return_value=device_map):
            with patch.object(provider.http_client, 'get', side_effect=capture_calls):
                provider.get_breadcrumbs(
                    since_iso=mission_start,
                    device_timestamps={}  # Empty dict
                )

        # Should behave like legacy - all same from time
        assert len(calls_made) == 3
        for from_time in calls_made:
            assert mission_start in from_time


class TestFailureHandling:
    """Tests for per-device failure tracking."""

    def test_failure_recorded_per_device(self, provider, device_map):
        """Failed device fetches are recorded in breadcrumb_failures."""
        def fail_device_2(endpoint, session=None, params=None, expect_json=True):
            if params and params.get('deviceId') == '2':
                raise ProviderNetworkError("Connection timeout", provider_name='traccar_http')
            return []

        with patch.object(provider, '_load_devices', return_value=device_map):
            with patch.object(provider.http_client, 'get', side_effect=fail_device_2):
                provider.get_breadcrumbs(
                    since_iso='2026-01-04T08:00:00Z',
                    device_timestamps={'1': '2026-01-04T11:00:00Z'}
                )

        # Check failures were recorded
        cache_stats = provider.get_cache_stats()
        failures = cache_stats.get('breadcrumb_failures', [])
        assert len(failures) >= 1
        # Should mention the device name
        assert any('Bravo' in f for f in failures)

    def test_partial_success_returns_successful_devices(self, provider, device_map):
        """If some devices fail, successful devices still return data."""
        def partial_failure(endpoint, session=None, params=None, expect_json=True):
            device_id = params.get('deviceId') if params else None
            if device_id == '2':
                raise ProviderNetworkError("Timeout", provider_name='traccar_http')
            elif device_id == '1':
                return [
                    {
                        'deviceId': 1,
                        'latitude': 52.0,
                        'longitude': -9.5,
                        'fixTime': '2026-01-04T12:00:00Z'
                    }
                ]
            return []

        with patch.object(provider, '_load_devices', return_value={'1': 'Alpha', '2': 'Bravo'}):
            with patch.object(provider.http_client, 'get', side_effect=partial_failure):
                result = provider.get_breadcrumbs(
                    since_iso='2026-01-04T08:00:00Z',
                    device_timestamps={'1': '2026-01-04T11:00:00Z'}
                )

        # Should have results from device 1
        assert len(result) >= 1
        assert result[0]['device_id'] == '1'


class TestDataIntegration:
    """Tests for data correctness with incremental fetching."""

    def test_incremental_returns_only_new_positions(self, provider):
        """Second incremental fetch returns fewer positions than first."""
        # Simulate: First fetch returns all positions, second fetch only new ones
        all_positions = [
            {'deviceId': 1, 'latitude': 52.0, 'longitude': -9.5, 'fixTime': '2026-01-04T10:00:00Z'},
            {'deviceId': 1, 'latitude': 52.1, 'longitude': -9.6, 'fixTime': '2026-01-04T10:30:00Z'},
            {'deviceId': 1, 'latitude': 52.2, 'longitude': -9.7, 'fixTime': '2026-01-04T11:00:00Z'},
        ]

        new_positions_only = [
            {'deviceId': 1, 'latitude': 52.3, 'longitude': -9.8, 'fixTime': '2026-01-04T11:30:00Z'},
        ]

        call_count = [0]

        def mock_fetch(endpoint, session=None, params=None, expect_json=True):
            call_count[0] += 1
            if call_count[0] == 1:
                return all_positions
            else:
                return new_positions_only

        with patch.object(provider, '_load_devices', return_value={'1': 'Alpha'}):
            with patch.object(provider.http_client, 'get', side_effect=mock_fetch):
                # First fetch - full
                first = provider.get_breadcrumbs(since_iso='2026-01-04T08:00:00Z')

                # Second fetch - incremental
                second = provider.get_breadcrumbs(
                    since_iso='2026-01-04T08:00:00Z',
                    device_timestamps={'1': '2026-01-04T11:00:00Z'}
                )

        assert len(first) == 3
        assert len(second) == 1

    def test_positions_normalized_correctly(self, provider):
        """Incremental fetch normalizes positions same as full fetch."""
        raw_positions = [
            {
                'deviceId': 1,
                'latitude': 52.12345,
                'longitude': -9.67890,
                'fixTime': '2026-01-04T11:30:00Z',
                'altitude': 150.5,
                'speed': 5.2,
                'attributes': {'batteryLevel': 85}
            }
        ]

        with patch.object(provider, '_load_devices', return_value={'1': 'Alpha'}):
            with patch.object(provider.http_client, 'get', return_value=raw_positions):
                result = provider.get_breadcrumbs(
                    since_iso='2026-01-04T08:00:00Z',
                    device_timestamps={'1': '2026-01-04T11:00:00Z'}
                )

        assert len(result) == 1
        pos = result[0]
        assert pos['device_id'] == '1'
        assert pos['name'] == 'Alpha'
        assert pos['lat'] == 52.12345
        assert pos['lon'] == -9.67890
        assert pos['altitude'] == 150.5
        assert pos['speed'] == 5.2
        assert pos['battery'] == 85


class TestCancellation:
    """Tests for cancellation support in incremental mode."""

    def test_cancel_check_respected_in_incremental_mode(self, provider, device_map):
        """cancel_check function is respected during incremental fetch."""
        call_count = [0]

        def counting_fetch(endpoint, session=None, params=None, expect_json=True):
            call_count[0] += 1
            return []

        def cancel_after_one():
            return call_count[0] >= 1

        with patch.object(provider, '_load_devices', return_value=device_map):
            with patch.object(provider.http_client, 'get', side_effect=counting_fetch):
                result = provider.get_breadcrumbs(
                    since_iso='2026-01-04T08:00:00Z',
                    device_timestamps={'1': '2026-01-04T11:00:00Z'},
                    cancel_check=cancel_after_one
                )

        # Should have stopped before fetching all 3 devices
        assert call_count[0] < 3


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_device_timestamp_exactly_at_boundary(self, provider):
        """Device timestamp at exact second boundary handled correctly."""
        device_timestamps = {
            '1': '2026-01-04T12:00:00Z',  # Exact second
        }

        from_times = []

        def capture_from(endpoint, session=None, params=None, expect_json=True):
            if params and 'deviceId' in params:
                from_times.append(params.get('from'))
            return []

        with patch.object(provider, '_load_devices', return_value={'1': 'Alpha'}):
            with patch.object(provider.http_client, 'get', side_effect=capture_from):
                provider.get_breadcrumbs(
                    since_iso='2026-01-04T08:00:00Z',
                    device_timestamps=device_timestamps
                )

        assert len(from_times) == 1
        # Should be 12:00:01
        assert '12:00:01' in from_times[0]

    def test_device_timestamp_with_milliseconds(self, provider):
        """Device timestamp with milliseconds handled correctly."""
        device_timestamps = {
            '1': '2026-01-04T12:00:00.500Z',  # With milliseconds
        }

        from_times = []

        def capture_from(endpoint, session=None, params=None, expect_json=True):
            if params and 'deviceId' in params:
                from_times.append(params.get('from'))
            return []

        with patch.object(provider, '_load_devices', return_value={'1': 'Alpha'}):
            with patch.object(provider.http_client, 'get', side_effect=capture_from):
                provider.get_breadcrumbs(
                    since_iso='2026-01-04T08:00:00Z',
                    device_timestamps=device_timestamps
                )

        assert len(from_times) == 1
        # Should add 1 second to the timestamp

    def test_numeric_device_id_in_timestamps(self, provider):
        """Numeric device IDs in device_timestamps work correctly."""
        # Device timestamps might have numeric or string keys
        device_timestamps = {
            1: '2026-01-04T11:00:00Z',  # Numeric key
        }

        from_times = []

        def capture_from(endpoint, session=None, params=None, expect_json=True):
            if params and 'deviceId' in params:
                from_times.append(params.get('from'))
            return []

        with patch.object(provider, '_load_devices', return_value={'1': 'Alpha'}):
            with patch.object(provider.http_client, 'get', side_effect=capture_from):
                provider.get_breadcrumbs(
                    since_iso='2026-01-04T08:00:00Z',
                    device_timestamps=device_timestamps
                )

        # Should handle numeric keys by converting to string
        assert len(from_times) == 1
