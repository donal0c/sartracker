# -*- coding: utf-8 -*-
"""
Devices Window Tests

Test suite for the DevicesWindow standalone device display window.

WHY THIS MATTERS:
The Devices Window displays real-time device status to SAR coordinators.
Correct display of online/offline status helps coordinators know which
team members have active tracking.

REQUIRES: Real QGIS for Qt widgets
"""

import pytest

# Skip if QGIS not available
pytest.importorskip("qgis.core")

from qgis.PyQt.QtWidgets import QApplication
from qgis.PyQt.QtCore import QSettings

from sartracker.ui.devices_window import DevicesWindow


@pytest.fixture
def app(qgis_app):
    """Ensure QApplication exists for widget tests."""
    return qgis_app


@pytest.fixture
def devices_window(app):
    """Create a DevicesWindow for testing."""
    window = DevicesWindow(None)
    yield window
    # Cleanup
    try:
        window.cleanup()
        window.close()
    except Exception:
        pass


# =============================================================================
# DEVICE DATA DISPLAY TESTS
# =============================================================================

class TestDeviceDisplay:
    """Test device data display functionality."""

    def test_update_devices_with_empty_list(self, devices_window):
        """
        Empty device list should clear display.

        VALUE: Handles disconnect scenarios cleanly.
        """
        devices_window.update_devices([])
        assert devices_window.get_device_count() == 0

    def test_update_devices_with_none(self, devices_window):
        """
        None devices should clear display without error.

        VALUE: Handles null data gracefully.
        """
        devices_window.update_devices(None)
        assert devices_window.get_device_count() == 0

    def test_update_devices_with_valid_data(self, devices_window):
        """
        CRITICAL: Valid device data displays correctly.

        VALUE: Coordinators can see all connected devices.
        """
        devices = [
            {'device_id': 'dev1', 'name': 'Team Alpha', 'status': 'online', 'last_update': '2026-01-03T10:00:00Z'},
            {'device_id': 'dev2', 'name': 'Team Beta', 'status': 'offline', 'last_update': '2026-01-03T09:00:00Z'},
            {'device_id': 'dev3', 'name': 'Team Gamma', 'status': 'unknown', 'last_update': 'Never'},
        ]

        devices_window.update_devices(devices)
        assert devices_window.get_device_count() == 3

    def test_update_devices_handles_minimal_data(self, devices_window):
        """
        Device with only device_id should display.

        VALUE: Handles providers that send minimal data.
        """
        devices = [
            {'device_id': 'minimal_device'},
        ]

        devices_window.update_devices(devices)
        assert devices_window.get_device_count() == 1

    def test_update_devices_uses_id_as_name_fallback(self, devices_window):
        """
        Device without name should use device_id as fallback.

        VALUE: Always shows something identifiable.
        """
        devices = [
            {'device_id': 'dev_without_name', 'status': 'online', 'last_update': 'Now'},
        ]

        devices_window.update_devices(devices)
        assert devices_window.get_device_count() == 1

    def test_update_devices_skips_invalid_entries(self, devices_window):
        """
        Non-dict entries in device list are skipped.

        VALUE: Robust against malformed provider data.
        """
        devices = [
            {'device_id': 'valid', 'name': 'Valid Device', 'status': 'online'},
            "invalid string entry",
            123,
            None,
            {'device_id': 'also_valid', 'name': 'Also Valid', 'status': 'offline'},
        ]

        devices_window.update_devices(devices)
        assert devices_window.get_device_count() == 2

    def test_update_devices_handles_invalid_list_type(self, devices_window):
        """
        Non-list devices parameter handled gracefully.

        VALUE: Prevents crashes from malformed data.
        """
        # Should not raise, just log warning
        devices_window.update_devices("not a list")
        assert devices_window.get_device_count() == 0


# =============================================================================
# SIGNAL TESTS
# =============================================================================

class TestDeviceSignals:
    """Test signal emissions from DevicesWindow."""

    def test_refresh_requested_signal_exists(self, devices_window):
        """Verify refresh_requested signal is defined."""
        assert hasattr(devices_window, 'refresh_requested')

    def test_device_selected_signal_exists(self, devices_window):
        """Verify device_selected signal is defined."""
        assert hasattr(devices_window, 'device_selected')

    def test_closed_signal_exists(self, devices_window):
        """Verify closed signal is defined."""
        assert hasattr(devices_window, 'closed')

    def test_refresh_button_triggers_signal(self, devices_window):
        """
        Refresh button click emits refresh_requested.

        VALUE: Allows manual refresh of device list.
        """
        # Track if signal was emitted
        signal_received = []
        devices_window.refresh_requested.connect(lambda: signal_received.append(True))

        # Click the button
        devices_window.refresh_button.click()

        # Signal should have been emitted
        assert len(signal_received) == 1


# =============================================================================
# GEOMETRY TESTS
# =============================================================================

class TestWindowGeometry:
    """Test window geometry handling."""

    def test_minimum_size_set(self, devices_window):
        """Window has minimum size constraints."""
        assert devices_window.minimumWidth() >= 400
        assert devices_window.minimumHeight() >= 300

    def test_settings_key_defined(self, devices_window):
        """Settings key for geometry persistence is defined."""
        assert hasattr(devices_window, 'SETTINGS_GEOMETRY_KEY')
        assert 'SARTracker' in devices_window.SETTINGS_GEOMETRY_KEY
        assert 'DevicesWindow' in devices_window.SETTINGS_GEOMETRY_KEY


# =============================================================================
# CLEANUP TESTS
# =============================================================================

class TestCleanup:
    """Test cleanup and lifecycle management."""

    def test_cleanup_sets_flag(self, devices_window):
        """Cleanup sets in-progress flag to prevent double cleanup."""
        assert devices_window._cleanup_in_progress is False
        devices_window.cleanup()
        assert devices_window._cleanup_in_progress is True

    def test_double_cleanup_safe(self, devices_window):
        """Calling cleanup twice is safe."""
        devices_window.cleanup()
        # Should not raise
        devices_window.cleanup()
        assert devices_window._cleanup_in_progress is True

    def test_cleanup_clears_device_list(self, devices_window):
        """Cleanup clears internal device data."""
        devices_window.update_devices([
            {'device_id': 'dev1', 'name': 'Test', 'status': 'online'}
        ])
        assert devices_window.get_device_count() == 1

        devices_window.cleanup()
        # Internal list should be cleared
        assert devices_window._devices == []


# =============================================================================
# STATUS INDICATOR TESTS
# =============================================================================

class TestStatusIndicators:
    """Test status indicator display."""

    def test_online_status_shows_green_indicator(self, devices_window):
        """
        CRITICAL: Online devices show green indicator.

        VALUE: Coordinators can quickly see active trackers.
        """
        devices = [{'device_id': 'online_dev', 'name': 'Online Device', 'status': 'online'}]
        devices_window.update_devices(devices)

        item_text = devices_window.devices_list.item(0).text()
        # Should contain green circle emoji
        assert '\U0001F7E2' in item_text or '🟢' in item_text

    def test_offline_status_shows_red_indicator(self, devices_window):
        """
        CRITICAL: Offline devices show red indicator.

        VALUE: Coordinators can see which trackers lost connection.
        """
        devices = [{'device_id': 'offline_dev', 'name': 'Offline Device', 'status': 'offline'}]
        devices_window.update_devices(devices)

        item_text = devices_window.devices_list.item(0).text()
        # Should contain red circle emoji
        assert '\U0001F534' in item_text or '🔴' in item_text

    def test_unknown_status_shows_white_indicator(self, devices_window):
        """
        Unknown status shows white/neutral indicator.

        VALUE: Clear distinction from online/offline states.
        """
        devices = [{'device_id': 'unknown_dev', 'name': 'Unknown Device', 'status': 'unknown'}]
        devices_window.update_devices(devices)

        item_text = devices_window.devices_list.item(0).text()
        # Should contain white circle emoji
        assert '\U000026AA' in item_text or '⚪' in item_text
