# -*- coding: utf-8 -*-
"""Regression tests for clue-specific marker controller fields."""

from unittest.mock import MagicMock


def test_create_clue_forwards_found_by_to_layers_controller():
    from sartracker.controllers.marker_controller import MarkerController

    iface = MagicMock()
    layers_controller = MagicMock()
    layers_controller.add_clue.return_value = "clue-123"

    controller = MarkerController(
        iface=iface,
        layers_controller=layers_controller,
        ingest_attachment=lambda path: path,
    )

    marker_id, label = controller._create_marker(
        {
            "type": "clue",
            "name": "Boot Print",
            "lat": 52.274681,
            "lon": -9.530912,
            "clue_type": "Footprint",
            "confidence": "Confirmed",
            "description": "Fresh track in bog",
            "found_by": "Team Charlie",
            "easting": 95553,
            "northing": 114716,
        }
    )

    assert marker_id == "clue-123"
    assert label == "Clue"
    layers_controller.add_clue.assert_called_once()
    assert layers_controller.add_clue.call_args.kwargs["found_by"] == "Team Charlie"
