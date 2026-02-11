# -*- coding: utf-8 -*-
"""
Tests for auto-refresh watchdog logic.

TDD: Tests written BEFORE implementation (SAR-REFRESH-WATCHDOG)
"""
from sartracker.ui.sar_panel import should_restart_auto_refresh_timer
from sartracker.controllers.mission_controller import MissionState


def test_restart_when_enabled_active_not_paused_and_timer_stopped():
    assert should_restart_auto_refresh_timer(
        auto_refresh_enabled=True,
        is_active=True,
        mission_state=MissionState.ACTIVE,
        timer_active=False,
    ) is True


def test_no_restart_when_disabled():
    assert should_restart_auto_refresh_timer(
        auto_refresh_enabled=False,
        is_active=True,
        mission_state=MissionState.ACTIVE,
        timer_active=False,
    ) is False


def test_no_restart_when_inactive():
    assert should_restart_auto_refresh_timer(
        auto_refresh_enabled=True,
        is_active=False,
        mission_state=MissionState.ACTIVE,
        timer_active=False,
    ) is False


def test_no_restart_when_paused():
    assert should_restart_auto_refresh_timer(
        auto_refresh_enabled=True,
        is_active=True,
        mission_state=MissionState.PAUSED,
        timer_active=False,
    ) is False


def test_no_restart_when_timer_running():
    assert should_restart_auto_refresh_timer(
        auto_refresh_enabled=True,
        is_active=True,
        mission_state=MissionState.ACTIVE,
        timer_active=True,
    ) is False
