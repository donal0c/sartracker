# -*- coding: utf-8 -*-
"""
QGIS integration test for layer tree → map canvas synchronization.
"""
import pytest

pytestmark = pytest.mark.qgis_required


def test_refresh_layer_tree_view_syncs_canvas_layers(sar_qgis_project, sar_iface):
    from qgis.core import QgsProject, QgsVectorLayer
    from sartracker.layers.utilities import refresh_layer_tree_view

    project = QgsProject.instance()
    root = project.layerTreeRoot()

    if not hasattr(root, "checkedLayers"):
        pytest.skip("QGIS layer tree does not support checkedLayers()")

    group = root.addGroup("SAR Tracker")
    layer = QgsVectorLayer("Point?crs=EPSG:4326", "Position", "memory")
    assert layer.isValid()

    project.addMapLayer(layer, False)
    group.addLayer(layer)

    node = root.findLayer(layer.id())
    assert node is not None
    node.setItemVisibilityChecked(True)

    canvas = sar_iface.mapCanvas()
    canvas.setLayers([])
    assert layer not in canvas.layers()

    assert refresh_layer_tree_view(sar_iface) is True
    assert layer in canvas.layers()
