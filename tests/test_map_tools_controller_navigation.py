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


def test_add_marker_by_grid_reference_uses_existing_marker_flow(monkeypatch):
    _controller_module, controller, _canvas = _build_controller(monkeypatch)
    controller.tool_registry = MagicMock()
    controller.marker_controller = MagicMock()
    controller.marker_placed = MagicMock()

    dialog = MagicMock()
    dialog.get_marker_request.return_value = ("clue", "Q 99840 04018")

    monkeypatch.setattr(
        controller,
        "_create_marker_grid_dialog",
        lambda: dialog,
    )
    monkeypatch.setattr(
        "sartracker.controllers.map_tools_controller.dialog_exec",
        lambda _dialog: _controller_module.DialogAccepted,
    )
    monkeypatch.setattr(
        controller,
        "_convert_grid_reference_marker_coordinates",
        lambda _grid_ref: (52.274681, -9.530912, 95553.0, 114716.0),
    )

    controller.on_add_marker_by_grid_requested()

    controller.tool_registry.deactivate_current.assert_called_once()
    controller.marker_controller.handle_new_marker.assert_called_once_with(
        "clue",
        52.274681,
        -9.530912,
        95553.0,
        114716.0,
    )
    controller.marker_placed.emit.assert_called_once_with()


def test_add_marker_by_grid_reference_rejects_invalid_grid_reference(monkeypatch):
    controller_module, controller, _canvas = _build_controller(monkeypatch)
    controller.marker_controller = MagicMock()

    messages = []
    dialog = MagicMock()
    dialog.get_marker_request.return_value = ("hazard", "bad ref")

    monkeypatch.setattr(
        controller,
        "_create_marker_grid_dialog",
        lambda: dialog,
    )
    monkeypatch.setattr(
        controller_module,
        "dialog_exec",
        lambda _dialog: controller_module.DialogAccepted,
    )
    monkeypatch.setattr(
        controller,
        "_convert_grid_reference_marker_coordinates",
        lambda _grid_ref: (_ for _ in ()).throw(ValueError("Invalid Irish Grid reference")),
    )
    monkeypatch.setattr(
        controller_module,
        "warning",
        lambda _bar, title, message, duration=0: messages.append((title, message, duration)),
    )

    controller.on_add_marker_by_grid_requested()

    controller.marker_controller.handle_new_marker.assert_not_called()
    assert messages == [
        ("Marker at GR", "Invalid Irish Grid reference", 5),
    ]


def test_convert_grid_reference_marker_coordinates_converts_tm65_to_wgs84_and_itm(monkeypatch):
    controller_module, controller, _canvas = _build_controller(monkeypatch)
    fake_tm65 = MagicMock()
    fake_tm65.isValid.return_value = True
    transform_calls = []

    class _FakeTransform:
        def __init__(self, source_crs, dest_crs, _project):
            transform_calls.append((source_crs, dest_crs))
            self._is_wgs84 = len(transform_calls) == 1

        def transform(self, _point):
            if self._is_wgs84:
                return _FakePoint(-9.530912, 52.274681)
            return _FakePoint(95553.0, 114716.0)

    monkeypatch.setattr(controller_module, "build_tm65_crs", lambda: fake_tm65)
    monkeypatch.setattr(
        controller_module,
        "parse_irish_grid_reference",
        lambda grid_ref: (99840, 104018) if grid_ref == "Q 99840 04018" else None,
    )
    monkeypatch.setattr(controller_module, "QgsCoordinateTransform", _FakeTransform)

    lat, lon, easting, northing = controller._convert_grid_reference_marker_coordinates(
        "Q 99840 04018"
    )

    assert (lat, lon, easting, northing) == (52.274681, -9.530912, 95553.0, 114716.0)
    assert transform_calls == [
        (fake_tm65, controller.wgs84),
        (fake_tm65, controller.itm),
    ]


def test_convert_grid_reference_marker_coordinates_rejects_missing_tm65_crs(monkeypatch):
    controller_module, controller, _canvas = _build_controller(monkeypatch)

    monkeypatch.setattr(controller_module, "build_tm65_crs", lambda: None)

    try:
        controller._convert_grid_reference_marker_coordinates("Q 99840 04018")
    except ValueError as exc:
        assert str(exc) == "TM65 coordinate system is unavailable in this QGIS build."
    else:
        raise AssertionError("Expected ValueError for unavailable TM65 CRS")
