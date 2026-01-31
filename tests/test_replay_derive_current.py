# -*- coding: utf-8 -*-
"""
Tests for replay mode: deriving current positions from breadcrumbs.

TDD: Tests written BEFORE implementation (SAR-zh9y Phase 4)

These tests verify that in replay mode, "current" positions are derived
from breadcrumbs (latest position per device) rather than fetched from
the live API.
"""
import pytest
from datetime import datetime, timezone


class TestDeriveCurrentFromBreadcrumbs:
    """Unit tests for derive_current_from_breadcrumbs helper."""

    def test_empty_breadcrumbs_returns_empty(self):
        """Empty breadcrumbs should return empty current."""
        from sartracker.providers.tasks import derive_current_from_breadcrumbs

        result = derive_current_from_breadcrumbs([])
        assert result == []

    def test_single_device_single_position(self):
        """Single device with one position returns that position."""
        from sartracker.providers.tasks import derive_current_from_breadcrumbs

        breadcrumbs = [
            {'device_id': 'dev1', 'ts': '2024-01-01T10:00:00Z', 'lat': 52.0, 'lon': -9.5}
        ]
        result = derive_current_from_breadcrumbs(breadcrumbs)

        assert len(result) == 1
        assert result[0]['device_id'] == 'dev1'
        assert result[0]['ts'] == '2024-01-01T10:00:00Z'

    def test_single_device_multiple_positions_returns_latest(self):
        """Multiple positions for one device returns the latest by timestamp."""
        from sartracker.providers.tasks import derive_current_from_breadcrumbs

        breadcrumbs = [
            {'device_id': 'dev1', 'ts': '2024-01-01T10:00:00Z', 'lat': 52.0, 'lon': -9.5},
            {'device_id': 'dev1', 'ts': '2024-01-01T12:00:00Z', 'lat': 52.1, 'lon': -9.4},
            {'device_id': 'dev1', 'ts': '2024-01-01T11:00:00Z', 'lat': 52.05, 'lon': -9.45},
        ]
        result = derive_current_from_breadcrumbs(breadcrumbs)

        assert len(result) == 1
        assert result[0]['device_id'] == 'dev1'
        assert result[0]['ts'] == '2024-01-01T12:00:00Z'  # Latest
        assert result[0]['lat'] == 52.1

    def test_multiple_devices_returns_latest_per_device(self):
        """Multiple devices each get their own latest position."""
        from sartracker.providers.tasks import derive_current_from_breadcrumbs

        breadcrumbs = [
            {'device_id': 'dev1', 'ts': '2024-01-01T10:00:00Z', 'lat': 52.0, 'lon': -9.5},
            {'device_id': 'dev2', 'ts': '2024-01-01T09:00:00Z', 'lat': 53.0, 'lon': -8.5},
            {'device_id': 'dev1', 'ts': '2024-01-01T11:00:00Z', 'lat': 52.1, 'lon': -9.4},
            {'device_id': 'dev2', 'ts': '2024-01-01T10:30:00Z', 'lat': 53.1, 'lon': -8.4},
        ]
        result = derive_current_from_breadcrumbs(breadcrumbs)

        assert len(result) == 2

        # Sort by device_id for deterministic comparison
        result_by_device = {r['device_id']: r for r in result}

        assert result_by_device['dev1']['ts'] == '2024-01-01T11:00:00Z'
        assert result_by_device['dev2']['ts'] == '2024-01-01T10:30:00Z'

    def test_missing_device_id_skipped(self):
        """Breadcrumbs without device_id are skipped."""
        from sartracker.providers.tasks import derive_current_from_breadcrumbs

        breadcrumbs = [
            {'device_id': 'dev1', 'ts': '2024-01-01T10:00:00Z', 'lat': 52.0, 'lon': -9.5},
            {'ts': '2024-01-01T12:00:00Z', 'lat': 53.0, 'lon': -8.5},  # No device_id
            {'device_id': None, 'ts': '2024-01-01T11:00:00Z', 'lat': 54.0, 'lon': -7.5},
        ]
        result = derive_current_from_breadcrumbs(breadcrumbs)

        assert len(result) == 1
        assert result[0]['device_id'] == 'dev1'

    def test_missing_timestamp_skipped(self):
        """Breadcrumbs without ts are skipped."""
        from sartracker.providers.tasks import derive_current_from_breadcrumbs

        breadcrumbs = [
            {'device_id': 'dev1', 'ts': '2024-01-01T10:00:00Z', 'lat': 52.0, 'lon': -9.5},
            {'device_id': 'dev2', 'lat': 53.0, 'lon': -8.5},  # No ts
        ]
        result = derive_current_from_breadcrumbs(breadcrumbs)

        assert len(result) == 1
        assert result[0]['device_id'] == 'dev1'

    def test_handles_timezone_aware_timestamps(self):
        """Timestamps with different timezone offsets are compared correctly."""
        from sartracker.providers.tasks import derive_current_from_breadcrumbs

        breadcrumbs = [
            {'device_id': 'dev1', 'ts': '2024-01-01T10:00:00Z', 'lat': 52.0, 'lon': -9.5},
            # Same absolute time but different representation
            {'device_id': 'dev1', 'ts': '2024-01-01T11:00:00+01:00', 'lat': 52.1, 'lon': -9.4},
            {'device_id': 'dev1', 'ts': '2024-01-01T12:00:00Z', 'lat': 52.2, 'lon': -9.3},
        ]
        result = derive_current_from_breadcrumbs(breadcrumbs)

        assert len(result) == 1
        # 12:00 UTC is latest
        assert result[0]['ts'] == '2024-01-01T12:00:00Z'


class TestTraccarRefreshTaskReplayMode:
    """Integration tests for replay mode in TraccarRefreshTask."""

    def test_task_has_replay_enabled_attribute(self):
        """TraccarRefreshTask should accept replay_enabled parameter."""
        from sartracker.providers.tasks import TraccarRefreshTask
        from unittest.mock import MagicMock

        mock_provider = MagicMock()
        mock_provider._create_session.return_value = MagicMock()

        task = TraccarRefreshTask(
            provider=mock_provider,
            description="Test",
            replay_enabled=True
        )

        assert task.replay_enabled is True

    def test_task_replay_disabled_by_default(self):
        """replay_enabled should default to False."""
        from sartracker.providers.tasks import TraccarRefreshTask
        from unittest.mock import MagicMock

        mock_provider = MagicMock()

        task = TraccarRefreshTask(
            provider=mock_provider,
            description="Test"
        )

        assert task.replay_enabled is False
