# -*- coding: utf-8 -*-
"""Regression tests for custom marker cursor rendering safety."""

import sys
import types
from types import SimpleNamespace

from unittest.mock import MagicMock

try:
    import qgis  # type: ignore  # noqa: F401
except ImportError:  # pragma: no cover - executed only in CI without QGIS
    from tests.test_layer_manager_resilience import (  # type: ignore
        _install_notify_stub,
        _install_qgis_stubs,
    )

    _install_qgis_stubs()
    _install_notify_stub()


def _build_tool(monkeypatch):
    gui_mod = sys.modules.get("qgis.gui")
    if gui_mod is None:
        gui_mod = types.ModuleType("qgis.gui")
        sys.modules["qgis.gui"] = gui_mod
    if not hasattr(gui_mod, "QgsMapTool"):
        class _FakeMapTool:
            def __init__(self, canvas):
                self.canvas = canvas

            def setCursor(self, _cursor):
                return None

            def toMapCoordinates(self, point):
                return point

            def activate(self):
                return None

            def deactivate(self):
                return None

        gui_mod.QgsMapTool = _FakeMapTool
    for name in ("QgsRubberBand", "QgsVertexMarker", "QgsMapToolPan"):
        if not hasattr(gui_mod, name):
            gui_mod.__dict__[name] = type(name, (), {"__init__": lambda self, *args, **kwargs: None})

    from sartracker.maptools import marker_tool as marker_tool_module
    from sartracker.maptools.marker_tool import MarkerMapTool

    monkeypatch.setattr(marker_tool_module, "QCursor", lambda *args: ("cursor", args))
    monkeypatch.setattr(marker_tool_module, "CrossCursor", object())

    tool = MarkerMapTool.__new__(MarkerMapTool)
    tool.canvas = MagicMock()
    tool.iface = SimpleNamespace(messageBar=lambda: MagicMock())
    return marker_tool_module, tool


def test_build_context_cursor_returns_none_when_painter_is_inactive(monkeypatch):
    marker_tool_module, tool = _build_tool(monkeypatch)

    class _FakePixmap:
        def __init__(self, *_args, **_kwargs):
            pass

        def fill(self, *_args, **_kwargs):
            return None

    class _InactivePainter:
        Antialiasing = object()

        def __init__(self, _pixmap):
            self.end_called = False

        def isActive(self):
            return False

        def setRenderHint(self, *_args, **_kwargs):
            raise AssertionError("Inactive painter should not be used")

        def end(self):
            self.end_called = True

    monkeypatch.setattr(marker_tool_module, "QPixmap", _FakePixmap)
    monkeypatch.setattr(marker_tool_module, "QPainter", _InactivePainter)

    assert tool._build_context_cursor(marker_tool_module.QColor("#ff8c00")) is None
