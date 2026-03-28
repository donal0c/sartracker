# -*- coding: utf-8 -*-
"""
Unit tests for ProviderController refresh filtering behavior.

These tests run without a QGIS runtime using mocked interfaces.
"""
import pytest
from unittest.mock import MagicMock, patch

from sartracker.controllers.provider_controller import ProviderController
from sartracker.config.keys import ConfigStore
from sartracker.utils.timeparse import parse_iso, format_iso
from datetime import datetime, timezone, timedelta


@pytest.fixture(autouse=True)
def _reset_replay_settings():
    """Keep replay-window config from leaking between branch-matrix tests."""
    ConfigStore.set_traccar_test_window_enabled(False)
    ConfigStore.set_traccar_test_window_start("")
    ConfigStore.set_traccar_test_window_hours(3)
    yield
    ConfigStore.set_traccar_test_window_enabled(False)
    ConfigStore.set_traccar_test_window_start("")
    ConfigStore.set_traccar_test_window_hours(3)


def _build_controller(provider_name: str):
    iface = MagicMock()
    iface.messageBar.return_value = MagicMock()
    task_manager = MagicMock()
    task_manager.is_shutting_down.return_value = False

    controller = ProviderController(
        iface=iface,
        task_manager=task_manager,
        parent=None
    )

    provider = MagicMock()
    provider.create_refresh_task.return_value = MagicMock()

    controller.provider = provider
    controller.provider_name = provider_name
    return controller, provider, task_manager


def test_start_refresh_uses_mission_start_for_traccar():
    controller, provider, task_manager = _build_controller('traccar_http')
    controller.set_mission_start_getter(lambda: "2026-01-03T10:14:18Z")

    started = controller.start_refresh()

    assert started is True
    provider.create_refresh_task.assert_called_once()
    assert provider.create_refresh_task.call_args.kwargs.get('since_iso') == "2026-01-03T10:14:18Z"


def test_start_refresh_passes_until_iso_when_provided():
    controller, provider, task_manager = _build_controller('traccar_http')

    started = controller.start_refresh(
        since_iso="2026-01-03T10:14:18Z",
        until_iso="2026-01-03T12:14:18Z"
    )

    assert started is True
    provider.create_refresh_task.assert_called_once()
    assert provider.create_refresh_task.call_args.kwargs.get('since_iso') == "2026-01-03T10:14:18Z"
    assert provider.create_refresh_task.call_args.kwargs.get('until_iso') == "2026-01-03T12:14:18Z"


def test_replay_window_used_when_enabled_and_no_active_mission():
    controller, provider, task_manager = _build_controller('traccar_http')
    controller.set_mission_active_getter(lambda: False)

    start_iso = format_iso(datetime.now(timezone.utc) - timedelta(hours=4))
    ConfigStore.set_traccar_test_window_enabled(True)
    ConfigStore.set_traccar_test_window_start(start_iso)
    ConfigStore.set_traccar_test_window_hours(3)

    started = controller.start_refresh()

    assert started is True
    provider.create_refresh_task.assert_called_once()
    kwargs = provider.create_refresh_task.call_args.kwargs
    assert kwargs.get('since_iso') == format_iso(parse_iso(start_iso))
    expected_until = format_iso(parse_iso(start_iso) + timedelta(hours=3))
    assert kwargs.get('until_iso') == expected_until


def test_replay_missing_start_disables_replay_and_blocks_refresh():
    controller, provider, task_manager = _build_controller('traccar_http')
    controller.set_mission_active_getter(lambda: False)

    ConfigStore.set_traccar_test_window_enabled(True)
    ConfigStore.set_traccar_test_window_start("")
    ConfigStore.set_traccar_test_window_hours(3)

    started = controller.start_refresh()

    assert started is False
    assert ConfigStore.get_traccar_test_window_enabled() is False
    provider.create_refresh_task.assert_not_called()


def test_replay_disabled_when_mission_active():
    controller, provider, task_manager = _build_controller('traccar_http')
    controller.set_mission_active_getter(lambda: True)
    controller.set_mission_start_getter(lambda: "2026-01-03T10:14:18Z")

    ConfigStore.set_traccar_test_window_enabled(True)
    ConfigStore.set_traccar_test_window_start("2026-01-04T08:00:00Z")
    ConfigStore.set_traccar_test_window_hours(3)

    started = controller.start_refresh()

    assert started is True
    assert ConfigStore.get_traccar_test_window_enabled() is False
    kwargs = provider.create_refresh_task.call_args.kwargs
    assert kwargs.get('since_iso') == "2026-01-03T10:14:18Z"
    assert kwargs.get('until_iso') is None


def test_replay_start_future_blocks_refresh():
    controller, provider, task_manager = _build_controller('traccar_http')
    controller.set_mission_active_getter(lambda: False)

    ConfigStore.set_traccar_test_window_enabled(True)
    ConfigStore.set_traccar_test_window_start("2999-01-01T00:00:00Z")
    ConfigStore.set_traccar_test_window_hours(3)

    started = controller.start_refresh()

    assert started is False
    provider.create_refresh_task.assert_not_called()


def test_replay_hours_out_of_range_blocks_refresh():
    controller, provider, task_manager = _build_controller('traccar_http')
    controller.set_mission_active_getter(lambda: False)

    ConfigStore.set_traccar_test_window_enabled(True)
    ConfigStore.set_traccar_test_window_start("2026-01-04T08:00:00Z")
    ConfigStore.set_traccar_test_window_hours(0)

    started = controller.start_refresh()

    assert started is False
    provider.create_refresh_task.assert_not_called()


def test_invalid_replay_window_emits_disabled_signal():
    controller, provider, task_manager = _build_controller('traccar_http')
    controller.set_mission_active_getter(lambda: False)

    signals = []
    controller.replay_mode_changed.connect(
        lambda enabled, start, end: signals.append((enabled, start, end))
    )

    ConfigStore.set_traccar_test_window_enabled(True)
    ConfigStore.set_traccar_test_window_start("2999-01-01T00:00:00Z")
    ConfigStore.set_traccar_test_window_hours(3)

    started = controller.start_refresh()

    assert started is False
    assert ConfigStore.get_traccar_test_window_enabled() is False
    provider.create_refresh_task.assert_not_called()
    assert signals[-1] == (False, "", "")


def test_invalid_replay_window_cleans_up_temp_store():
    controller, provider, task_manager = _build_controller('traccar_http')
    controller.set_mission_active_getter(lambda: False)

    temp_store_path = {'value': None}
    cleared = []

    def set_temp_store(path):
        temp_store_path['value'] = path

    def clear_temp_store():
        cleared.append(temp_store_path['value'])
        temp_store_path['value'] = None

    def get_temp_store():
        return temp_store_path['value']

    controller.set_temp_store_handlers(
        setter=set_temp_store,
        clearer=clear_temp_store,
        getter=get_temp_store,
    )

    ConfigStore.set_traccar_test_window_enabled(True)
    ConfigStore.set_traccar_test_window_start("2999-01-01T00:00:00Z")
    ConfigStore.set_traccar_test_window_hours(3)

    with patch(
        'sartracker.utils.mission_storage.MissionStorageHelper.prepare_temp_replay_store',
        return_value='/tmp/replay-invalid.gpkg',
    ):
        started = controller.start_refresh()

    assert started is False
    assert ConfigStore.get_traccar_test_window_enabled() is False
    provider.create_refresh_task.assert_not_called()
    assert cleared == ['/tmp/replay-invalid.gpkg']
    assert temp_store_path['value'] is None


def test_replay_setup_failure_cleans_up_temp_store_and_clears_signal():
    controller, provider, task_manager = _build_controller('traccar_http')
    controller.set_mission_active_getter(lambda: False)

    temp_store_path = {'value': None}
    cleared = []
    signals = []

    def set_temp_store(path):
        temp_store_path['value'] = path

    def clear_temp_store():
        cleared.append(temp_store_path['value'])
        temp_store_path['value'] = None

    def get_temp_store():
        return temp_store_path['value']

    controller.set_temp_store_handlers(
        setter=set_temp_store,
        clearer=clear_temp_store,
        getter=get_temp_store,
    )
    controller.replay_mode_changed.connect(
        lambda enabled, start, end: signals.append((enabled, start, end))
    )

    start_iso = format_iso(datetime.now(timezone.utc) - timedelta(hours=2))
    ConfigStore.set_traccar_test_window_enabled(True)
    ConfigStore.set_traccar_test_window_start(start_iso)
    ConfigStore.set_traccar_test_window_hours(1)

    provider.create_refresh_task.side_effect = RuntimeError("task setup failed")

    with patch(
        'sartracker.utils.mission_storage.MissionStorageHelper.prepare_temp_replay_store',
        return_value='/tmp/replay-setup-failed.gpkg',
    ):
        started = controller.start_refresh()

    assert started is False
    assert ConfigStore.get_traccar_test_window_enabled() is True
    assert cleared == ['/tmp/replay-setup-failed.gpkg']
    assert temp_store_path['value'] is None
    assert signals[0][0] is True
    assert signals[-1] == (False, "", "")


def test_replay_task_start_failure_cleans_up_temp_store_and_clears_signal():
    controller, provider, task_manager = _build_controller('traccar_http')
    controller.set_mission_active_getter(lambda: False)

    temp_store_path = {'value': None}
    cleared = []
    signals = []

    def set_temp_store(path):
        temp_store_path['value'] = path

    def clear_temp_store():
        cleared.append(temp_store_path['value'])
        temp_store_path['value'] = None

    def get_temp_store():
        return temp_store_path['value']

    controller.set_temp_store_handlers(
        setter=set_temp_store,
        clearer=clear_temp_store,
        getter=get_temp_store,
    )
    controller.replay_mode_changed.connect(
        lambda enabled, start, end: signals.append((enabled, start, end))
    )

    start_iso = format_iso(datetime.now(timezone.utc) - timedelta(hours=2))
    ConfigStore.set_traccar_test_window_enabled(True)
    ConfigStore.set_traccar_test_window_start(start_iso)
    ConfigStore.set_traccar_test_window_hours(1)

    task_manager.start_task.side_effect = RuntimeError("task manager refused task")

    with patch(
        'sartracker.utils.mission_storage.MissionStorageHelper.prepare_temp_replay_store',
        return_value='/tmp/replay-start-failed.gpkg',
    ):
        started = controller.start_refresh()

    assert started is False
    assert ConfigStore.get_traccar_test_window_enabled() is True
    assert cleared == ['/tmp/replay-start-failed.gpkg']
    assert temp_store_path['value'] is None
    assert signals[0][0] is True
    assert signals[-1] == (False, "", "")
