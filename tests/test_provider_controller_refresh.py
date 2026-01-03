# -*- coding: utf-8 -*-
"""
Unit tests for ProviderController refresh filtering behavior.

These tests run without a QGIS runtime using mocked interfaces.
"""
from unittest.mock import MagicMock

from sartracker.controllers.provider_controller import ProviderController


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


def test_start_refresh_skips_mission_start_for_csv():
    controller, provider, task_manager = _build_controller('csv')
    controller.set_mission_start_getter(lambda: "2026-01-03T10:14:18Z")

    started = controller.start_refresh()

    assert started is True
    provider.create_refresh_task.assert_called_once()
    assert provider.create_refresh_task.call_args.kwargs.get('since_iso') is None


def test_start_refresh_uses_mission_start_for_traccar():
    controller, provider, task_manager = _build_controller('traccar_http')
    controller.set_mission_start_getter(lambda: "2026-01-03T10:14:18Z")

    started = controller.start_refresh()

    assert started is True
    provider.create_refresh_task.assert_called_once()
    assert provider.create_refresh_task.call_args.kwargs.get('since_iso') == "2026-01-03T10:14:18Z"
