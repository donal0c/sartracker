# -*- coding: utf-8 -*-
"""
Unit tests for per-device item ID selection and rebuild logic.
"""
import re
from unittest.mock import MagicMock

from sartracker.controllers.layer_managers.tracking_manager import TrackingLayerManager


def test_candidate_device_item_ids_are_safe_and_stable():
    legacy, safe = TrackingLayerManager._candidate_device_item_ids("pos", "team alpha/1")

    assert legacy == "pos_team alpha/1"
    assert safe.startswith("pos_")
    assert re.match(r"^pos_[0-9a-f]{32}$", safe)


def test_get_or_rebuild_device_layer_prefers_loaded_layer():
    factory = MagicMock()
    layer = MagicMock()
    layer.isValid.return_value = True
    factory.get_layer_by_item_id.return_value = layer

    result = TrackingLayerManager._get_or_rebuild_device_layer(factory, "pos_x", MagicMock())

    assert result == layer
    factory.rebuild_missing_layer.assert_not_called()


def test_get_or_rebuild_device_layer_rebuilds_missing_layer():
    factory = MagicMock()
    factory.get_layer_by_item_id.return_value = None
    rebuilt = MagicMock()
    factory.rebuild_missing_layer.return_value = rebuilt

    result = TrackingLayerManager._get_or_rebuild_device_layer(factory, "pos_x", MagicMock())

    assert result == rebuilt
    factory.rebuild_missing_layer.assert_called_once()
