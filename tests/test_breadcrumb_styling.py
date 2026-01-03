# -*- coding: utf-8 -*-
"""QGIS styling tests for breadcrumb trail defaults."""

import pytest

from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtGui import QColor
from qgis.core import (
    QgsCategorizedSymbolRenderer,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsPointXY,
    QgsVectorLayer,
)

from sartracker.controllers.layer_managers.tracking_manager import TrackingLayerManager


pytestmark = pytest.mark.qgis_required


def _line_style(symbol):
    return symbol.symbolLayer(0).properties().get("line_style")


def _make_breadcrumb_layer():
    layer = QgsVectorLayer("LineString?crs=EPSG:4326", "Breadcrumbs", "memory")
    provider = layer.dataProvider()
    provider.addAttributes([
        QgsField("device_id", QVariant.String),
        QgsField("name", QVariant.String),
        QgsField("timestamp", QVariant.String),
    ])
    layer.updateFields()

    features = []
    for idx in range(2):
        feature = QgsFeature(layer.fields())
        feature.setAttribute("device_id", f"dev{idx}")
        feature.setAttribute("name", f"Dev {idx}")
        feature.setAttribute("timestamp", "2024-01-01T00:00:00Z")
        feature.setGeometry(
            QgsGeometry.fromPolylineXY([
                QgsPointXY(-9.0 + idx * 0.01, 52.0),
                QgsPointXY(-9.01 + idx * 0.01, 52.01),
            ])
        )
        features.append(feature)

    provider.addFeatures(features)
    layer.updateExtents()
    return layer


def test_per_device_trail_defaults_to_dash(sar_iface, sar_qgis_project):
    manager = TrackingLayerManager(sar_iface)
    layer = QgsVectorLayer("LineString?crs=EPSG:4326", "Trail", "memory")

    manager._apply_device_trail_style(layer, QColor("#ff0000"))

    renderer = layer.renderer()
    assert renderer is not None
    assert _line_style(renderer.symbol()) == "dash"


def test_shared_breadcrumbs_default_to_dash(sar_iface, sar_qgis_project):
    manager = TrackingLayerManager(sar_iface)
    layer = _make_breadcrumb_layer()

    manager._apply_breadcrumbs_style(layer)

    renderer = layer.renderer()
    assert isinstance(renderer, QgsCategorizedSymbolRenderer)
    for category in renderer.categories():
        assert _line_style(category.symbol()) == "dash"
