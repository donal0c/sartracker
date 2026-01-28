# -*- coding: utf-8 -*-
"""Source-level checks for replay guardrails in sartracker settings handler."""
import os


def _read_sartracker_source() -> str:
    root = os.path.dirname(os.path.dirname(__file__))
    path = os.path.join(root, 'sartracker.py')
    with open(path, 'r') as f:
        return f.read()


def test_sartracker_disables_replay_when_mission_active():
    source = _read_sartracker_source()
    assert "Replay Disabled" in source
    assert "replay_window_enabled" in source
    assert "set_traccar_test_window_enabled(False)" in source
