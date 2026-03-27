# -*- coding: utf-8 -*-
"""Unit tests for per-item layer tree visibility behavior."""

from unittest.mock import MagicMock

import pytest


pytestmark = pytest.mark.mock_qgis_only


def test_add_layer_to_project_marks_new_tree_node_visible(monkeypatch):
    from sartracker.controllers.per_item_layer_factory import PerItemLayerFactory
    from sartracker.controllers import per_item_layer_factory as factory_module

    layer = MagicMock()
    layer.id.return_value = "layer-123"

    node = MagicMock()
    root = MagicMock()
    root.findLayer.return_value = node

    target_group = MagicMock()
    project = MagicMock()
    project.layerTreeRoot.return_value = root

    monkeypatch.setattr(factory_module.QgsProject, "instance", MagicMock(return_value=project))

    factory = PerItemLayerFactory.__new__(PerItemLayerFactory)

    PerItemLayerFactory._add_layer_to_project(factory, layer, target_group=target_group)

    project.addMapLayer.assert_called_once_with(layer, False)
    target_group.addLayer.assert_called_once_with(layer)
    root.findLayer.assert_called_once_with("layer-123")
    node.setItemVisibilityChecked.assert_called_once_with(True)
