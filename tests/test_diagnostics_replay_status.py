# -*- coding: utf-8 -*-
"""Source-level checks for replay diagnostics fields."""
import os


def _read_diagnostics_service_source() -> str:
    root = os.path.dirname(os.path.dirname(__file__))
    path = os.path.join(root, 'services', 'diagnostics_service.py')
    with open(path, 'r') as f:
        return f.read()


def test_diagnostics_includes_replay_fields():
    source = _read_diagnostics_service_source()
    assert "replay_window_enabled" in source
    assert "replay_window_start" in source
    assert "replay_window_hours" in source
