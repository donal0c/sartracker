# -*- coding: utf-8 -*-
"""UI smoke tests for marker-specific details in Marker Log."""
import os


def _read_marker_log_source() -> str:
    root = os.path.dirname(os.path.dirname(__file__))
    widget_path = os.path.join(root, "ui", "marker_log_widget.py")
    with open(widget_path, "r", encoding="utf-8") as handle:
        return handle.read()


def test_marker_log_casualty_details_include_triage_labels():
    source = _read_marker_log_source()
    assert "Condition:" in source
    assert "Treatment:" in source
    assert "Evacuation Priority:" in source
    assert "Found By:" in source


def test_marker_log_clue_details_include_metadata_labels():
    source = _read_marker_log_source()
    assert "Clue Type:" in source
    assert "Confidence:" in source
