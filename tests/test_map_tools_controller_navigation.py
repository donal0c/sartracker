# -*- coding: utf-8 -*-
"""Regression tests for coordinate-converter map targeting."""

from unittest.mock import MagicMock


class _FakePoint:
    def __init__(self, x, y):
        self._x = float(x)
        self._y = float(y)

    def x(self):
        return self._x

    def y(self):
        return self._y


class _FakeCrs:
    def __init__(self, authid="EPSG:4326", geographic=False):
        self._authid = authid
        self._geographic = geographic

    def authid(self):
        return self._authid

    def isGeographic(self):
        return self._geographic


def _build_controller(monkeypatch, geographic=False):
    from sartracker.controllers import map_tools_controller as controller_module
    from sartracker.controllers.map_tools_controller import MapToolsController

    monkeypatch.setattr(controller_module, "QgsPointXY", _FakePoint)
    monkeypatch.setattr(controller_module, "QgsRectangle", lambda *args: args)

    canvas = MagicMock()
    canvas.mapSettings.return_value.destinationCrs.return_value = _FakeCrs(
        authid="EPSG:4326",
        geographic=geographic,
    )

    iface = MagicMock()
    iface.mapCanvas.return_value = canvas
    iface.messageBar.return_value = MagicMock()

    controller = MapToolsController(iface=iface)
    return controller_module, controller, canvas


def test_zoom_to_location_shows_temporary_target(monkeypatch):
    controller_module, controller, canvas = _build_controller(monkeypatch)
    shown_points = []

    monkeypatch.setattr(controller, "_show_location_target", lambda point: shown_points.append(point))

    controller._zoom_to_location(52.274681, -9.530912)

    canvas.setExtent.assert_called_once()
    canvas.refresh.assert_called_once()
    assert len(shown_points) == 1
    assert shown_points[0].x() == -9.530912
    assert shown_points[0].y() == 52.274681


def test_show_location_target_replaces_existing_marker_and_schedules_clear(monkeypatch):
    controller_module, controller, canvas = _build_controller(monkeypatch)
    existing_marker = object()
    controller._location_target_marker = existing_marker
    created_marker = object()
    scheduled = []

    monkeypatch.setattr(
        controller,
        "_build_location_target_marker",
        lambda target_canvas, point: created_marker,
    )
    monkeypatch.setattr(
        controller_module.QTimer,
        "singleShot",
        lambda delay_ms, callback: scheduled.append((delay_ms, callback)),
        raising=False,
    )

    controller._show_location_target(_FakePoint(-9.530912, 52.274681))

    canvas.scene.return_value.removeItem.assert_called_once_with(existing_marker)
    assert controller._location_target_marker is created_marker
    assert scheduled
    assert scheduled[0][0] == 60000
    assert scheduled[0][1] == controller._clear_location_target


def test_cleanup_clears_location_target(monkeypatch):
    _controller_module, controller, canvas = _build_controller(monkeypatch)
    marker = object()
    controller._location_target_marker = marker

    controller.cleanup("test cleanup")

    canvas.scene.return_value.removeItem.assert_called_once_with(marker)
    assert controller._location_target_marker is None
