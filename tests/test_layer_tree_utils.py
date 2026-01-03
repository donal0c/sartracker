# -*- coding: utf-8 -*-
"""
Unit tests for layer tree utilities.
"""
from unittest.mock import MagicMock

from sartracker.layers.utilities import refresh_layer_tree_view


def test_refresh_layer_tree_view_no_view_returns_false():
    iface = MagicMock()
    iface.layerTreeView.return_value = None

    assert refresh_layer_tree_view(iface) is False


def test_refresh_layer_tree_view_emits_layout_changed_and_updates():
    iface = MagicMock()
    view = MagicMock()
    model = MagicMock()
    view.model.return_value = model
    iface.layerTreeView.return_value = view

    assert refresh_layer_tree_view(iface) is True
    model.layoutChanged.emit.assert_called_once()
    view.viewport().update.assert_called_once()
