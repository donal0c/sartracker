# -*- coding: utf-8 -*-
"""
Unit tests for layer tree utilities.
"""
import pytest
from unittest.mock import MagicMock

from sartracker.layers.utilities import refresh_layer_tree_view


pytestmark = pytest.mark.mock_qgis_only


def test_refresh_layer_tree_view_no_view_returns_false():
    iface = MagicMock()
    iface.layerTreeView.return_value = None
    iface.mapCanvas.return_value = None

    assert refresh_layer_tree_view(iface) is False


def test_refresh_layer_tree_view_emits_layout_changed_and_updates():
    iface = MagicMock()
    view = MagicMock()
    model = MagicMock()
    view.model.return_value = model
    iface.layerTreeView.return_value = view
    canvas = MagicMock()
    iface.mapCanvas.return_value = canvas

    from qgis.core import QgsProject
    project = MagicMock()
    root = MagicMock()
    root.checkedLayers.return_value = ["layer-a", "layer-b"]
    project.layerTreeRoot.return_value = root
    QgsProject.instance.return_value = project

    assert refresh_layer_tree_view(iface) is True
    canvas.setLayers.assert_called_once_with(root.checkedLayers.return_value)
    canvas.refresh.assert_called_once()
    model.layoutChanged.emit.assert_called_once()
    view.viewport().update.assert_called_once()
