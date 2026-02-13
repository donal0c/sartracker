# -*- coding: utf-8 -*-
"""Tests for coordinate display mode settings."""

from sartracker.config.keys import ConfigStore, SETTINGS_KEYS


def test_coordinate_display_mode_defaults_to_latlon_first():
    ConfigStore.remove(SETTINGS_KEYS.COORDINATE_DISPLAY_MODE)
    assert ConfigStore.get_coordinate_display_mode() == SETTINGS_KEYS.COORDINATE_DISPLAY_MODE_LATLON_FIRST


def test_coordinate_display_mode_round_trip_tm65_first():
    ConfigStore.set_coordinate_display_mode(SETTINGS_KEYS.COORDINATE_DISPLAY_MODE_TM65_FIRST)
    assert ConfigStore.get_coordinate_display_mode() == SETTINGS_KEYS.COORDINATE_DISPLAY_MODE_TM65_FIRST


def test_coordinate_display_mode_invalid_value_falls_back_to_default():
    ConfigStore.set(SETTINGS_KEYS.COORDINATE_DISPLAY_MODE, "unexpected_mode")
    assert ConfigStore.get_coordinate_display_mode() == SETTINGS_KEYS.COORDINATE_DISPLAY_MODE_LATLON_FIRST
