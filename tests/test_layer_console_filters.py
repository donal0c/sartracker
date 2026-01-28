# -*- coding: utf-8 -*-
"""Tests for Layer Console type filtering with per-device tracking layers."""

from sartracker.ui.layer_console_widget import layer_matches_type_filter


def test_positions_filter_accepts_device_position_layer_type():
    layer = {
        "id": "custom_layer_id",
        "layer_type": "device_position",
        "display_name": "Alpha Team",
    }
    assert layer_matches_type_filter(layer, "positions") is True


def test_breadcrumbs_filter_accepts_device_trail_layer_type():
    layer = {
        "id": "custom_layer_id",
        "layer_type": "device_trail",
        "display_name": "Alpha Team",
    }
    assert layer_matches_type_filter(layer, "breadcrumbs") is True
