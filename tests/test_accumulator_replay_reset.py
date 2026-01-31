# -*- coding: utf-8 -*-
"""
Tests for accumulator reset on replay config changes.

TDD: Tests written BEFORE implementation (SAR-i1by Phase 5)

These tests verify that the breadcrumb accumulator is properly reset
when replay configuration changes, preventing stale data from leaking
across replay windows or into live mode.
"""
import pytest
from unittest.mock import MagicMock, patch


class TestAccumulatorReplayReset:
    """Tests for accumulator reset on replay config changes."""

    def test_accumulator_reset_on_replay_enable(self):
        """Accumulator should reset when replay is enabled."""
        from sartracker.controllers.provider_controller import ProviderController

        controller = ProviderController.__new__(ProviderController)
        controller._breadcrumb_accumulator = MagicMock()
        controller._last_replay_config = (False, None, None)

        # Enable replay
        controller._check_replay_config_reset(True, '2024-01-01T10:00:00Z', 2)

        controller._breadcrumb_accumulator.clear.assert_called_once()

    def test_accumulator_reset_on_replay_disable(self):
        """Accumulator should reset when replay is disabled."""
        from sartracker.controllers.provider_controller import ProviderController

        controller = ProviderController.__new__(ProviderController)
        controller._breadcrumb_accumulator = MagicMock()
        controller._last_replay_config = (True, '2024-01-01T10:00:00Z', 2)

        # Disable replay
        controller._check_replay_config_reset(False, None, None)

        controller._breadcrumb_accumulator.clear.assert_called_once()

    def test_accumulator_reset_on_start_time_change(self):
        """Accumulator should reset when replay start time changes."""
        from sartracker.controllers.provider_controller import ProviderController

        controller = ProviderController.__new__(ProviderController)
        controller._breadcrumb_accumulator = MagicMock()
        controller._last_replay_config = (True, '2024-01-01T10:00:00Z', 2)

        # Change start time
        controller._check_replay_config_reset(True, '2024-01-01T14:00:00Z', 2)

        controller._breadcrumb_accumulator.clear.assert_called_once()

    def test_accumulator_reset_on_hours_change(self):
        """Accumulator should reset when replay hours change."""
        from sartracker.controllers.provider_controller import ProviderController

        controller = ProviderController.__new__(ProviderController)
        controller._breadcrumb_accumulator = MagicMock()
        controller._last_replay_config = (True, '2024-01-01T10:00:00Z', 2)

        # Change hours
        controller._check_replay_config_reset(True, '2024-01-01T10:00:00Z', 4)

        controller._breadcrumb_accumulator.clear.assert_called_once()

    def test_no_reset_on_unchanged_config(self):
        """Accumulator should NOT reset when config is unchanged."""
        from sartracker.controllers.provider_controller import ProviderController

        controller = ProviderController.__new__(ProviderController)
        controller._breadcrumb_accumulator = MagicMock()
        controller._last_replay_config = (True, '2024-01-01T10:00:00Z', 2)

        # Same config
        controller._check_replay_config_reset(True, '2024-01-01T10:00:00Z', 2)

        controller._breadcrumb_accumulator.clear.assert_not_called()

    def test_no_reset_when_accumulator_is_none(self):
        """Should handle None accumulator gracefully."""
        from sartracker.controllers.provider_controller import ProviderController

        controller = ProviderController.__new__(ProviderController)
        controller._breadcrumb_accumulator = None
        controller._last_replay_config = (False, None, None)

        # Should not raise
        controller._check_replay_config_reset(True, '2024-01-01T10:00:00Z', 2)

    def test_config_updated_after_reset(self):
        """Last replay config should be updated after check."""
        from sartracker.controllers.provider_controller import ProviderController

        controller = ProviderController.__new__(ProviderController)
        controller._breadcrumb_accumulator = MagicMock()
        controller._last_replay_config = (False, None, None)

        controller._check_replay_config_reset(True, '2024-01-01T10:00:00Z', 2)

        assert controller._last_replay_config == (True, '2024-01-01T10:00:00Z', 2)


class TestIncrementalFetchInReplayMode:
    """Tests for disabling incremental fetch in replay mode."""

    def test_incremental_fetch_disabled_in_replay_mode(self):
        """Incremental fetch should be disabled when replay is enabled."""
        from sartracker.controllers.provider_controller import ProviderController

        controller = ProviderController.__new__(ProviderController)
        controller._incremental_breadcrumbs_enabled = True
        controller._breadcrumb_accumulator = MagicMock()
        controller._breadcrumb_accumulator.get_latest_timestamps.return_value = {'dev1': 'ts1'}

        # In replay mode, should NOT get timestamps
        timestamps = controller._get_incremental_timestamps(replay_enabled=True)

        assert timestamps is None
        controller._breadcrumb_accumulator.get_latest_timestamps.assert_not_called()

    def test_incremental_fetch_enabled_in_normal_mode(self):
        """Incremental fetch should work normally when replay is disabled."""
        from sartracker.controllers.provider_controller import ProviderController

        controller = ProviderController.__new__(ProviderController)
        controller._incremental_breadcrumbs_enabled = True
        controller._breadcrumb_accumulator = MagicMock()
        controller._breadcrumb_accumulator.get_latest_timestamps.return_value = {'dev1': 'ts1'}

        # In normal mode, should get timestamps
        timestamps = controller._get_incremental_timestamps(replay_enabled=False)

        assert timestamps == {'dev1': 'ts1'}
        controller._breadcrumb_accumulator.get_latest_timestamps.assert_called_once()
