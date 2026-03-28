# -*- coding: utf-8 -*-
"""
Devices Controller Tests

Test suite for DevicesController functionality.

WHY THIS MATTERS:
The DevicesController manages the Devices window lifecycle and ensures
device data flows correctly from ProviderController to the UI.

Some tests require real QGIS, others can run with mocks.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch

# Import from sartracker package
from sartracker.controllers.devices_controller import DevicesController


# =============================================================================
# CONTROLLER INITIALIZATION TESTS (No QGIS required)
# =============================================================================

class TestControllerInitialization:
    """Test DevicesController initialization."""

    def test_controller_initializes_with_required_args(self):
        """Controller can be created with minimal arguments."""
        mock_iface = Mock()
        mock_iface.mainWindow.return_value = None
        mock_iface.messageBar.return_value = Mock()

        controller = DevicesController(
            iface=mock_iface,
            provider_controller=None,
            is_unloading=lambda: False,
            parent=None
        )

        assert controller is not None
        assert controller._window is None
        assert controller._is_shutting_down is False

    def test_controller_sets_is_unloading_callback(self):
        """is_unloading callback is stored."""
        mock_iface = Mock()
        mock_iface.mainWindow.return_value = None

        unloading_flag = [False]

        def is_unloading():
            return unloading_flag[0]

        controller = DevicesController(
            iface=mock_iface,
            is_unloading=is_unloading
        )

        assert controller._is_unloading_cb() is False

        unloading_flag[0] = True
        assert controller._is_unloading_cb() is True


# =============================================================================
# PROVIDER CONNECTION TESTS
# =============================================================================

class TestProviderConnection:
    """Test provider controller connection."""

    def test_set_provider_controller_stores_reference(self):
        """set_provider_controller stores the provider."""
        mock_iface = Mock()
        mock_iface.mainWindow.return_value = None

        controller = DevicesController(iface=mock_iface)

        mock_provider = Mock()
        mock_provider.refresh_complete = Mock()
        mock_provider.refresh_complete.connect = Mock()

        controller.set_provider_controller(mock_provider)

        assert controller._provider_controller is mock_provider

    def test_set_provider_controller_connects_signals(self):
        """set_provider_controller connects refresh_complete signal."""
        mock_iface = Mock()
        mock_iface.mainWindow.return_value = None

        controller = DevicesController(iface=mock_iface)

        mock_provider = Mock()
        mock_provider.refresh_complete = Mock()
        mock_provider.refresh_complete.connect = Mock()

        controller.set_provider_controller(mock_provider)

        # Verify connect was called
        mock_provider.refresh_complete.connect.assert_called()

    def test_changing_provider_disconnects_old(self):
        """Changing provider disconnects from old provider."""
        mock_iface = Mock()
        mock_iface.mainWindow.return_value = None

        controller = DevicesController(iface=mock_iface)

        # Set up first provider
        mock_provider1 = Mock()
        mock_provider1.refresh_complete = Mock()
        mock_provider1.refresh_complete.connect = Mock()
        mock_provider1.refresh_complete.disconnect = Mock()

        controller.set_provider_controller(mock_provider1)

        # Set up second provider
        mock_provider2 = Mock()
        mock_provider2.refresh_complete = Mock()
        mock_provider2.refresh_complete.connect = Mock()

        controller.set_provider_controller(mock_provider2)

        # Verify disconnect was called on first provider
        mock_provider1.refresh_complete.disconnect.assert_called()


# =============================================================================
# DATA HANDLING TESTS
# =============================================================================

class TestDataHandling:
    """Test device data handling."""

    def test_on_refresh_complete_stores_devices(self):
        """_on_refresh_complete stores device list."""
        mock_iface = Mock()
        mock_iface.mainWindow.return_value = None

        controller = DevicesController(iface=mock_iface)

        devices = [
            {'device_id': 'dev1', 'name': 'Team 1', 'status': 'online'},
            {'device_id': 'dev2', 'name': 'Team 2', 'status': 'offline'},
        ]

        controller._on_refresh_complete({'devices': devices})

        assert controller._last_devices == devices

    def test_on_refresh_complete_updates_window_with_unfiltered_devices(self):
        """Devices window should receive the full device list without layer filtering."""
        mock_iface = Mock()
        mock_iface.mainWindow.return_value = None

        controller = DevicesController(iface=mock_iface)
        controller._window = Mock()

        devices = [
            {'device_id': 'dev1', 'name': 'Team 1', 'status': 'online'},
            {'device_id': 'dev2', 'name': 'Team 2', 'status': 'offline'},
            {'device_id': 'dev3', 'name': 'Team 3', 'status': 'unknown'},
        ]

        with patch('sartracker.controllers.devices_controller.sip_isdeleted', return_value=False):
            controller._on_refresh_complete({'devices': devices})

        assert controller._last_devices == devices
        controller._window.update_devices.assert_called_once_with(devices)

    def test_on_refresh_complete_handles_missing_devices_key(self):
        """_on_refresh_complete handles result without devices key."""
        mock_iface = Mock()
        mock_iface.mainWindow.return_value = None

        controller = DevicesController(iface=mock_iface)
        controller._last_devices = [{'device_id': 'old'}]

        # Result without devices key
        controller._on_refresh_complete({'current': [], 'breadcrumbs': []})

        # Should be empty list, not old value
        assert controller._last_devices == []

    def test_on_refresh_complete_skipped_when_unloading(self):
        """_on_refresh_complete does nothing when unloading."""
        mock_iface = Mock()
        mock_iface.mainWindow.return_value = None

        controller = DevicesController(
            iface=mock_iface,
            is_unloading=lambda: True
        )
        controller._last_devices = [{'device_id': 'old'}]

        controller._on_refresh_complete({'devices': [{'device_id': 'new'}]})

        # Should not update
        assert controller._last_devices == [{'device_id': 'old'}]


# =============================================================================
# LIFECYCLE TESTS
# =============================================================================

class TestLifecycle:
    """Test controller lifecycle management."""

    def test_cleanup_sets_shutdown_flag(self):
        """cleanup() sets shutdown flag."""
        mock_iface = Mock()
        mock_iface.mainWindow.return_value = None

        controller = DevicesController(iface=mock_iface)

        assert controller._is_shutting_down is False
        controller.cleanup()
        assert controller._is_shutting_down is True

    def test_cleanup_clears_provider_reference(self):
        """cleanup() clears provider reference."""
        mock_iface = Mock()
        mock_iface.mainWindow.return_value = None

        mock_provider = Mock()
        mock_provider.refresh_complete = Mock()
        mock_provider.refresh_complete.connect = Mock()
        mock_provider.refresh_complete.disconnect = Mock()

        controller = DevicesController(
            iface=mock_iface,
            provider_controller=mock_provider
        )

        controller.cleanup()

        assert controller._provider_controller is None

    def test_cleanup_clears_device_data(self):
        """cleanup() clears stored device data."""
        mock_iface = Mock()
        mock_iface.mainWindow.return_value = None

        controller = DevicesController(iface=mock_iface)
        controller._last_devices = [{'device_id': 'test'}]

        controller.cleanup()

        assert controller._last_devices == []


# =============================================================================
# STATUS SNAPSHOT TESTS
# =============================================================================

class TestStatusSnapshot:
    """Test diagnostics snapshot."""

    def test_status_snapshot_returns_dict(self):
        """status_snapshot returns diagnostic info."""
        mock_iface = Mock()
        mock_iface.mainWindow.return_value = None

        controller = DevicesController(iface=mock_iface)

        snapshot = controller.status_snapshot()

        assert isinstance(snapshot, dict)
        assert 'window_open' in snapshot
        assert 'is_shutting_down' in snapshot
        assert 'device_count' in snapshot
        assert 'provider_connected' in snapshot

    def test_status_snapshot_reflects_state(self):
        """status_snapshot reflects current state."""
        mock_iface = Mock()
        mock_iface.mainWindow.return_value = None

        controller = DevicesController(iface=mock_iface)
        controller._last_devices = [{'device_id': '1'}, {'device_id': '2'}]

        snapshot = controller.status_snapshot()

        assert snapshot['window_open'] is False
        assert snapshot['is_shutting_down'] is False
        assert snapshot['device_count'] == 2
        assert snapshot['provider_connected'] is False


# =============================================================================
# SAFE MODE TESTS
# =============================================================================

class TestSafeMode:
    """Test safe mode blocking."""

    def test_set_safe_mode_block_stores_callback(self):
        """set_safe_mode_block stores the callback."""
        mock_iface = Mock()
        mock_iface.mainWindow.return_value = None

        controller = DevicesController(iface=mock_iface)

        def block_callback(feature_name):
            return feature_name == "Devices"

        controller.set_safe_mode_block(block_callback)

        assert controller._safe_mode_block is not None
        assert controller._safe_mode_block("Devices") is True
        assert controller._safe_mode_block("Other") is False
