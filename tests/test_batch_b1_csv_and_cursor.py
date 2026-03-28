# -*- coding: utf-8 -*-
"""Batch B1 regression tests.

Covers two requirements:
1. CSV import functionality is removed from UI/provider surface.
2. Clue/casualty marker placement requests apply explicit cursor context.
"""

from unittest.mock import MagicMock



def test_registry_does_not_register_csv_provider():
    """CSV provider should no longer be available for selection/instantiation."""
    from sartracker.providers.registry import registry

    assert registry.is_registered("csv") is False



def test_sar_panel_no_csv_load_signal():
    """SAR panel should not expose csv_load_requested signal."""
    from sartracker.ui.sar_panel import SARPanel

    assert hasattr(SARPanel, "csv_load_requested") is False


def test_sar_panel_exposes_marker_by_grid_reference_signal():
    """SAR panel should expose explicit marker-by-grid-reference workflow."""
    import os

    root = os.path.dirname(os.path.dirname(__file__))
    source_path = os.path.join(root, "ui", "sar_panel.py")
    with open(source_path, "r", encoding="utf-8") as handle:
        source = handle.read()

    assert "add_marker_by_grid_requested = pyqtSignal()" in source


def test_sar_panel_exposes_generic_marker_signal_and_button_text():
    """SAR panel should use one generic Marker / Clues entry point in the dock."""
    import os

    root = os.path.dirname(os.path.dirname(__file__))
    source_path = os.path.join(root, "ui", "sar_panel.py")
    with open(source_path, "r", encoding="utf-8") as handle:
        source = handle.read()

    assert "add_marker_requested = pyqtSignal()" in source
    assert 'QPushButton("Marker / Clues")' in source
    assert 'QPushButton("Clue")' not in source
    assert 'QPushButton("Hazard")' not in source
    assert 'QPushButton("Casualty")' not in source



def test_plugin_no_load_csv_handler():
    """Plugin should not maintain legacy _on_load_csv wiring endpoint."""
    from sartracker.sartracker import sartracker

    assert hasattr(sartracker, "_on_load_csv") is False


def test_provider_controller_unavailable_messages_do_not_reference_csv_legacy():
    """Provider-controller errors should not reference removed CSV legacy flow."""
    import os

    root = os.path.dirname(os.path.dirname(__file__))
    source_path = os.path.join(root, "sartracker.py")
    with open(source_path, "r", encoding="utf-8") as handle:
        source = handle.read()

    assert "CSV loading available via legacy workflow" not in source
    assert "Restart plugin and run Diagnostics." in source


def _build_map_tools_controller_with_marker_tool(marker_tool):
    from sartracker.controllers.map_tools_controller import MapToolsController

    iface = MagicMock()
    iface.mapCanvas.return_value = MagicMock()
    iface.messageBar.return_value = MagicMock()

    controller = MapToolsController(iface=iface)
    controller.marker_tool = marker_tool
    controller.tool_registry = None
    return controller, iface



def test_add_clue_sets_marker_cursor_context():
    """Clue placement should set a clue-specific cursor context."""
    marker_tool = MagicMock()
    controller, iface = _build_map_tools_controller_with_marker_tool(marker_tool)

    controller.on_add_clue_requested()

    marker_tool.set_marker_context.assert_called_once_with("clue")
    iface.mapCanvas.return_value.setMapTool.assert_called_once_with(marker_tool)


def test_add_marker_requested_uses_generic_context(monkeypatch):
    """Generic Marker / Clues workflow should use neutral cursor context."""
    from sartracker.controllers import map_tools_controller as controller_module

    marker_tool = MagicMock()
    controller, iface = _build_map_tools_controller_with_marker_tool(marker_tool)
    messages = []

    monkeypatch.setattr(
        controller_module,
        "info",
        lambda _bar, title, message, duration=0: messages.append((title, message, duration)),
    )

    controller.on_add_marker_requested()

    marker_tool.set_marker_context.assert_called_once_with(None)
    iface.mapCanvas.return_value.setMapTool.assert_called_once_with(marker_tool)
    assert messages == [
        (
            "SAR Tracker",
            "Click on map to add a marker, clue, hazard, or casualty",
            4,
        )
    ]



def test_add_casualty_sets_marker_cursor_context():
    """Casualty placement should set a casualty-specific cursor context."""
    marker_tool = MagicMock()
    controller, iface = _build_map_tools_controller_with_marker_tool(marker_tool)

    controller.on_add_casualty_requested()

    marker_tool.set_marker_context.assert_called_once_with("casualty")
    iface.mapCanvas.return_value.setMapTool.assert_called_once_with(marker_tool)


def test_add_casualty_prompt_does_not_use_false_critical_title(monkeypatch):
    """Normal casualty placement prompt should not look like a runtime critical error."""
    from sartracker.controllers import map_tools_controller as controller_module

    marker_tool = MagicMock()
    controller, _iface = _build_map_tools_controller_with_marker_tool(marker_tool)
    messages = []

    monkeypatch.setattr(
        controller_module,
        "info",
        lambda _bar, title, message, duration=0: messages.append((title, message, duration)),
    )

    controller.on_add_casualty_requested()

    assert messages == [
        (
            "SAR Tracker",
            "Click on map to add Casualty location (found injured/deceased person)",
            5,
        )
    ]


def test_map_tools_controller_exposes_marker_by_grid_reference_handler():
    """Map tools controller should offer explicit marker-by-grid entry path."""
    from sartracker.controllers.map_tools_controller import MapToolsController

    assert hasattr(MapToolsController, "on_add_marker_by_grid_requested") is True


def test_map_tools_controller_exposes_generic_marker_handler():
    """Map tools controller should offer generic Marker / Clues map-click path."""
    from sartracker.controllers.map_tools_controller import MapToolsController

    assert hasattr(MapToolsController, "on_add_marker_requested") is True
