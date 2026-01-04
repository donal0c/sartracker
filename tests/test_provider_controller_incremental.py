# -*- coding: utf-8 -*-
"""
Tests for Phase 3: Integration and Wiring of Incremental Breadcrumb Collection.

Tests the integration of BreadcrumbAccumulator into ProviderController's
refresh flow, including lifecycle management and device timestamp passing.

TDD: Tests written BEFORE implementation per CLAUDE.md guidelines.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch

from sartracker.controllers.provider_controller import ProviderController
from sartracker.utils.breadcrumb_accumulator import BreadcrumbAccumulator


def _build_controller(provider_name: str = 'traccar_http'):
    """Helper to create a ProviderController with mocked dependencies."""
    iface = MagicMock()
    iface.messageBar.return_value = MagicMock()
    task_manager = MagicMock()
    task_manager.is_shutting_down.return_value = False

    controller = ProviderController(
        iface=iface,
        task_manager=task_manager,
        parent=None
    )

    provider = MagicMock()
    provider.create_refresh_task.return_value = MagicMock()

    controller.provider = provider
    controller.provider_name = provider_name
    return controller, provider, task_manager


class TestBreadcrumbAccumulatorIntegration:
    """Tests for BreadcrumbAccumulator integration in ProviderController."""

    def test_accumulator_state_variables_exist(self):
        """Verify that accumulator state variables are defined on controller."""
        controller, _, _ = _build_controller()

        # Phase 3 requires these state variables
        assert hasattr(controller, '_breadcrumb_accumulator')
        assert hasattr(controller, '_incremental_breadcrumbs_enabled')

        # Initial state should be None (not initialized until first refresh)
        assert controller._breadcrumb_accumulator is None
        # Feature flag should default to True
        assert controller._incremental_breadcrumbs_enabled is True

    def test_init_breadcrumb_accumulator_creates_new_instance(self):
        """_init_breadcrumb_accumulator should create a fresh accumulator."""
        controller, _, _ = _build_controller()

        # Precondition: no accumulator
        assert controller._breadcrumb_accumulator is None

        # Initialize
        controller._init_breadcrumb_accumulator()

        # Should have a new accumulator
        assert controller._breadcrumb_accumulator is not None
        assert isinstance(controller._breadcrumb_accumulator, BreadcrumbAccumulator)
        assert controller._breadcrumb_accumulator.stats()['total_positions'] == 0

    def test_accumulator_initialized_on_first_refresh(self):
        """Accumulator should be created on first successful refresh with data."""
        controller, mock_provider, _ = _build_controller()

        # Mock layers controller
        controller._layers_controller = MagicMock()

        # Mock a task with breadcrumb results
        # Note: sanitize_provider_results requires 'name' field for positions
        mock_task = MagicMock()
        mock_task.isCanceled.return_value = False
        mock_task.results = {
            'current': [{'device_id': 'dev1', 'name': 'Device 1', 'lat': 52.0, 'lon': -9.5, 'ts': '2024-01-01T10:00:00Z'}],
            'breadcrumbs': [
                {'device_id': 'dev1', 'name': 'Device 1', 'lat': 52.0, 'lon': -9.5, 'ts': '2024-01-01T09:00:00Z'},
                {'device_id': 'dev1', 'name': 'Device 1', 'lat': 52.01, 'lon': -9.51, 'ts': '2024-01-01T09:30:00Z'},
            ],
            'devices': [{'device_id': 'dev1', 'name': 'Device 1', 'status': 'online'}]
        }

        # Before refresh complete, accumulator should be None
        assert controller._breadcrumb_accumulator is None

        # Trigger refresh complete callback
        controller._on_refresh_task_complete(mock_task)

        # After refresh with breadcrumbs, accumulator should be initialized
        assert controller._breadcrumb_accumulator is not None

    def test_accumulator_reset_on_new_mission(self):
        """Accumulator should be reset when a new mission starts."""
        controller, mock_provider, _ = _build_controller()

        # Setup: controller with existing accumulator containing data
        controller._breadcrumb_accumulator = BreadcrumbAccumulator(max_positions=1000)
        controller._breadcrumb_accumulator.add([
            {'device_id': 'dev1', 'lat': 52.0, 'lon': -9.5, 'ts': '2024-01-01T09:00:00Z'}
        ])

        # Verify data exists
        assert controller._breadcrumb_accumulator.stats()['total_positions'] == 1

        # Simulate mission state change: idle -> active (new mission)
        controller._on_mission_state_changed('idle', 'active')

        # Accumulator should be reset (new instance or cleared)
        assert controller._breadcrumb_accumulator is not None
        assert controller._breadcrumb_accumulator.stats()['total_positions'] == 0

    def test_accumulator_preserved_on_mission_resume(self):
        """Accumulator should be preserved when resuming from pause."""
        controller, mock_provider, _ = _build_controller()

        # Setup: controller with existing accumulator containing data
        controller._breadcrumb_accumulator = BreadcrumbAccumulator(max_positions=1000)
        controller._breadcrumb_accumulator.add([
            {'device_id': 'dev1', 'lat': 52.0, 'lon': -9.5, 'ts': '2024-01-01T09:00:00Z'}
        ])

        original_count = controller._breadcrumb_accumulator.stats()['total_positions']

        # Simulate mission state change: paused -> active (resume)
        controller._on_mission_state_changed('paused', 'active')

        # Accumulator should be preserved with same data
        assert controller._breadcrumb_accumulator is not None
        assert controller._breadcrumb_accumulator.stats()['total_positions'] == original_count

    def test_accumulator_reset_on_provider_change_commit(self):
        """Accumulator should be reset when provider change is committed."""
        controller, mock_provider, _ = _build_controller()

        # Setup: controller with existing accumulator
        controller._breadcrumb_accumulator = BreadcrumbAccumulator(max_positions=1000)
        controller._breadcrumb_accumulator.add([
            {'device_id': 'dev1', 'lat': 52.0, 'lon': -9.5, 'ts': '2024-01-01T09:00:00Z'}
        ])

        # Verify data exists
        assert controller._breadcrumb_accumulator.stats()['total_positions'] == 1

        # Simulate provider commit (called by _on_connection_test_complete)
        # Setup pending state as if test succeeded
        controller._pending_provider = MagicMock()
        controller._pending_provider_name = 'csv'
        controller._pending_provider_config = {'csv_path': '/tmp/test.csv'}
        controller._pending_test_only = False

        # Create a successful mock connection test task
        mock_task = MagicMock()
        mock_task.success = True

        # Trigger connection test complete
        controller._on_connection_test_complete(mock_task)

        # Accumulator should be reset (new instance)
        assert controller._breadcrumb_accumulator is not None
        assert controller._breadcrumb_accumulator.stats()['total_positions'] == 0

    def test_incremental_timestamps_passed_to_task(self):
        """Device timestamps should be passed to refresh task for incremental fetch."""
        controller, mock_provider, _ = _build_controller()

        # Setup: controller with accumulator that has tracked positions
        controller._breadcrumb_accumulator = BreadcrumbAccumulator(max_positions=1000)
        controller._breadcrumb_accumulator.add([
            {'device_id': 'dev1', 'lat': 52.0, 'lon': -9.5, 'ts': '2024-01-01T09:00:00Z'},
            {'device_id': 'dev2', 'lat': 53.0, 'lon': -8.5, 'ts': '2024-01-01T08:30:00Z'},
        ])

        # Get timestamps that should be passed
        expected_timestamps = controller._breadcrumb_accumulator.get_latest_timestamps()
        assert 'dev1' in expected_timestamps
        assert 'dev2' in expected_timestamps

        # Start refresh
        controller.start_refresh()

        # Verify create_refresh_task was called with device_timestamps
        mock_provider.create_refresh_task.assert_called_once()
        call_kwargs = mock_provider.create_refresh_task.call_args[1]
        assert 'device_timestamps' in call_kwargs
        assert call_kwargs['device_timestamps'] == expected_timestamps

    def test_filtered_breadcrumbs_accumulated(self):
        """Only breadcrumbs from active devices should be accumulated."""
        controller, mock_provider, _ = _build_controller()

        # Setup
        controller._breadcrumb_accumulator = BreadcrumbAccumulator(max_positions=1000)

        # Mock layers controller
        controller._layers_controller = MagicMock()

        # Mock task with breadcrumbs from both active and inactive devices
        # Note: sanitize_provider_results requires 'name' field for positions
        mock_task = MagicMock()
        mock_task.isCanceled.return_value = False
        mock_task.results = {
            'current': [
                {'device_id': 'active_dev', 'name': 'Active Device', 'lat': 52.0, 'lon': -9.5, 'ts': '2024-01-01T10:00:00Z'}
            ],
            'breadcrumbs': [
                {'device_id': 'active_dev', 'name': 'Active Device', 'lat': 52.0, 'lon': -9.5, 'ts': '2024-01-01T09:00:00Z'},
                {'device_id': 'inactive_dev', 'name': 'Inactive Device', 'lat': 53.0, 'lon': -8.5, 'ts': '2024-01-01T09:00:00Z'},
            ],
            'devices': [
                {'device_id': 'active_dev', 'name': 'Active Device', 'status': 'online'},
                {'device_id': 'inactive_dev', 'name': 'Inactive Device', 'status': 'offline'},
            ]
        }

        # Trigger refresh complete
        controller._on_refresh_task_complete(mock_task)

        # Only active device breadcrumbs should be in accumulator
        stats = controller._breadcrumb_accumulator.stats()
        assert 'active_dev' in stats.get('positions_per_device', {})
        assert 'inactive_dev' not in stats.get('positions_per_device', {})

    def test_accumulated_breadcrumbs_sent_to_layers(self):
        """Accumulated breadcrumbs (not just new ones) should be sent to layers."""
        controller, mock_provider, _ = _build_controller()

        # Setup with pre-existing accumulated breadcrumbs
        controller._breadcrumb_accumulator = BreadcrumbAccumulator(max_positions=1000)
        # Pre-populate with existing breadcrumbs
        controller._breadcrumb_accumulator.add([
            {'device_id': 'dev1', 'name': 'Device 1', 'lat': 52.0, 'lon': -9.5, 'ts': '2024-01-01T08:00:00Z'},
            {'device_id': 'dev1', 'name': 'Device 1', 'lat': 52.01, 'lon': -9.51, 'ts': '2024-01-01T08:30:00Z'},
        ])

        # Mock layers controller
        mock_layers = MagicMock()
        controller._layers_controller = mock_layers

        # Mock task with NEW breadcrumbs
        # Note: sanitize_provider_results requires 'name' field for positions
        mock_task = MagicMock()
        mock_task.isCanceled.return_value = False
        mock_task.results = {
            'current': [{'device_id': 'dev1', 'name': 'Device 1', 'lat': 52.02, 'lon': -9.52, 'ts': '2024-01-01T10:00:00Z'}],
            'breadcrumbs': [
                {'device_id': 'dev1', 'name': 'Device 1', 'lat': 52.015, 'lon': -9.515, 'ts': '2024-01-01T09:00:00Z'},
            ],
            'devices': [{'device_id': 'dev1', 'name': 'Device 1', 'status': 'online'}]
        }

        # Trigger refresh complete
        controller._on_refresh_task_complete(mock_task)

        # Layers controller should receive ALL accumulated breadcrumbs (3 total)
        mock_layers.update_breadcrumbs.assert_called_once()
        call_args = mock_layers.update_breadcrumbs.call_args[0]
        all_breadcrumbs = call_args[0]

        # Should have accumulated breadcrumbs (pre-existing + new)
        assert len(all_breadcrumbs) == 3

    def test_diagnostics_show_accumulator_stats(self):
        """Diagnostics endpoint should return accumulator statistics."""
        controller, _, _ = _build_controller()

        # Setup with accumulator
        controller._breadcrumb_accumulator = BreadcrumbAccumulator(max_positions=100000)
        controller._breadcrumb_accumulator.add([
            {'device_id': 'dev1', 'lat': 52.0, 'lon': -9.5, 'ts': '2024-01-01T09:00:00Z'},
            {'device_id': 'dev2', 'lat': 53.0, 'lon': -8.5, 'ts': '2024-01-01T09:00:00Z'},
        ])

        # Get stats via diagnostics method
        stats = controller.get_breadcrumb_stats()

        assert stats['enabled'] is True
        assert stats['total_positions'] == 2
        assert stats['device_count'] == 2
        assert 'memory_usage_pct' in stats
        assert 'per_device' in stats

    def test_diagnostics_show_disabled_when_no_accumulator(self):
        """Diagnostics should show disabled state when accumulator not initialized."""
        controller, _, _ = _build_controller()

        # No accumulator
        controller._breadcrumb_accumulator = None

        stats = controller.get_breadcrumb_stats()

        assert stats['enabled'] is False

    def test_incremental_fetch_disabled_when_flag_false(self):
        """When incremental breadcrumbs disabled, timestamps should not be passed."""
        controller, mock_provider, _ = _build_controller()

        # Setup with accumulator but feature disabled
        controller._breadcrumb_accumulator = BreadcrumbAccumulator(max_positions=1000)
        controller._breadcrumb_accumulator.add([
            {'device_id': 'dev1', 'lat': 52.0, 'lon': -9.5, 'ts': '2024-01-01T09:00:00Z'},
        ])
        controller._incremental_breadcrumbs_enabled = False  # Disable feature

        # Start refresh
        controller.start_refresh()

        # Verify create_refresh_task was called WITHOUT device_timestamps
        mock_provider.create_refresh_task.assert_called_once()
        call_kwargs = mock_provider.create_refresh_task.call_args[1]
        assert call_kwargs.get('device_timestamps') is None


class TestIncrementalFlowEndToEnd:
    """Tests for complete incremental fetch flow - verifies CRITICAL bug fix."""

    def test_full_incremental_cycle(self):
        """
        CRITICAL: Complete cycle - verify device_timestamps flows through entire stack.

        This test verifies the fix for the critical bug where device_timestamps
        was not being passed from ProviderController to TraccarRefreshTask.
        """
        controller, mock_provider, _ = _build_controller()
        controller._layers_controller = MagicMock()

        # First refresh - should have no timestamps (accumulator not yet populated)
        controller.start_refresh()
        first_call_kwargs = mock_provider.create_refresh_task.call_args[1]
        assert first_call_kwargs.get('device_timestamps') is None

        # Reset mock for next call
        mock_provider.create_refresh_task.reset_mock()
        controller._refresh_in_progress = False

        # Simulate first refresh completion with breadcrumbs
        mock_task = MagicMock()
        mock_task.isCanceled.return_value = False
        mock_task.results = {
            'current': [{'device_id': 'dev1', 'name': 'Device 1', 'lat': 52.0, 'lon': -9.5, 'ts': '2024-01-01T10:30:00Z'}],
            'breadcrumbs': [
                {'device_id': 'dev1', 'name': 'Device 1', 'lat': 52.0, 'lon': -9.5, 'ts': '2024-01-01T10:00:00Z'},
                {'device_id': 'dev1', 'name': 'Device 1', 'lat': 52.1, 'lon': -9.6, 'ts': '2024-01-01T10:15:00Z'},
            ],
            'devices': [{'device_id': 'dev1', 'name': 'Device 1', 'status': 'online'}]
        }
        controller._on_refresh_task_complete(mock_task)
        controller._refresh_in_progress = False

        # Second refresh - should now have timestamps from accumulator
        controller.start_refresh()
        second_call_kwargs = mock_provider.create_refresh_task.call_args[1]

        # CRITICAL: This assertion verifies the bug fix - device_timestamps MUST be passed
        assert second_call_kwargs.get('device_timestamps') is not None, \
            "CRITICAL BUG: device_timestamps not passed to create_refresh_task!"
        assert 'dev1' in second_call_kwargs['device_timestamps']
        # Should be the latest timestamp from accumulator
        assert second_call_kwargs['device_timestamps']['dev1'] == '2024-01-01T10:15:00Z'

    def test_cleanup_clears_accumulator(self):
        """Verify accumulator is cleared during cleanup to prevent memory leaks."""
        controller, mock_provider, _ = _build_controller()

        # Initialize accumulator with data
        controller._init_breadcrumb_accumulator()
        controller._breadcrumb_accumulator.add([
            {'device_id': 'dev1', 'lat': 52.0, 'lon': -9.5, 'ts': '2024-01-01T09:00:00Z'}
        ])
        assert controller._breadcrumb_accumulator.stats()['total_positions'] == 1

        # Cleanup
        controller.cleanup()

        # Accumulator should be None
        assert controller._breadcrumb_accumulator is None

    def test_get_breadcrumb_stats_handles_race_condition(self):
        """Verify get_breadcrumb_stats doesn't crash if accumulator is cleared mid-call."""
        controller, mock_provider, _ = _build_controller()

        # No accumulator
        controller._breadcrumb_accumulator = None

        # Should return disabled state, not crash
        stats = controller.get_breadcrumb_stats()
        assert stats['enabled'] is False

    def test_accumulator_error_falls_back_to_filtered_breadcrumbs(self):
        """
        CRITICAL FIX: If accumulator.add() throws, refresh should continue with filtered data.

        This test verifies that even if the accumulator fails, the layers still receive
        breadcrumb data - essential for life-safety operations.
        """
        controller, mock_provider, _ = _build_controller()

        # Create a mock accumulator that throws on add()
        mock_accumulator = MagicMock()
        mock_accumulator.add.side_effect = Exception("Simulated accumulator failure")
        controller._breadcrumb_accumulator = mock_accumulator

        # Mock layers controller
        mock_layers = MagicMock()
        controller._layers_controller = mock_layers

        # Mock task with breadcrumbs
        mock_task = MagicMock()
        mock_task.isCanceled.return_value = False
        mock_task.results = {
            'current': [{'device_id': 'dev1', 'name': 'Device 1', 'lat': 52.0, 'lon': -9.5, 'ts': '2024-01-01T10:00:00Z'}],
            'breadcrumbs': [
                {'device_id': 'dev1', 'name': 'Device 1', 'lat': 52.0, 'lon': -9.5, 'ts': '2024-01-01T09:00:00Z'},
            ],
            'devices': [{'device_id': 'dev1', 'name': 'Device 1', 'status': 'online'}]
        }

        # Should NOT raise - should gracefully fall back
        controller._on_refresh_task_complete(mock_task)

        # Layers should still receive breadcrumb data (the filtered breadcrumbs)
        mock_layers.update_breadcrumbs.assert_called_once()
        call_args = mock_layers.update_breadcrumbs.call_args[0]
        breadcrumbs_sent = call_args[0]

        # Should have received the filtered breadcrumbs (1 position)
        assert len(breadcrumbs_sent) == 1
        assert breadcrumbs_sent[0]['device_id'] == 'dev1'


class TestTraccarRefreshTaskDeviceTimestamps:
    """Tests for TraccarRefreshTask device_timestamps parameter."""

    def test_task_accepts_device_timestamps_parameter(self):
        """TraccarRefreshTask should accept device_timestamps in __init__."""
        from sartracker.providers.tasks import TraccarRefreshTask

        mock_provider = MagicMock()
        timestamps = {'dev1': '2024-01-01T09:00:00Z', 'dev2': '2024-01-01T08:30:00Z'}

        task = TraccarRefreshTask(
            provider=mock_provider,
            description="Test",
            since_iso='2024-01-01T00:00:00Z',
            device_timestamps=timestamps
        )

        assert hasattr(task, '_device_timestamps')
        assert task._device_timestamps == timestamps

    def test_task_passes_timestamps_to_provider(self):
        """TraccarRefreshTask should pass device_timestamps to get_breadcrumbs."""
        from sartracker.providers.tasks import TraccarRefreshTask

        mock_provider = MagicMock()
        mock_session = MagicMock()
        mock_provider._create_session.return_value = mock_session
        mock_provider.get_devices.return_value = []
        mock_provider.get_current.return_value = []
        mock_provider.get_breadcrumbs.return_value = []
        mock_provider.enable_last_good_cache = False

        timestamps = {'dev1': '2024-01-01T09:00:00Z'}

        task = TraccarRefreshTask(
            provider=mock_provider,
            description="Test",
            device_timestamps=timestamps
        )

        # Run the task
        task.run()

        # Verify get_breadcrumbs was called with device_timestamps
        mock_provider.get_breadcrumbs.assert_called_once()
        call_kwargs = mock_provider.get_breadcrumbs.call_args[1]
        assert call_kwargs.get('device_timestamps') == timestamps

    def test_task_works_without_device_timestamps(self):
        """TraccarRefreshTask should work when device_timestamps is None (legacy mode)."""
        from sartracker.providers.tasks import TraccarRefreshTask

        mock_provider = MagicMock()
        mock_session = MagicMock()
        mock_provider._create_session.return_value = mock_session
        mock_provider.get_devices.return_value = []
        mock_provider.get_current.return_value = []
        mock_provider.get_breadcrumbs.return_value = []
        mock_provider.enable_last_good_cache = False

        # No device_timestamps
        task = TraccarRefreshTask(
            provider=mock_provider,
            description="Test"
        )

        # Run the task
        result = task.run()

        # Should complete successfully
        assert result is True

        # Verify get_breadcrumbs was called (with None for device_timestamps)
        mock_provider.get_breadcrumbs.assert_called_once()
