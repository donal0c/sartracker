# -*- coding: utf-8 -*-
"""ConfigStore tests for replay/test window settings."""
from sartracker.config.keys import ConfigStore, SETTINGS_KEYS


def test_replay_defaults():
    assert ConfigStore.get_traccar_test_window_enabled() is False
    assert ConfigStore.get_traccar_test_window_start() == ""
    assert ConfigStore.get_traccar_test_window_hours() == 3


def test_replay_settings_round_trip():
    ConfigStore.set_traccar_test_window_enabled(True)
    ConfigStore.set_traccar_test_window_start("2026-01-05T08:00:00Z")
    ConfigStore.set_traccar_test_window_hours(12)

    assert ConfigStore.get_traccar_test_window_enabled() is True
    assert ConfigStore.get_traccar_test_window_start() == "2026-01-05T08:00:00Z"
    assert ConfigStore.get_traccar_test_window_hours() == 12


def test_replay_settings_remove_resets():
    ConfigStore.set_traccar_test_window_enabled(True)
    ConfigStore.set_traccar_test_window_start("2026-01-05T08:00:00Z")
    ConfigStore.set_traccar_test_window_hours(12)

    ConfigStore.remove(SETTINGS_KEYS.PROVIDER_TRACCAR_TEST_WINDOW_ENABLED)
    ConfigStore.remove(SETTINGS_KEYS.PROVIDER_TRACCAR_TEST_WINDOW_START)
    ConfigStore.remove(SETTINGS_KEYS.PROVIDER_TRACCAR_TEST_WINDOW_HOURS)

    assert ConfigStore.get_traccar_test_window_enabled() is False
    assert ConfigStore.get_traccar_test_window_start() == ""
    assert ConfigStore.get_traccar_test_window_hours() == 3
