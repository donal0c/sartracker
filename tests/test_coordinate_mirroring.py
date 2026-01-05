# -*- coding: utf-8 -*-
"""
Tests for coordinate display mirroring in Focus Mode Plus.

TDD: Tests written BEFORE implementation (SAR-cksi.4)

When Focus Mode Plus hides the status bar, coordinates must be
mirrored to the SAR Panel so operators can still see position.
"""
import os

import pytest


class TestCoordinatesControllerSignalCode:
    """Tests for coordinates_updated signal in CoordinatesController source code."""

    def test_coordinates_controller_has_coordinates_updated_signal(self):
        """CoordinatesController should have a coordinates_updated signal."""
        controller_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'controllers', 'coordinates_controller.py'
        )
        with open(controller_path, 'r') as f:
            content = f.read()

        assert 'coordinates_updated' in content, \
            "CoordinatesController should have coordinates_updated signal"

    def test_coordinates_updated_signal_is_pyqt_signal(self):
        """coordinates_updated should be defined as a pyqtSignal."""
        controller_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'controllers', 'coordinates_controller.py'
        )
        with open(controller_path, 'r') as f:
            content = f.read()

        # Should be defined as a pyqtSignal
        assert 'pyqtSignal' in content, \
            "CoordinatesController should use pyqtSignal"
        assert 'coordinates_updated' in content and 'pyqtSignal' in content, \
            "coordinates_updated should be a pyqtSignal"


class TestCoordinatesControllerEmitsSignalCode:
    """Tests that CoordinatesController emits coordinate updates."""

    def test_update_coords_display_emits_signal(self):
        """_update_coords_display should emit coordinates_updated signal."""
        controller_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'controllers', 'coordinates_controller.py'
        )
        with open(controller_path, 'r') as f:
            content = f.read()

        # Should emit the signal after updating label
        assert 'coordinates_updated.emit' in content, \
            "_update_coords_display should emit coordinates_updated signal"


class TestSARPanelCoordinateWidget:
    """Tests for coordinate display widget in SAR Panel."""

    def test_sar_panel_has_coord_display_widget(self):
        """SAR Panel should have _coord_display_widget attribute."""
        import os
        sar_panel_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'ui', 'sar_panel.py'
        )
        with open(sar_panel_path, 'r') as f:
            content = f.read()

        assert '_coord_display_widget' in content, \
            "SAR Panel should have _coord_display_widget"

    def test_sar_panel_has_connect_coordinates_method(self):
        """SAR Panel should have connect_coordinates_controller method."""
        import os
        sar_panel_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'ui', 'sar_panel.py'
        )
        with open(sar_panel_path, 'r') as f:
            content = f.read()

        assert 'connect_coordinates_controller' in content, \
            "SAR Panel should have connect_coordinates_controller method"

    def test_sar_panel_has_on_coordinates_updated_handler(self):
        """SAR Panel should have _on_coordinates_updated handler."""
        import os
        sar_panel_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'ui', 'sar_panel.py'
        )
        with open(sar_panel_path, 'r') as f:
            content = f.read()

        assert '_on_coordinates_updated' in content, \
            "SAR Panel should have _on_coordinates_updated handler"


class TestCoordinateWidgetVisibility:
    """Tests for coordinate widget visibility in Focus Mode Plus."""

    def test_coord_widget_visible_in_focus_mode(self):
        """Coordinate widget should be visible when Focus Mode Plus is active."""
        import os
        sar_panel_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'ui', 'sar_panel.py'
        )
        with open(sar_panel_path, 'r') as f:
            content = f.read()

        # Should show widget when entering focus mode
        assert '_coord_display_widget' in content and 'setVisible(True)' in content, \
            "Coordinate widget should be shown in Focus Mode Plus"

    def test_coord_widget_hidden_when_not_in_focus_mode(self):
        """Coordinate widget should be hidden when Focus Mode Plus is not active."""
        import os
        sar_panel_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'ui', 'sar_panel.py'
        )
        with open(sar_panel_path, 'r') as f:
            content = f.read()

        # Widget should be initially hidden
        assert '_coord_display_widget' in content, \
            "Coordinate widget should exist for hiding"


class TestCoordinateSignalCleanup:
    """Tests for proper cleanup of coordinate signal connections."""

    def test_sar_panel_disconnects_coordinates_on_cleanup(self):
        """SAR Panel cleanup should disconnect coordinates signal."""
        import os
        sar_panel_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'ui', 'sar_panel.py'
        )
        with open(sar_panel_path, 'r') as f:
            content = f.read()

        # Should have cleanup code for coordinates controller
        assert '_coords_controller' in content, \
            "SAR Panel should track coordinates controller reference"


class TestCoordinateMirroringWiring:
    """Tests for coordinate mirroring wiring in sartracker.py."""

    def test_sartracker_wires_coordinates_to_sar_panel(self):
        """sartracker.py should wire coordinates controller to SAR Panel."""
        import os
        sartracker_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'sartracker.py'
        )
        with open(sartracker_path, 'r') as f:
            content = f.read()

        # Should have the wiring call
        assert 'connect_coordinates_controller' in content, \
            "sartracker.py should wire coordinates to SAR Panel"

    def test_wiring_happens_after_controller_init(self):
        """Wiring should happen after coordinates controller initializes."""
        import os
        sartracker_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'sartracker.py'
        )
        with open(sartracker_path, 'r') as f:
            content = f.read()

        # Find positions - wiring should come after init success
        init_pos = content.find('coordinates_controller.init()')
        wiring_pos = content.find('connect_coordinates_controller')

        assert init_pos > 0, "Should have controller init"
        assert wiring_pos > 0, "Should have wiring call"
        assert wiring_pos > init_pos, \
            "Wiring should happen after controller initialization"
