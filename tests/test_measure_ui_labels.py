# -*- coding: utf-8 -*-
"""
UI smoke tests for measurement control labels.
"""
import os


def _read_sar_panel_source() -> str:
    root = os.path.dirname(os.path.dirname(__file__))
    sar_panel_path = os.path.join(root, "ui", "sar_panel.py")
    with open(sar_panel_path, "r", encoding="utf-8") as handle:
        return handle.read()


def test_sar_panel_measure_button_mentions_bearing():
    source = _read_sar_panel_source()
    assert 'QPushButton("Measure Distance & Bearing")' in source
