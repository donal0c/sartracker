# -*- coding: utf-8 -*-
"""
Source-level wiring tests for breadcrumb accumulator reset.

Ensures sartracker.py connects mission state changes to ProviderController
so per-mission accumulator resets occur.
"""
import os


def _read_sartracker_source() -> str:
    root = os.path.dirname(os.path.dirname(__file__))
    sartracker_path = os.path.join(root, 'sartracker.py')
    with open(sartracker_path, 'r') as f:
        return f.read()


def test_sartracker_wires_provider_mission_state_handler():
    source = _read_sartracker_source()
    assert "provider_controller._on_mission_state_changed" in source
