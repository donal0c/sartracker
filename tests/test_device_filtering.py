"""
Tests for FR-6: Active device filtering in SAR Panel.

SAR-5c6: Filter SAR Panel devices_list to show only active devices.
Definition from SAR-qvn:
- 'online' = always show (green indicator)
- 'unknown' within threshold = show (yellow indicator, "stale")
- 'unknown' beyond threshold = hide
- 'offline' = always hide

Threshold default: 1 hour (3600 seconds)
"""

import pytest
from datetime import datetime, timezone, timedelta

from utils.device_filtering import should_show_device, get_device_indicator, filter_devices


# =============================================================================
# UNIT TESTS: Filtering logic (no Qt/QGIS required)
# =============================================================================

class TestDeviceFilteringLogic:
    """Unit tests for the device filtering decision logic."""

    def test_online_device_always_shown(self):
        """Online devices should always be shown regardless of last_update."""
        device = {
            'device_id': 'dev1',
            'name': 'Team Alpha',
            'status': 'online',
            'last_update': '2020-01-01T00:00:00Z'  # Very old - doesn't matter for online
        }

        result = should_show_device(device, threshold_seconds=3600)

        assert result is True, "Online devices must always be shown"

    def test_offline_device_never_shown(self):
        """Offline devices should never be shown."""
        device = {
            'device_id': 'dev2',
            'name': 'Team Bravo',
            'status': 'offline',
            'last_update': datetime.now(timezone.utc).isoformat()  # Recent - doesn't matter
        }

        result = should_show_device(device, threshold_seconds=3600)

        assert result is False, "Offline devices must never be shown"

    def test_unknown_device_within_threshold_shown(self):
        """Unknown devices with recent last_update should be shown."""
        # 30 minutes ago - within 1 hour threshold
        recent_time = datetime.now(timezone.utc) - timedelta(minutes=30)

        device = {
            'device_id': 'dev3',
            'name': 'Team Charlie',
            'status': 'unknown',
            'last_update': recent_time.isoformat()
        }

        result = should_show_device(device, threshold_seconds=3600)

        assert result is True, "Unknown devices within threshold should be shown"

    def test_unknown_device_beyond_threshold_hidden(self):
        """Unknown devices with old last_update should be hidden."""
        # 2 hours ago - beyond 1 hour threshold
        old_time = datetime.now(timezone.utc) - timedelta(hours=2)

        device = {
            'device_id': 'dev4',
            'name': 'Team Delta',
            'status': 'unknown',
            'last_update': old_time.isoformat()
        }

        result = should_show_device(device, threshold_seconds=3600)

        assert result is False, "Unknown devices beyond threshold should be hidden"

    def test_unknown_device_at_exact_threshold_shown(self):
        """Unknown devices at exactly the threshold should be shown (inclusive)."""
        # Slightly less than 1 hour ago (59 min 59 sec) to account for test execution time
        threshold_time = datetime.now(timezone.utc) - timedelta(seconds=3599)

        device = {
            'device_id': 'dev5',
            'name': 'Team Echo',
            'status': 'unknown',
            'last_update': threshold_time.isoformat()
        }

        result = should_show_device(device, threshold_seconds=3600)

        assert result is True, "Unknown devices at threshold boundary should be shown"

    def test_unknown_device_without_last_update_hidden(self):
        """Unknown devices without last_update should be hidden (fail safe)."""
        device = {
            'device_id': 'dev6',
            'name': 'Team Foxtrot',
            'status': 'unknown',
            'last_update': None
        }

        result = should_show_device(device, threshold_seconds=3600)

        assert result is False, "Unknown devices without last_update should be hidden"

    def test_device_with_missing_status_treated_as_unknown(self):
        """Devices with missing status should be treated as unknown."""
        # Recent position, but no status - treat as unknown
        recent_time = datetime.now(timezone.utc) - timedelta(minutes=30)

        device = {
            'device_id': 'dev7',
            'name': 'Team Golf',
            # No 'status' key
            'last_update': recent_time.isoformat()
        }

        result = should_show_device(device, threshold_seconds=3600)

        assert result is True, "Missing status with recent update should be shown"

    def test_custom_threshold_respected(self):
        """Custom threshold values should be respected."""
        # 45 minutes ago
        time_45min_ago = datetime.now(timezone.utc) - timedelta(minutes=45)

        device = {
            'device_id': 'dev8',
            'name': 'Team Hotel',
            'status': 'unknown',
            'last_update': time_45min_ago.isoformat()
        }

        # 30 minute threshold - should be hidden
        result_short = should_show_device(device, threshold_seconds=1800)
        assert result_short is False, "Should be hidden with 30-min threshold"

        # 1 hour threshold - should be shown
        result_long = should_show_device(device, threshold_seconds=3600)
        assert result_long is True, "Should be shown with 1-hour threshold"


class TestDeviceIndicator:
    """Unit tests for device status indicator selection."""

    def test_online_device_gets_green_indicator(self):
        """Online devices should get green indicator."""
        device = {'status': 'online'}
        indicator = get_device_indicator(device)

        assert indicator == '\U0001F7E2', "Online devices should have green indicator"

    def test_offline_device_gets_red_indicator(self):
        """Offline devices should get red indicator."""
        device = {'status': 'offline'}
        indicator = get_device_indicator(device)

        assert indicator == '\U0001F534', "Offline devices should have red indicator"

    def test_unknown_stale_device_gets_yellow_indicator(self):
        """Unknown/stale devices should get yellow indicator (not white)."""
        device = {'status': 'unknown'}
        indicator = get_device_indicator(device)

        assert indicator == '\U0001F7E1', "Unknown/stale devices should have yellow indicator"

    def test_missing_status_gets_yellow_indicator(self):
        """Devices with missing status should get yellow indicator."""
        device = {}  # No status key
        indicator = get_device_indicator(device)

        assert indicator == '\U0001F7E1', "Missing status should have yellow indicator"


class TestFilterDevicesList:
    """Integration tests for the filter_devices function."""

    def test_filter_removes_offline_devices(self):
        """filter_devices should remove offline devices from list."""
        devices = [
            {'device_id': '1', 'name': 'Online1', 'status': 'online', 'last_update': '2026-01-01T12:00:00Z'},
            {'device_id': '2', 'name': 'Offline1', 'status': 'offline', 'last_update': '2026-01-01T12:00:00Z'},
            {'device_id': '3', 'name': 'Online2', 'status': 'online', 'last_update': '2026-01-01T12:00:00Z'},
        ]

        result = filter_devices(devices, threshold_seconds=3600)

        assert len(result) == 2
        assert all(d['status'] != 'offline' for d in result)

    def test_filter_removes_stale_unknown_devices(self):
        """filter_devices should remove unknown devices beyond threshold."""
        now = datetime.now(timezone.utc)
        recent = (now - timedelta(minutes=30)).isoformat()
        stale = (now - timedelta(hours=2)).isoformat()

        devices = [
            {'device_id': '1', 'name': 'RecentUnknown', 'status': 'unknown', 'last_update': recent},
            {'device_id': '2', 'name': 'StaleUnknown', 'status': 'unknown', 'last_update': stale},
        ]

        result = filter_devices(devices, threshold_seconds=3600)

        assert len(result) == 1
        assert result[0]['name'] == 'RecentUnknown'

    def test_filter_preserves_all_online_devices(self):
        """filter_devices should preserve all online devices."""
        devices = [
            {'device_id': '1', 'name': 'Online1', 'status': 'online', 'last_update': '2020-01-01T00:00:00Z'},
            {'device_id': '2', 'name': 'Online2', 'status': 'online', 'last_update': '2020-01-01T00:00:00Z'},
            {'device_id': '3', 'name': 'Online3', 'status': 'online', 'last_update': '2020-01-01T00:00:00Z'},
        ]

        result = filter_devices(devices, threshold_seconds=3600)

        assert len(result) == 3, "All online devices should be preserved"

    def test_filter_handles_empty_list(self):
        """filter_devices should handle empty device list."""
        result = filter_devices([], threshold_seconds=3600)

        assert result == []

    def test_filter_handles_none_gracefully(self):
        """filter_devices should handle None input gracefully."""
        result = filter_devices(None, threshold_seconds=3600)

        assert result == []


# =============================================================================
# CONFIGURATION TESTS
# =============================================================================

class TestActiveDeviceConfig:
    """Tests for the active device threshold configuration."""

    def test_default_threshold_is_one_hour(self):
        """Default threshold should be 3600 seconds (1 hour)."""
        from config.settings import ACTIVE_DEVICE_STALE_THRESHOLD_SECONDS

        assert ACTIVE_DEVICE_STALE_THRESHOLD_SECONDS == 3600, \
            "Default threshold should be 3600 seconds (1 hour)"
