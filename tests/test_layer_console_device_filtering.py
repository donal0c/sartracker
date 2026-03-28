# -*- coding: utf-8 -*-
"""
Tests for FR-6: Layer Console shows active devices only.

SAR-5c6: Layer Console (left panel) shows only ACTIVE tracking layers.
SAR Panel devices_list (right panel) shows ALL devices (no change).

Active device definition (from SAR-qvn):
- 'online' = always show in layers
- 'unknown' within threshold (1 hour) = show in layers
- 'unknown' beyond threshold = DO NOT create/update layer
- 'offline' = DO NOT create/update layer

This filters POSITIONS before they reach the tracking layer manager,
not devices in the SAR Panel.
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, MagicMock, patch, call

from sartracker.controllers.provider_controller import ProviderController


# =============================================================================
# UNIT TESTS: Position filtering logic (no Qt/QGIS required)
# =============================================================================

class TestGetActiveDeviceIds:
    """Unit tests for computing active device IDs from device list."""

    def test_online_devices_always_active(self):
        """Online devices should always be included in active IDs."""
        from utils.device_filtering import should_show_device

        devices = [
            {'device_id': 'dev1', 'status': 'online', 'last_update': '2020-01-01T00:00:00Z'},
            {'device_id': 'dev2', 'status': 'online', 'last_update': '2020-01-01T00:00:00Z'},
        ]

        active_ids = {d['device_id'] for d in devices if should_show_device(d)}

        assert 'dev1' in active_ids
        assert 'dev2' in active_ids

    def test_offline_devices_never_active(self):
        """Offline devices should never be included in active IDs."""
        from utils.device_filtering import should_show_device

        devices = [
            {'device_id': 'dev1', 'status': 'offline', 'last_update': datetime.now(timezone.utc).isoformat()},
        ]

        active_ids = {d['device_id'] for d in devices if should_show_device(d)}

        assert 'dev1' not in active_ids

    def test_unknown_within_threshold_is_active(self):
        """Unknown devices within threshold should be active."""
        from utils.device_filtering import should_show_device

        recent = datetime.now(timezone.utc) - timedelta(minutes=30)
        devices = [
            {'device_id': 'dev1', 'status': 'unknown', 'last_update': recent.isoformat()},
        ]

        active_ids = {d['device_id'] for d in devices if should_show_device(d, threshold_seconds=3600)}

        assert 'dev1' in active_ids

    def test_unknown_beyond_threshold_not_active(self):
        """Unknown devices beyond threshold should NOT be active."""
        from utils.device_filtering import should_show_device

        stale = datetime.now(timezone.utc) - timedelta(hours=2)
        devices = [
            {'device_id': 'dev1', 'status': 'unknown', 'last_update': stale.isoformat()},
        ]

        active_ids = {d['device_id'] for d in devices if should_show_device(d, threshold_seconds=3600)}

        assert 'dev1' not in active_ids


class TestFilterPositionsByActiveDevices:
    """Unit tests for filtering positions to only include active devices."""

    def test_filter_positions_keeps_active_devices(self):
        """Positions from active devices should be kept."""
        active_device_ids = {'dev1', 'dev2'}

        positions = [
            {'device_id': 'dev1', 'lat': 52.0, 'lon': -9.0},
            {'device_id': 'dev2', 'lat': 52.1, 'lon': -9.1},
            {'device_id': 'dev3', 'lat': 52.2, 'lon': -9.2},  # Inactive
        ]

        filtered = [p for p in positions if p.get('device_id') in active_device_ids]

        assert len(filtered) == 2
        assert all(p['device_id'] in active_device_ids for p in filtered)

    def test_filter_positions_removes_inactive_devices(self):
        """Positions from inactive devices should be removed."""
        active_device_ids = {'dev1'}

        positions = [
            {'device_id': 'dev1', 'lat': 52.0, 'lon': -9.0},
            {'device_id': 'dev2', 'lat': 52.1, 'lon': -9.1},  # Inactive
            {'device_id': 'dev3', 'lat': 52.2, 'lon': -9.2},  # Inactive
        ]

        filtered = [p for p in positions if p.get('device_id') in active_device_ids]

        assert len(filtered) == 1
        assert filtered[0]['device_id'] == 'dev1'

    def test_filter_handles_empty_active_set(self):
        """Empty active device set should result in empty positions."""
        active_device_ids = set()

        positions = [
            {'device_id': 'dev1', 'lat': 52.0, 'lon': -9.0},
            {'device_id': 'dev2', 'lat': 52.1, 'lon': -9.1},
        ]

        filtered = [p for p in positions if p.get('device_id') in active_device_ids]

        assert len(filtered) == 0

    def test_filter_handles_missing_device_id(self):
        """Positions without device_id should be filtered out."""
        active_device_ids = {'dev1'}

        positions = [
            {'device_id': 'dev1', 'lat': 52.0, 'lon': -9.0},
            {'lat': 52.1, 'lon': -9.1},  # No device_id
        ]

        filtered = [p for p in positions if p.get('device_id') in active_device_ids]

        assert len(filtered) == 1


# =============================================================================
# INTEGRATION TESTS: Provider Controller filtering behavior
# =============================================================================

class TestProviderControllerLayerFiltering:
    """
    Integration tests for Layer Console filtering in ProviderController.

    These tests verify that:
    1. Only active device positions are sent to layers_controller
    2. Inactive device positions are filtered BEFORE reaching layers
    3. ALL devices are still sent to sar_panel (no filtering there)
    """

    @pytest.fixture
    def mock_dependencies(self):
        """Create mock dependencies for ProviderController tests."""
        return {
            'layers_controller': Mock(),
            'sar_panel': Mock(),
            'iface': Mock(),
        }

    def _build_controller(self, mock_dependencies):
        iface = mock_dependencies['iface']
        iface.messageBar.return_value = Mock()
        task_manager = Mock()
        task_manager.is_shutting_down.return_value = False
        controller = ProviderController(
            iface=iface,
            task_manager=task_manager,
            parent=None,
        )
        controller._layers_controller = mock_dependencies['layers_controller']
        return controller

    def test_online_device_positions_sent_to_layers(self, mock_dependencies):
        """
        Positions from online devices should be sent to layers_controller.

        FR-6: Online devices are always active and their positions should
        create/update tracking layers.
        """
        # Arrange
        devices = [
            {'device_id': 'dev1', 'name': 'Team Alpha', 'status': 'online', 'last_update': '2026-01-03T12:00:00Z'},
        ]
        positions = [
            {'device_id': 'dev1', 'name': 'Team Alpha', 'lat': 52.0, 'lon': -9.0, 'ts': '2026-01-03T12:00:00Z'},
        ]

        controller = self._build_controller(mock_dependencies)
        task = MagicMock()
        task.isCanceled.return_value = False
        task.results = {
            'current': positions,
            'breadcrumbs': [],
            'devices': devices,
        }

        controller._on_refresh_task_complete(task)

        mock_dependencies['layers_controller'].update_current_positions.assert_called_once()
        filtered_positions = (
            mock_dependencies['layers_controller']
            .update_current_positions
            .call_args
            .args[0]
        )
        assert len(filtered_positions) == 1
        filtered_position = filtered_positions[0]
        assert filtered_position['device_id'] == 'dev1'
        assert filtered_position['name'] == 'Team Alpha'
        assert filtered_position['lat'] == 52.0
        assert filtered_position['lon'] == -9.0
        assert isinstance(filtered_position['ts'], str)

    def test_offline_device_positions_not_sent_to_layers(self, mock_dependencies):
        """
        Positions from offline devices should NOT be sent to layers_controller.

        FR-6: Offline devices are never active and their positions should
        NOT create/update tracking layers.
        """
        # Arrange
        devices = [
            {'device_id': 'dev1', 'name': 'Team Alpha', 'status': 'offline', 'last_update': '2026-01-03T12:00:00Z'},
        ]
        positions = [
            {'device_id': 'dev1', 'name': 'Team Alpha', 'lat': 52.0, 'lon': -9.0, 'ts': '2026-01-03T12:00:00Z'},
        ]

        controller = self._build_controller(mock_dependencies)
        task = MagicMock()
        task.isCanceled.return_value = False
        task.results = {
            'current': positions,
            'breadcrumbs': [],
            'devices': devices,
        }

        controller._on_refresh_task_complete(task)

        mock_dependencies['layers_controller'].update_current_positions.assert_not_called()

    def test_stale_unknown_device_positions_not_sent_to_layers(self, mock_dependencies):
        """
        Positions from stale unknown devices should NOT be sent to layers.

        FR-6: Unknown devices beyond threshold (1 hour) should not have
        their positions create/update tracking layers.
        """
        # Arrange
        stale_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        devices = [
            {'device_id': 'dev1', 'name': 'Team Alpha', 'status': 'unknown', 'last_update': stale_time},
        ]
        positions = [
            {'device_id': 'dev1', 'name': 'Team Alpha', 'lat': 52.0, 'lon': -9.0, 'ts': stale_time},
        ]

        controller = self._build_controller(mock_dependencies)
        task = MagicMock()
        task.isCanceled.return_value = False
        task.results = {
            'current': positions,
            'breadcrumbs': [],
            'devices': devices,
        }

        controller._on_refresh_task_complete(task)

        mock_dependencies['layers_controller'].update_current_positions.assert_not_called()

    def test_recent_unknown_device_positions_sent_to_layers(self, mock_dependencies):
        """
        Positions from recent unknown devices should be sent to layers.

        FR-6: Unknown devices within threshold (1 hour) should have their
        positions create/update tracking layers (grace period for patchy connections).
        """
        # Arrange
        recent_time = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        devices = [
            {'device_id': 'dev1', 'name': 'Team Alpha', 'status': 'unknown', 'last_update': recent_time},
        ]
        positions = [
            {'device_id': 'dev1', 'name': 'Team Alpha', 'lat': 52.0, 'lon': -9.0, 'ts': recent_time},
        ]

        controller = self._build_controller(mock_dependencies)
        task = MagicMock()
        task.isCanceled.return_value = False
        task.results = {
            'current': positions,
            'breadcrumbs': [],
            'devices': devices,
        }

        controller._on_refresh_task_complete(task)

        mock_dependencies['layers_controller'].update_current_positions.assert_called_once()
        filtered_positions = (
            mock_dependencies['layers_controller']
            .update_current_positions
            .call_args
            .args[0]
        )
        assert len(filtered_positions) == 1
        filtered_position = filtered_positions[0]
        assert filtered_position['device_id'] == 'dev1'
        assert filtered_position['name'] == 'Team Alpha'
        assert filtered_position['lat'] == 52.0
        assert filtered_position['lon'] == -9.0
        assert isinstance(filtered_position['ts'], str)

    def test_all_devices_sent_to_sar_panel_unfiltered(self, mock_dependencies):
        """
        ALL devices (active and inactive) should be sent to SAR Panel.

        FR-6: The SAR Panel devices_list on the right shows ALL registered
        devices with appropriate status indicators. No filtering there.
        """
        # Arrange
        devices = [
            {'device_id': 'dev1', 'name': 'Online', 'status': 'online', 'last_update': '2026-01-03T12:00:00Z'},
            {'device_id': 'dev2', 'name': 'Offline', 'status': 'offline', 'last_update': '2026-01-03T12:00:00Z'},
            {'device_id': 'dev3', 'name': 'Unknown', 'status': 'unknown', 'last_update': '2026-01-03T12:00:00Z'},
        ]

        # Current architecture no longer pushes the device list directly into
        # the SAR panel from ProviderController; DevicesController subscribes
        # to refresh_complete instead. Keep this scenario as a placeholder until
        # that path is exercised through the dedicated controller tests.
        pytest.skip("Current device-list path is owned by DevicesController, not ProviderController")

    def test_breadcrumbs_also_filtered_by_active_devices(self, mock_dependencies):
        """
        Breadcrumbs should also be filtered to only include active devices.

        FR-6: Both current positions AND breadcrumbs should only show
        active device data in the Layer Console.
        """
        # Arrange
        devices = [
            {'device_id': 'dev1', 'name': 'Active', 'status': 'online', 'last_update': '2026-01-03T12:00:00Z'},
            {'device_id': 'dev2', 'name': 'Inactive', 'status': 'offline', 'last_update': '2026-01-03T12:00:00Z'},
        ]
        breadcrumbs = [
            {'device_id': 'dev1', 'name': 'Active', 'lat': 52.0, 'lon': -9.0, 'ts': '2026-01-03T11:00:00Z'},
            {'device_id': 'dev1', 'name': 'Active', 'lat': 52.1, 'lon': -9.1, 'ts': '2026-01-03T12:00:00Z'},
            {'device_id': 'dev2', 'name': 'Inactive', 'lat': 53.0, 'lon': -8.0, 'ts': '2026-01-03T12:00:00Z'},  # Should be filtered
        ]

        # After implementation:
        # - Only dev1's breadcrumbs should be sent to layers_controller
        # - dev2's breadcrumbs should be filtered out

        pytest.skip("Implementation pending - TDD Red phase")


class TestInactiveDeviceLayerCleanup:
    """
    Tests for cleaning up layers when devices become inactive.

    When a device that previously had layers becomes inactive (offline or
    stale unknown), its tracking layers should be removed from the Layer Console.
    """

    def test_device_goes_offline_layers_removed(self):
        """
        When a previously active device goes offline, its layers should be removed.

        Scenario:
        1. Device 'dev1' is online, has position layer
        2. Device 'dev1' status changes to 'offline'
        3. On next refresh, dev1's position layer should be deleted
        """
        pytest.skip("Implementation pending - TDD Red phase")

    def test_device_goes_stale_layers_removed(self):
        """
        When an unknown device exceeds the threshold, its layers should be removed.

        Scenario:
        1. Device 'dev1' is 'unknown' but within threshold, has position layer
        2. Device 'dev1' last_update becomes older than threshold
        3. On next refresh, dev1's position layer should be deleted
        """
        pytest.skip("Implementation pending - TDD Red phase")

    def test_device_comes_back_online_layer_recreated(self):
        """
        When an inactive device becomes active again, its layer should be recreated.

        Scenario:
        1. Device 'dev1' was offline, no layer
        2. Device 'dev1' status changes to 'online'
        3. On next refresh, dev1's position should create a new layer
        """
        pytest.skip("Implementation pending - TDD Red phase")


# =============================================================================
# HELPER FUNCTION TESTS
# =============================================================================

class TestFilterPositionsHelper:
    """
    Tests for the helper function that filters positions by active devices.

    This function should be added to provider_controller.py or a utility module.
    """

    def test_filter_positions_by_active_devices_basic(self):
        """Basic filtering of positions by active device IDs."""
        from utils.device_filtering import should_show_device
        from config.settings import ACTIVE_DEVICE_STALE_THRESHOLD_SECONDS

        devices = [
            {'device_id': 'active1', 'status': 'online', 'last_update': '2026-01-03T12:00:00Z'},
            {'device_id': 'inactive1', 'status': 'offline', 'last_update': '2026-01-03T12:00:00Z'},
        ]

        positions = [
            {'device_id': 'active1', 'lat': 52.0, 'lon': -9.0},
            {'device_id': 'inactive1', 'lat': 53.0, 'lon': -8.0},
        ]

        # Compute active device IDs
        active_ids = {
            d['device_id'] for d in devices
            if should_show_device(d, ACTIVE_DEVICE_STALE_THRESHOLD_SECONDS)
        }

        # Filter positions
        filtered = [p for p in positions if p.get('device_id') in active_ids]

        assert len(filtered) == 1
        assert filtered[0]['device_id'] == 'active1'

    def test_filter_preserves_position_data(self):
        """Filtering should preserve all fields in position records."""
        active_ids = {'dev1'}

        original_position = {
            'device_id': 'dev1',
            'name': 'Team Alpha',
            'lat': 52.123456,
            'lon': -9.654321,
            'ts': '2026-01-03T12:00:00Z',
            'altitude': 150.0,
            'speed': 5.2,
            'battery': 75.0,
        }

        positions = [original_position]
        filtered = [p for p in positions if p.get('device_id') in active_ids]

        assert len(filtered) == 1
        assert filtered[0] == original_position  # All fields preserved


# =============================================================================
# EDGE CASE TESTS
# =============================================================================

class TestFilteringEdgeCases:
    """Edge case tests for the filtering logic."""

    def test_position_with_device_not_in_device_list(self):
        """
        Position for a device not in the devices list should be filtered.

        This can happen if:
        - Device was deleted from Traccar between calls
        - API race condition
        """
        from utils.device_filtering import should_show_device

        devices = [
            {'device_id': 'dev1', 'status': 'online', 'last_update': '2026-01-03T12:00:00Z'},
        ]

        positions = [
            {'device_id': 'dev1', 'lat': 52.0, 'lon': -9.0},
            {'device_id': 'unknown_device', 'lat': 53.0, 'lon': -8.0},  # Not in devices list
        ]

        # Build lookup and filter
        active_ids = {d['device_id'] for d in devices if should_show_device(d)}
        filtered = [p for p in positions if p.get('device_id') in active_ids]

        assert len(filtered) == 1
        assert filtered[0]['device_id'] == 'dev1'

    def test_empty_devices_list(self):
        """Empty devices list should result in empty active IDs."""
        from utils.device_filtering import should_show_device

        devices = []
        positions = [
            {'device_id': 'dev1', 'lat': 52.0, 'lon': -9.0},
        ]

        active_ids = {d['device_id'] for d in devices if should_show_device(d)}
        filtered = [p for p in positions if p.get('device_id') in active_ids]

        assert len(filtered) == 0

    def test_empty_positions_list(self):
        """Empty positions list should return empty result."""
        active_ids = {'dev1', 'dev2'}
        positions = []

        filtered = [p for p in positions if p.get('device_id') in active_ids]

        assert len(filtered) == 0

    def test_all_devices_active(self):
        """When all devices are active, all positions should pass."""
        from utils.device_filtering import should_show_device

        devices = [
            {'device_id': 'dev1', 'status': 'online', 'last_update': '2026-01-03T12:00:00Z'},
            {'device_id': 'dev2', 'status': 'online', 'last_update': '2026-01-03T12:00:00Z'},
        ]

        positions = [
            {'device_id': 'dev1', 'lat': 52.0, 'lon': -9.0},
            {'device_id': 'dev2', 'lat': 53.0, 'lon': -8.0},
        ]

        active_ids = {d['device_id'] for d in devices if should_show_device(d)}
        filtered = [p for p in positions if p.get('device_id') in active_ids]

        assert len(filtered) == 2

    def test_all_devices_inactive(self):
        """When all devices are inactive, no positions should pass."""
        from utils.device_filtering import should_show_device

        devices = [
            {'device_id': 'dev1', 'status': 'offline', 'last_update': '2026-01-03T12:00:00Z'},
            {'device_id': 'dev2', 'status': 'offline', 'last_update': '2026-01-03T12:00:00Z'},
        ]

        positions = [
            {'device_id': 'dev1', 'lat': 52.0, 'lon': -9.0},
            {'device_id': 'dev2', 'lat': 53.0, 'lon': -8.0},
        ]

        active_ids = {d['device_id'] for d in devices if should_show_device(d)}
        filtered = [p for p in positions if p.get('device_id') in active_ids]

        assert len(filtered) == 0
