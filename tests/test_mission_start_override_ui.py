# -*- coding: utf-8 -*-
"""
UI smoke tests for mission start override controls.

These tests read the SAR panel source to confirm the back-date input
exists in the mission controls section.
"""
import os


def _read_sar_panel_source() -> str:
    root = os.path.dirname(os.path.dirname(__file__))
    sar_panel_path = os.path.join(root, 'ui', 'sar_panel.py')
    with open(sar_panel_path, 'r') as f:
        return f.read()


def test_sar_panel_has_mission_start_offset_spinbox():
    source = _read_sar_panel_source()
    assert "mission_start_offset_spin" in source
    assert "Start offset" in source


def test_sar_panel_mission_start_offset_limits():
    source = _read_sar_panel_source()
    assert "setRange(0, 5)" in source
    assert "setSuffix(\"h\")" in source
