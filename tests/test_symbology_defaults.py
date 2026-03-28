# -*- coding: utf-8 -*-
"""QGIS styling tests for marker and line defaults."""

import pytest

from qgis.PyQt.QtGui import QColor
from qgis.core import QgsVectorLayer

from sartracker.controllers.layer_managers.drawing_manager import DrawingLayerManager
from sartracker.controllers.layer_managers.marker_manager import MarkerLayerManager


pytestmark = pytest.mark.qgis_required


def _make_point_layer(name: str = "Markers") -> QgsVectorLayer:
    return QgsVectorLayer("Point?crs=EPSG:4326", name, "memory")


def _make_line_layer(name: str = "Lines") -> QgsVectorLayer:
    return QgsVectorLayer("LineString?crs=EPSG:4326", name, "memory")


def _make_polygon_layer(name: str = "Polygons") -> QgsVectorLayer:
    return QgsVectorLayer("Polygon?crs=EPSG:4326", name, "memory")


def _marker_symbol(layer: QgsVectorLayer):
    renderer = layer.renderer()
    assert renderer is not None
    symbol = renderer.symbol()
    assert symbol is not None
    return symbol


def _property_color_name(props, *keys: str) -> str:
    for key in keys:
        value = props.get(key)
        if value:
            red, green, blue = (int(channel) for channel in value.split(",")[:3])
            return QColor(red, green, blue).name()
    raise AssertionError(f"Expected one of {keys} in symbol properties: {props}")


def test_clues_symbol_defaults(sar_iface, sar_qgis_project):
    manager = MarkerLayerManager(sar_iface)
    layer = _make_point_layer("Clues")

    manager._style_clues_layer(layer)

    symbol = _marker_symbol(layer)
    props = symbol.symbolLayer(0).properties()
    assert props.get("name") == "circle"
    assert symbol.size() == pytest.approx(10.0, abs=0.01)
    assert symbol.color().name() == QColor("#ffffff").name()


def test_hazards_symbol_defaults(sar_iface, sar_qgis_project):
    manager = MarkerLayerManager(sar_iface)
    layer = _make_point_layer("Hazards")

    manager._style_hazards_layer(layer)

    symbol = _marker_symbol(layer)
    props = symbol.symbolLayer(0).properties()
    assert props.get("name") == "filled_arrowhead"
    assert symbol.size() == pytest.approx(12.0, abs=0.01)
    assert symbol.color().name() == QColor("#ff0000").name()


def test_casualties_symbol_defaults(sar_iface, sar_qgis_project):
    manager = MarkerLayerManager(sar_iface)
    layer = _make_point_layer("Casualties")

    manager._style_casualties_layer(layer)

    symbol = _marker_symbol(layer)
    props = symbol.symbolLayer(0).properties()
    assert props.get("name") == "star"
    assert symbol.size() == pytest.approx(16.0, abs=0.01)
    assert _property_color_name(props, "color") == QColor("#ff0000").name()


def test_line_symbol_defaults(sar_iface, sar_qgis_project):
    manager = DrawingLayerManager(sar_iface)
    layer = _make_line_layer("Lines")

    manager._style_lines_layer(layer)

    renderer = layer.renderer()
    assert renderer is not None
    symbol = renderer.symbol()
    assert symbol is not None
    props = symbol.symbolLayer(0).properties()
    assert float(props.get("line_width") or props.get("width")) == pytest.approx(0.7, abs=0.01)
    assert _property_color_name(props, "line_color", "color") == QColor("#ff0000").name()


def test_range_rings_symbol_defaults(sar_iface, sar_qgis_project):
    manager = DrawingLayerManager(sar_iface)
    layer = _make_polygon_layer("Range Rings")

    manager._style_range_rings_layer(layer)

    renderer = layer.renderer()
    assert renderer is not None
    symbol = renderer.symbol()
    assert symbol is not None
    assert symbol.symbolLayerCount() == 3

    pattern_marker = symbol.symbolLayer(1).subSymbol().symbolLayer(0)
    pattern_props = pattern_marker.properties()
    outline_props = symbol.symbolLayer(2).properties()

    assert _property_color_name(pattern_props, "color") == QColor("#000000").name()
    assert float(outline_props.get("line_width") or outline_props.get("width")) == pytest.approx(2.0, abs=0.01)
    assert _property_color_name(outline_props, "line_color", "color") == QColor("#ff8c00").name()
    assert layer.opacity() == pytest.approx(1.0, abs=0.01)
