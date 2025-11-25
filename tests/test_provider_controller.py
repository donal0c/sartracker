# -*- coding: utf-8 -*-
"""
Tests for Provider Controller (Phase 2 Refactor).

Tests the two-phase commit pattern for provider changes, polling management,
and status tracking.

Note: These tests require QGIS runtime. They are skipped when QGIS is not available.
"""
import pytest
from unittest.mock import Mock, MagicMock, patch, PropertyMock

# Skip all tests in this module if QGIS is not available
pytest.importorskip("qgis", reason="QGIS not available; ProviderController tests require QGIS runtime")


class TestProviderControllerTwoPhaseCommit:
    """Tests for two-phase commit provider changes."""

    def test_set_provider_creates_shadow_state(self):
        """set_provider should create shadow state before testing."""
        with patch('sartracker.controllers.provider_controller.provider_registry') as mock_registry:
            mock_provider = Mock()
            mock_registry.get_provider.return_value = mock_provider

            from sartracker.controllers.provider_controller import ProviderController

            controller = ProviderController(
                iface=Mock(),
                task_manager=Mock(),
                parent=None
            )

            controller.set_provider('test_provider', {'key': 'value'})

            # Shadow state should be set
            assert controller._pending_provider is mock_provider
            assert controller._pending_provider_name == 'test_provider'
            assert controller._pending_provider_config == {'key': 'value'}

    def test_set_provider_prevents_concurrent_changes(self):
        """set_provider should block when a change is in progress."""
        with patch('sartracker.controllers.provider_controller.provider_registry') as mock_registry:
            mock_provider = Mock()
            mock_registry.get_provider.return_value = mock_provider

            from sartracker.controllers.provider_controller import ProviderController

            controller = ProviderController(
                iface=Mock(),
                task_manager=Mock(),
                parent=None
            )

            # Start first change
            controller._pending_provider = Mock()

            # Second change should be blocked
            controller.set_provider('another_provider', {})

            # Provider should not have been created for second call
            mock_registry.get_provider.assert_not_called()

    def test_set_provider_validates_inputs(self):
        """set_provider should validate provider_name and config."""
        from sartracker.controllers.provider_controller import ProviderController

        controller = ProviderController(
            iface=Mock(),
            task_manager=Mock(),
            parent=None
        )

        with pytest.raises(ValueError, match="non-empty string"):
            controller.set_provider('', {})

        with pytest.raises(ValueError, match="non-empty string"):
            controller.set_provider(None, {})

        with pytest.raises(ValueError, match="dictionary"):
            controller.set_provider('test', None)

    def test_connection_test_success_commits_provider(self):
        """Successful connection test should commit shadow state."""
        from sartracker.controllers.provider_controller import ProviderController

        mock_task = Mock()
        mock_task.success = True

        controller = ProviderController(
            iface=Mock(),
            task_manager=Mock(),
            parent=None
        )

        # Set up shadow state
        mock_provider = Mock()
        controller._pending_provider = mock_provider
        controller._pending_provider_name = 'test_provider'
        controller._pending_provider_config = {'key': 'value'}
        controller._pending_test_only = False

        controller._on_connection_test_complete(mock_task)

        # Provider should be committed
        assert controller.provider is mock_provider
        assert controller.provider_name == 'test_provider'
        assert controller.provider_config == {'key': 'value'}

        # Shadow state should be cleared
        assert controller._pending_provider is None

    def test_connection_test_failure_preserves_current_provider(self):
        """Failed connection test should preserve current provider."""
        from sartracker.controllers.provider_controller import ProviderController

        mock_task = Mock()
        mock_task.success = False

        controller = ProviderController(
            iface=Mock(),
            task_manager=Mock(),
            parent=None
        )

        # Set current provider
        original_provider = Mock()
        controller.provider = original_provider
        controller.provider_name = 'original'

        # Set up shadow state
        controller._pending_provider = Mock()
        controller._pending_provider_name = 'new_provider'
        controller._pending_provider_config = {}
        controller._pending_test_only = False

        controller._on_connection_test_complete(mock_task)

        # Original provider should be preserved
        assert controller.provider is original_provider
        assert controller.provider_name == 'original'

        # Shadow state should be cleared
        assert controller._pending_provider is None

    def test_test_only_mode_does_not_commit(self):
        """test_only=True should not commit provider even on success."""
        from sartracker.controllers.provider_controller import ProviderController

        mock_task = Mock()
        mock_task.success = True

        controller = ProviderController(
            iface=Mock(),
            task_manager=Mock(),
            parent=None
        )

        # Set current provider
        original_provider = Mock()
        controller.provider = original_provider
        controller.provider_name = 'original'

        # Set up shadow state with test_only=True
        controller._pending_provider = Mock()
        controller._pending_provider_name = 'new_provider'
        controller._pending_provider_config = {}
        controller._pending_test_only = True  # Test only mode

        controller._on_connection_test_complete(mock_task)

        # Original provider should be preserved
        assert controller.provider is original_provider
        assert controller.provider_name == 'original'

        # Shadow state should be cleared
        assert controller._pending_provider is None


class TestProviderControllerPolling:
    """Tests for polling management."""

    def test_start_polling_requires_provider(self):
        """start_polling should fail without a provider."""
        from sartracker.controllers.provider_controller import ProviderController

        controller = ProviderController(
            iface=Mock(),
            task_manager=Mock(),
            parent=None
        )

        with pytest.raises(RuntimeError, match="without an active provider"):
            controller.start_polling(30)

    def test_start_polling_validates_interval(self):
        """start_polling should require interval >= 5 seconds."""
        from sartracker.controllers.provider_controller import ProviderController

        controller = ProviderController(
            iface=Mock(),
            task_manager=Mock(),
            parent=None
        )
        controller.provider = Mock()

        with pytest.raises(ValueError, match=">= 5 seconds"):
            controller.start_polling(3)

    def test_stop_polling(self):
        """stop_polling should stop the timer."""
        from sartracker.controllers.provider_controller import ProviderController

        controller = ProviderController(
            iface=Mock(),
            task_manager=Mock(),
            parent=None
        )
        controller.provider = Mock()

        # Mock the timer
        controller.poll_timer = Mock()
        controller.poll_timer.isActive.return_value = True

        controller.stop_polling()

        controller.poll_timer.stop.assert_called_once()


class TestProviderControllerStatus:
    """Tests for status tracking."""

    def test_status_snapshot_returns_dict(self):
        """status_snapshot should return a dictionary."""
        from sartracker.controllers.provider_controller import ProviderController

        controller = ProviderController(
            iface=Mock(),
            task_manager=Mock(),
            parent=None
        )

        status = controller.status_snapshot()

        assert isinstance(status, dict)
        assert 'provider' in status
        assert 'state' in status
        assert 'message' in status

    def test_update_refresh_stats(self):
        """update_refresh_stats should update cached values."""
        from sartracker.controllers.provider_controller import ProviderController

        controller = ProviderController(
            iface=Mock(),
            task_manager=Mock(),
            parent=None
        )

        controller.update_refresh_stats(
            devices_count=10,
            refresh_time='2025-01-01T12:00:00',
            refresh_duration_ms=150.5
        )

        assert controller._cached_device_count == 10
        assert controller._last_refresh_time == '2025-01-01T12:00:00'
        assert controller._last_refresh_duration_ms == 150.5


class TestProviderControllerCleanup:
    """Tests for cleanup behavior."""

    def test_cleanup_stops_polling(self):
        """cleanup should stop polling timer."""
        from sartracker.controllers.provider_controller import ProviderController

        controller = ProviderController(
            iface=Mock(),
            task_manager=Mock(),
            parent=None
        )

        # Mock the timer
        controller.poll_timer = Mock()
        controller.poll_timer.isActive.return_value = True

        controller.cleanup()

        controller.poll_timer.stop.assert_called_once()

    def test_cleanup_clears_provider(self):
        """cleanup should clear provider references."""
        from sartracker.controllers.provider_controller import ProviderController

        controller = ProviderController(
            iface=Mock(),
            task_manager=Mock(),
            parent=None
        )

        controller.provider = Mock()
        controller.provider_name = 'test'
        controller.provider_config = {}

        controller.cleanup()

        assert controller.provider is None
        assert controller.provider_name is None
        assert controller.provider_config is None

    def test_cleanup_clears_shadow_state(self):
        """cleanup should clear shadow state."""
        from sartracker.controllers.provider_controller import ProviderController

        controller = ProviderController(
            iface=Mock(),
            task_manager=Mock(),
            parent=None
        )

        controller._pending_provider = Mock()
        controller._pending_provider_name = 'test'
        controller._pending_test_only = True

        controller.cleanup()

        assert controller._pending_provider is None
        assert controller._pending_provider_name is None
        assert controller._pending_test_only is False
