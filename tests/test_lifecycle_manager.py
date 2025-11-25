# -*- coding: utf-8 -*-
"""
Tests for Plugin Lifecycle Manager (Phase 1 Refactor).

These tests validate the lifecycle management logic without requiring
QGIS runtime, using mocks for Qt and QGIS components.
"""
import pytest
from unittest.mock import Mock, MagicMock, patch


# Import the module under test
from sartracker.services.lifecycle_manager import (
    ComponentState,
    ComponentInfo,
    ComponentRegistry,
    PluginLifecycleManager,
    validate_init_preconditions,
)


class TestComponentInfo:
    """Tests for ComponentInfo dataclass."""

    def test_initial_state_is_pending(self):
        """New ComponentInfo should have PENDING state."""
        info = ComponentInfo(name="test", instance=object())
        assert info.state == ComponentState.PENDING

    def test_mark_initialized(self):
        """mark_initialized should set state to INITIALIZED."""
        info = ComponentInfo(name="test", instance=object())
        info.mark_initialized()
        assert info.state == ComponentState.INITIALIZED
        assert info.error is None

    def test_mark_failed_captures_error(self):
        """mark_failed should capture exception details."""
        info = ComponentInfo(name="test", instance=object())
        try:
            raise ValueError("test error")
        except ValueError as e:
            info.mark_failed(e)

        assert info.state == ComponentState.FAILED
        assert info.error == "test error"
        assert info.error_traceback is not None

    def test_mark_cleaned_up(self):
        """mark_cleaned_up should set state to CLEANED_UP."""
        info = ComponentInfo(name="test", instance=object())
        info.mark_initialized()
        info.mark_cleaned_up()
        assert info.state == ComponentState.CLEANED_UP


class TestComponentRegistry:
    """Tests for ComponentRegistry."""

    def test_register_component(self):
        """Should register component successfully."""
        registry = ComponentRegistry()
        obj = object()
        registry.register("comp1", obj)

        assert registry.get("comp1") is obj
        assert registry.is_initialized("comp1")

    def test_register_with_cleanup(self):
        """Should register component with cleanup function."""
        registry = ComponentRegistry()
        cleanup_called = []

        def cleanup_fn():
            cleanup_called.append(True)

        registry.register("comp1", object(), cleanup_fn=cleanup_fn)
        info = registry.get_info("comp1")

        assert info.cleanup_fn is cleanup_fn

    def test_register_with_dependencies(self):
        """Should register component with dependencies."""
        registry = ComponentRegistry()
        registry.register("dep1", object())
        registry.register("comp1", object(), dependencies=["dep1"])

        info = registry.get_info("comp1")
        assert "dep1" in info.dependencies

    def test_get_returns_none_for_missing(self):
        """get should return None for unregistered component."""
        registry = ComponentRegistry()
        assert registry.get("nonexistent") is None

    def test_is_initialized_false_for_missing(self):
        """is_initialized should return False for unregistered."""
        registry = ComponentRegistry()
        assert registry.is_initialized("nonexistent") is False

    def test_all_ready_true_when_all_initialized(self):
        """all_ready should return True when all components initialized."""
        registry = ComponentRegistry()
        registry.register("comp1", object())
        registry.register("comp2", object())

        assert registry.all_ready("comp1", "comp2") is True

    def test_all_ready_false_when_missing(self):
        """all_ready should return False when any component missing."""
        registry = ComponentRegistry()
        registry.register("comp1", object())

        assert registry.all_ready("comp1", "comp2") is False

    def test_cleanup_order_is_reverse(self):
        """cleanup_order should be reverse of registration order."""
        registry = ComponentRegistry()
        registry.register("first", object())
        registry.register("second", object())
        registry.register("third", object())

        order = registry.cleanup_order()
        assert order == ["third", "second", "first"]

    def test_cleanup_all_calls_cleanup_functions(self):
        """cleanup_all should call all cleanup functions."""
        registry = ComponentRegistry()
        cleanup_calls = []

        registry.register("comp1", object(), cleanup_fn=lambda: cleanup_calls.append("comp1"))
        registry.register("comp2", object(), cleanup_fn=lambda: cleanup_calls.append("comp2"))

        registry.cleanup_all()

        assert "comp1" in cleanup_calls
        assert "comp2" in cleanup_calls

    def test_cleanup_all_reverse_order(self):
        """cleanup_all should call cleanups in reverse order."""
        registry = ComponentRegistry()
        cleanup_calls = []

        registry.register("first", object(), cleanup_fn=lambda: cleanup_calls.append("first"))
        registry.register("second", object(), cleanup_fn=lambda: cleanup_calls.append("second"))

        registry.cleanup_all()

        assert cleanup_calls == ["second", "first"]

    def test_cleanup_all_handles_errors(self):
        """cleanup_all should continue after cleanup errors."""
        registry = ComponentRegistry()
        cleanup_calls = []

        def failing_cleanup():
            raise RuntimeError("cleanup failed")

        registry.register("comp1", object(), cleanup_fn=failing_cleanup)
        registry.register("comp2", object(), cleanup_fn=lambda: cleanup_calls.append("comp2"))

        errors = registry.cleanup_all()

        assert "comp1" in errors
        assert "comp2" in cleanup_calls  # Should still be called

    def test_cleanup_all_marks_state(self):
        """cleanup_all should mark components as cleaned up."""
        registry = ComponentRegistry()
        registry.register("comp1", object(), cleanup_fn=lambda: None)

        registry.cleanup_all()

        info = registry.get_info("comp1")
        assert info.state == ComponentState.CLEANED_UP

    def test_get_status_returns_all_components(self):
        """get_status should return status of all components."""
        registry = ComponentRegistry()
        registry.register("comp1", object())
        registry.register("comp2", object(), dependencies=["comp1"])

        status = registry.get_status()

        assert "comp1" in status
        assert "comp2" in status
        assert status["comp1"]["state"] == "initialized"
        assert status["comp2"]["dependencies"] == ["comp1"]

    def test_clear_removes_all(self):
        """clear should remove all registered components."""
        registry = ComponentRegistry()
        registry.register("comp1", object())
        registry.register("comp2", object())

        registry.clear()

        assert registry.get("comp1") is None
        assert registry.get("comp2") is None


class TestPluginLifecycleManager:
    """Tests for PluginLifecycleManager."""

    def test_init_without_iface(self):
        """Should initialize without QGIS iface (for testing)."""
        manager = PluginLifecycleManager(iface=None)
        assert manager.iface is None
        assert manager.registry is not None

    def test_register_and_get_component(self):
        """Should register and retrieve components."""
        manager = PluginLifecycleManager()
        obj = object()
        manager.register_component("test", obj)

        assert manager.get_component("test") is obj

    def test_components_ready(self):
        """components_ready should check multiple components."""
        manager = PluginLifecycleManager()
        manager.register_component("comp1", object())
        manager.register_component("comp2", object())

        assert manager.components_ready("comp1", "comp2") is True
        assert manager.components_ready("comp1", "comp3") is False

    def test_track_signal(self):
        """Should track signal connections."""
        manager = PluginLifecycleManager()
        signal = Mock()
        slot = Mock()

        manager.track_signal(signal, slot)

        assert len(manager._signal_connections) == 1

    def test_disconnect_all_signals(self):
        """disconnect_all_signals should disconnect all tracked signals."""
        manager = PluginLifecycleManager()
        signal = Mock()
        slot = Mock()

        manager.track_signal(signal, slot)
        manager.disconnect_all_signals()

        signal.disconnect.assert_called_once_with(slot)
        assert len(manager._signal_connections) == 0

    def test_disconnect_handles_errors(self):
        """disconnect_all_signals should handle disconnect errors."""
        manager = PluginLifecycleManager()
        signal = Mock()
        signal.disconnect.side_effect = TypeError("not connected")
        slot = Mock()

        manager.track_signal(signal, slot)
        # Should not raise
        manager.disconnect_all_signals()

    def test_record_import_error(self):
        """Should record import errors."""
        manager = PluginLifecycleManager()

        try:
            raise ImportError("module not found")
        except ImportError as e:
            manager.record_import_error("test_module", e)

        assert manager.has_import_errors() is True
        errors = manager.get_import_errors()
        assert len(errors) == 1
        assert errors[0][0] == "test_module"

    def test_has_import_errors_false_initially(self):
        """has_import_errors should be False initially."""
        manager = PluginLifecycleManager()
        assert manager.has_import_errors() is False

    def test_format_import_errors(self):
        """format_import_errors should produce readable output."""
        manager = PluginLifecycleManager()

        try:
            raise ImportError("test error")
        except ImportError as e:
            manager.record_import_error("test.module", e)

        formatted = manager.format_import_errors()

        assert "test.module" in formatted
        assert "test error" in formatted
        assert "SUGGESTED ACTIONS" in formatted

    def test_mark_init_complete(self):
        """Should track init completion state."""
        manager = PluginLifecycleManager()
        assert manager.is_init_complete() is False

        manager.mark_init_complete()
        assert manager.is_init_complete() is True

    def test_is_init_complete_false_with_errors(self):
        """is_init_complete should be False if import errors exist."""
        manager = PluginLifecycleManager()
        manager.mark_init_complete()

        manager.record_import_error("module", ImportError("test"))

        assert manager.is_init_complete() is False

    def test_cleanup_disconnects_signals_first(self):
        """cleanup should disconnect signals before component cleanup."""
        manager = PluginLifecycleManager()
        call_order = []

        signal = Mock()
        signal.disconnect = Mock(side_effect=lambda s: call_order.append("signal"))
        slot = Mock()

        manager.track_signal(signal, slot)
        manager.register_component(
            "comp1",
            object(),
            cleanup_fn=lambda: call_order.append("component")
        )

        manager.cleanup()

        # Signals disconnected before components
        assert call_order.index("signal") < call_order.index("component")

    def test_cleanup_resets_init_state(self):
        """cleanup should reset init complete state."""
        manager = PluginLifecycleManager()
        manager.mark_init_complete()

        manager.cleanup()

        assert manager.is_init_complete() is False

    def test_get_diagnostics(self):
        """get_diagnostics should return status info."""
        manager = PluginLifecycleManager()
        manager.register_component("test", object())
        manager.mark_init_complete()

        diag = manager.get_diagnostics()

        assert diag["init_complete"] is True
        assert diag["import_errors_count"] == 0
        assert "test" in diag["components"]


class TestValidateInitPreconditions:
    """Tests for validate_init_preconditions."""

    def test_warns_if_iface_none(self):
        """Should warn if iface is None."""
        warnings = validate_init_preconditions(None)
        assert any("iface" in w.lower() for w in warnings)

    def test_no_warnings_with_valid_iface(self):
        """Should have no warnings with valid iface and modern QGIS."""
        mock_iface = Mock()
        mock_qgis = Mock()
        mock_qgis.QGIS_VERSION_INT = 34000  # QGIS 3.40
        mock_qgis.QGIS_VERSION = "3.40.0"

        # Patch the import inside the function
        with patch.dict('sys.modules', {'qgis.core': Mock(Qgis=mock_qgis)}):
            warnings = validate_init_preconditions(mock_iface)

        # Filter out any import warnings (from actual qgis import failing)
        real_warnings = [w for w in warnings if "import" not in w.lower()]
        assert len(real_warnings) == 0

    def test_warns_for_old_qgis(self):
        """Should warn for QGIS versions older than 3.28."""
        mock_iface = Mock()
        mock_qgis = Mock()
        mock_qgis.QGIS_VERSION_INT = 32600  # QGIS 3.26
        mock_qgis.QGIS_VERSION = "3.26.0"

        # Patch the import inside the function
        with patch.dict('sys.modules', {'qgis.core': Mock(Qgis=mock_qgis)}):
            warnings = validate_init_preconditions(mock_iface)

        assert any("3.28" in w for w in warnings)


class TestPluginBootstrapIntegration:
    """Integration tests for plugin bootstrap scenarios."""

    def test_full_lifecycle_no_errors(self):
        """Test complete lifecycle without errors."""
        manager = PluginLifecycleManager(log_prefix="[TEST]")

        # Simulate component registration during initGui
        manager.register_component("task_manager", Mock(), cleanup_fn=lambda: None)
        manager.register_component("layer_manager", Mock(), cleanup_fn=lambda: None)
        manager.register_component("sar_panel", Mock(), cleanup_fn=lambda: None, dependencies=["layer_manager"])

        manager.mark_init_complete()

        assert manager.is_init_complete()
        assert manager.components_ready("task_manager", "layer_manager", "sar_panel")

        # Simulate unload
        errors = manager.cleanup()

        assert len(errors) == 0
        assert not manager.is_init_complete()

    def test_lifecycle_with_import_failure(self):
        """Test lifecycle when imports fail."""
        manager = PluginLifecycleManager()

        # Simulate import failure
        manager.record_import_error("ui.sar_panel", ImportError("Qt not found"))

        # Should not mark as complete even if called
        manager.mark_init_complete()

        assert not manager.is_init_complete()
        assert manager.has_import_errors()

    def test_cleanup_with_partial_init(self):
        """Test cleanup when only some components initialized."""
        manager = PluginLifecycleManager()

        # Only some components registered
        manager.register_component("task_manager", Mock(), cleanup_fn=lambda: None)
        # Simulate failure before sar_panel registration

        # Cleanup should still work
        errors = manager.cleanup()

        assert len(errors) == 0

    def test_rapid_reload_scenario(self):
        """Test rapid plugin reload (init -> unload -> init -> unload)."""
        manager = PluginLifecycleManager()

        for _ in range(3):
            # Init cycle
            manager.register_component("comp1", Mock(), cleanup_fn=lambda: None)
            manager.mark_init_complete()
            assert manager.is_init_complete()

            # Unload cycle
            manager.cleanup()
            manager.registry.clear()
            assert not manager.is_init_complete()
