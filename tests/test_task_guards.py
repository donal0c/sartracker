# -*- coding: utf-8 -*-
"""
Tests for Task Guard Utilities (Phase 6 Refactor).

Tests safe callback execution and component guards.
"""
import pytest
from unittest.mock import Mock, patch

from sartracker.utils.task_guards import (
    log_exception,
    safe_callback,
    require_components,
    guard_ui_update,
    CallbackGuard,
    components_ready,
    notify_safe,
)


class TestLogException:
    """Tests for log_exception."""

    def test_logs_exception_info(self, capsys):
        try:
            raise ValueError("test error")
        except ValueError as e:
            log_exception("[TEST]", "test_context", e)

        captured = capsys.readouterr()
        assert "[TEST]" in captured.out
        assert "test_context" in captured.out
        assert "ValueError" in captured.out
        assert "test error" in captured.out


class TestSafeCallback:
    """Tests for safe_callback decorator."""

    def test_normal_execution(self):
        @safe_callback()
        def my_func():
            return "success"

        result = my_func()
        assert result == "success"

    def test_catches_exceptions(self, capsys):
        @safe_callback(log_prefix="[TEST]")
        def failing_func():
            raise RuntimeError("test failure")

        result = failing_func()
        assert result is None  # Default return_on_error

        captured = capsys.readouterr()
        assert "RuntimeError" in captured.out

    def test_custom_return_on_error(self):
        @safe_callback(return_on_error="fallback")
        def failing_func():
            raise RuntimeError("test")

        result = failing_func()
        assert result == "fallback"

    def test_logs_entry_when_enabled(self, capsys):
        @safe_callback(log_prefix="[TEST]", log_entry=True)
        def my_func():
            return "ok"

        my_func()

        captured = capsys.readouterr()
        assert "Entering my_func" in captured.out


class TestRequireComponents:
    """Tests for require_components decorator."""

    def test_executes_when_components_exist(self):
        class TestClass:
            def __init__(self):
                self.panel = Mock()
                self.controller = Mock()

            @require_components('panel', 'controller')
            def do_work(self):
                return "done"

        obj = TestClass()
        result = obj.do_work()
        assert result == "done"

    def test_skips_when_component_missing(self, capsys):
        class TestClass:
            def __init__(self):
                self.panel = Mock()
                self.controller = None  # Missing!

            @require_components('panel', 'controller')
            def do_work(self):
                return "done"

        obj = TestClass()
        result = obj.do_work()
        assert result is None

        captured = capsys.readouterr()
        assert "controller" in captured.out
        assert "missing/deleted" in captured.out

    def test_skips_when_component_not_defined(self, capsys):
        class TestClass:
            @require_components('nonexistent')
            def do_work(self):
                return "done"

        obj = TestClass()
        result = obj.do_work()
        assert result is None


class TestGuardUiUpdate:
    """Tests for guard_ui_update decorator."""

    def test_executes_when_iface_exists(self):
        class TestClass:
            def __init__(self):
                self.iface = Mock()

            @guard_ui_update()
            def update(self):
                return "updated"

        obj = TestClass()
        result = obj.update()
        assert result == "updated"

    def test_skips_when_iface_none(self, capsys):
        class TestClass:
            def __init__(self):
                self.iface = None

            @guard_ui_update()
            def update(self):
                return "updated"

        obj = TestClass()
        result = obj.update()
        assert result is None

        captured = capsys.readouterr()
        assert "iface" in captured.out.lower()

    def test_checks_panel_when_specified(self, capsys):
        class TestClass:
            def __init__(self):
                self.iface = Mock()
                self.sar_panel = None  # Panel is None

            @guard_ui_update(panel_attr='sar_panel')
            def update(self):
                return "updated"

        obj = TestClass()
        result = obj.update()
        assert result is None

        captured = capsys.readouterr()
        assert "sar_panel" in captured.out

    def test_catches_exceptions(self, capsys):
        class TestClass:
            def __init__(self):
                self.iface = Mock()

            @guard_ui_update()
            def failing_update(self):
                raise ValueError("update failed")

        obj = TestClass()
        result = obj.failing_update()
        assert result is None

        captured = capsys.readouterr()
        assert "ValueError" in captured.out


class TestCallbackGuard:
    """Tests for CallbackGuard context manager."""

    def test_ready_when_all_components_exist(self):
        class TestClass:
            def __init__(self):
                self.panel = Mock()
                self.controller = Mock()

        obj = TestClass()

        with CallbackGuard(obj, 'panel', 'controller') as guard:
            assert guard.ready is True

    def test_not_ready_when_component_missing(self, capsys):
        class TestClass:
            def __init__(self):
                self.panel = Mock()
                self.controller = None

        obj = TestClass()

        with CallbackGuard(obj, 'panel', 'controller') as guard:
            assert guard.ready is False

        captured = capsys.readouterr()
        assert "controller" in captured.out

    def test_catches_exceptions(self, capsys):
        obj = Mock()
        obj.panel = Mock()

        with CallbackGuard(obj, 'panel') as guard:
            assert guard.ready is True
            raise ValueError("test exception")

        # Exception should be suppressed
        captured = capsys.readouterr()
        assert "ValueError" in captured.out

    def test_context_in_logging(self, capsys):
        obj = Mock()
        obj.missing = None

        with CallbackGuard(obj, 'missing', context='refresh_complete') as guard:
            pass

        captured = capsys.readouterr()
        assert "refresh_complete" in captured.out


class TestComponentsReady:
    """Tests for components_ready utility."""

    def test_returns_true_when_all_exist(self):
        class Obj:
            a = Mock()
            b = Mock()

        assert components_ready(Obj(), 'a', 'b') is True

    def test_returns_false_when_any_none(self):
        class Obj:
            a = Mock()
            b = None

        assert components_ready(Obj(), 'a', 'b') is False

    def test_returns_false_when_attr_missing(self):
        class Obj:
            a = Mock()

        assert components_ready(Obj(), 'a', 'nonexistent') is False

    def test_returns_true_with_no_args(self):
        assert components_ready(object()) is True


class TestNotifySafe:
    """Tests for notify_safe utility."""

    def test_calls_notify_function(self):
        message_bar = Mock()
        notify_func = Mock()

        result = notify_safe(message_bar, notify_func, "Title", "Message")

        assert result is True
        notify_func.assert_called_once_with(message_bar, "Title", "Message", duration=5)

    def test_returns_false_when_message_bar_none(self, capsys):
        notify_func = Mock()

        result = notify_safe(None, notify_func, "Title", "Message")

        assert result is False
        notify_func.assert_not_called()

        captured = capsys.readouterr()
        assert "message_bar missing/deleted" in captured.out

    def test_handles_notify_exception(self, capsys):
        message_bar = Mock()
        notify_func = Mock(side_effect=RuntimeError("display failed"))

        result = notify_safe(message_bar, notify_func, "Title", "Message")

        assert result is False

        captured = capsys.readouterr()
        assert "Failed to show notification" in captured.out

    def test_custom_duration(self):
        message_bar = Mock()
        notify_func = Mock()

        notify_safe(message_bar, notify_func, "Title", "Message", duration=10)

        notify_func.assert_called_once_with(message_bar, "Title", "Message", duration=10)
