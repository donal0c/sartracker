# -*- coding: utf-8 -*-
"""
Tests for Qt5/Qt6 compatibility enums required by Focus Mode Plus.

These tests verify that the new enum constants added for Focus Mode Plus
are properly exported and can be imported from utils.qt_compat.

TDD: Tests written BEFORE implementation (SAR-cksi.1)
"""
import pytest


class TestWindowStateEnums:
    """Tests for WindowState enum exports required for fullscreen handling."""

    def test_window_no_state_importable(self):
        """WindowNoState enum should be importable from qt_compat."""
        from utils.qt_compat import WindowNoState
        assert WindowNoState is not None

    def test_window_minimized_importable(self):
        """WindowMinimized enum should be importable from qt_compat."""
        from utils.qt_compat import WindowMinimized
        assert WindowMinimized is not None

    def test_window_maximized_importable(self):
        """WindowMaximized enum should be importable from qt_compat."""
        from utils.qt_compat import WindowMaximized
        assert WindowMaximized is not None

    def test_window_fullscreen_importable(self):
        """WindowFullScreen enum should be importable from qt_compat."""
        from utils.qt_compat import WindowFullScreen
        assert WindowFullScreen is not None

    def test_window_active_importable(self):
        """WindowActive enum should be importable from qt_compat."""
        from utils.qt_compat import WindowActive
        assert WindowActive is not None

    def test_window_state_enums_in_all(self):
        """All WindowState enums should be in __all__ export list."""
        from utils import qt_compat
        assert 'WindowNoState' in qt_compat.__all__
        assert 'WindowMinimized' in qt_compat.__all__
        assert 'WindowMaximized' in qt_compat.__all__
        assert 'WindowFullScreen' in qt_compat.__all__
        assert 'WindowActive' in qt_compat.__all__


class TestShortcutContextEnums:
    """Tests for ShortcutContext enum exports required for escape key handling."""

    def test_widget_shortcut_importable(self):
        """WidgetShortcut enum should be importable from qt_compat."""
        from utils.qt_compat import WidgetShortcut
        assert WidgetShortcut is not None

    def test_widget_with_children_shortcut_importable(self):
        """WidgetWithChildrenShortcut enum should be importable from qt_compat."""
        from utils.qt_compat import WidgetWithChildrenShortcut
        assert WidgetWithChildrenShortcut is not None

    def test_window_shortcut_importable(self):
        """WindowShortcut enum should be importable from qt_compat."""
        from utils.qt_compat import WindowShortcut
        assert WindowShortcut is not None

    def test_application_shortcut_importable(self):
        """ApplicationShortcut enum should be importable from qt_compat."""
        from utils.qt_compat import ApplicationShortcut
        assert ApplicationShortcut is not None

    def test_shortcut_context_enums_in_all(self):
        """All ShortcutContext enums should be in __all__ export list."""
        from utils import qt_compat
        assert 'WidgetShortcut' in qt_compat.__all__
        assert 'WidgetWithChildrenShortcut' in qt_compat.__all__
        assert 'WindowShortcut' in qt_compat.__all__
        assert 'ApplicationShortcut' in qt_compat.__all__


class TestDockWidgetFeatureEnums:
    """Tests for DockWidgetFeature enum exports required for dock protection."""

    def test_dock_widget_closable_importable(self):
        """DockWidgetClosable enum should be importable from qt_compat."""
        from utils.qt_compat import DockWidgetClosable
        assert DockWidgetClosable is not None

    def test_dock_widget_movable_importable(self):
        """DockWidgetMovable enum should be importable from qt_compat."""
        from utils.qt_compat import DockWidgetMovable
        assert DockWidgetMovable is not None

    def test_dock_widget_floatable_importable(self):
        """DockWidgetFloatable enum should be importable from qt_compat."""
        from utils.qt_compat import DockWidgetFloatable
        assert DockWidgetFloatable is not None

    def test_no_dock_widget_features_importable(self):
        """NoDockWidgetFeatures enum should be importable from qt_compat."""
        from utils.qt_compat import NoDockWidgetFeatures
        assert NoDockWidgetFeatures is not None

    def test_dock_widget_feature_enums_in_all(self):
        """All DockWidgetFeature enums should be in __all__ export list."""
        from utils import qt_compat
        assert 'DockWidgetClosable' in qt_compat.__all__
        assert 'DockWidgetMovable' in qt_compat.__all__
        assert 'DockWidgetFloatable' in qt_compat.__all__
        assert 'NoDockWidgetFeatures' in qt_compat.__all__


@pytest.mark.qgis_required
class TestEnumValuesWithQGIS:
    """Tests that verify enum values are correct when QGIS is available.

    These tests require real QGIS to verify the enums map to actual Qt values.
    """

    def test_window_state_enums_are_distinct(self):
        """WindowState enums should have distinct integer values."""
        from utils.qt_compat import (
            WindowNoState, WindowMinimized, WindowMaximized,
            WindowFullScreen, WindowActive
        )
        values = {
            int(WindowNoState), int(WindowMinimized), int(WindowMaximized),
            int(WindowFullScreen), int(WindowActive)
        }
        # All 5 values should be distinct
        assert len(values) == 5

    def test_shortcut_context_enums_are_distinct(self):
        """ShortcutContext enums should have distinct integer values."""
        from utils.qt_compat import (
            WidgetShortcut, WidgetWithChildrenShortcut,
            WindowShortcut, ApplicationShortcut
        )
        values = {
            int(WidgetShortcut), int(WidgetWithChildrenShortcut),
            int(WindowShortcut), int(ApplicationShortcut)
        }
        # All 4 values should be distinct
        assert len(values) == 4

    def test_dock_widget_features_are_bitflags(self):
        """DockWidgetFeature enums should be valid bitflags."""
        from utils.qt_compat import (
            DockWidgetClosable, DockWidgetMovable,
            DockWidgetFloatable, NoDockWidgetFeatures
        )
        # NoDockWidgetFeatures should be 0
        assert int(NoDockWidgetFeatures) == 0
        # Others should be powers of 2 (bitflags)
        assert int(DockWidgetClosable) in {0x01, 1}
        assert int(DockWidgetMovable) in {0x02, 2}
        assert int(DockWidgetFloatable) in {0x04, 4}

    def test_can_combine_dock_widget_features(self):
        """DockWidgetFeature enums should be combinable with bitwise OR."""
        from utils.qt_compat import (
            DockWidgetClosable, DockWidgetMovable, DockWidgetFloatable
        )
        # Combining should work without error
        combined = DockWidgetClosable | DockWidgetMovable | DockWidgetFloatable
        assert combined is not None
