# -*- coding: utf-8 -*-
"""Source-level checks for replay UI controls in SettingsPanel."""
import os


def _read_settings_panel_source() -> str:
    root = os.path.dirname(os.path.dirname(__file__))
    panel_path = os.path.join(root, 'ui', 'settings_panel.py')
    with open(panel_path, 'r') as f:
        return f.read()


def test_settings_panel_has_replay_controls():
    source = _read_settings_panel_source()
    assert "Replay / Testing Window" in source
    assert "replay_enable_check" in source
    assert "replay_start_edit" in source
    assert "replay_window_hours_spin" in source


def test_settings_panel_replay_defaults():
    source = _read_settings_panel_source()
    assert "PROVIDER_TRACCAR_TEST_WINDOW_HOURS_DEFAULT" in source
    assert "setMaximum(24)" in source
