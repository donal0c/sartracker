# -*- coding: utf-8 -*-
"""Shutdown and about-to-quit guard tests for SARTracker."""

from types import SimpleNamespace
from unittest.mock import MagicMock


def _build_tracker():
    from sartracker import sartracker as sartracker_module

    SarTracker = sartracker_module.sartracker
    tracker = SarTracker.__new__(SarTracker)
    tracker._focus_mode_exit_blocker_ran = False
    tracker._restore_focus_mode_before_quit = MagicMock()
    tracker._is_qt_deleted = MagicMock(return_value=False)
    tracker._stop_sar_panel_timers = MagicMock()
    tracker._shutdown_provider_controller = MagicMock()
    tracker._is_unloading = False
    tracker._skip_layer_ops = False
    tracker._app_is_quitting = False
    tracker._coords_updates_enabled = True
    tracker._map_canvas_connected = True
    tracker.layer_manager = MagicMock()
    tracker.task_manager = MagicMock()
    tracker.task_manager.begin_shutdown = MagicMock()
    tracker.task_manager.get_active_count.return_value = 2
    tracker.task_manager.cancel_all = MagicMock()
    tracker.coordinates_controller = MagicMock()
    tracker.mission_lifecycle_controller = MagicMock()
    tracker.mission_storage_controller = MagicMock()
    tracker.layers_controller = MagicMock()
    tracker.mission_controller = MagicMock()
    tracker.map_tools_controller = MagicMock()
    tracker.provider_controller = MagicMock()
    tracker.sar_panel = MagicMock()
    return tracker, SarTracker


def test_about_to_quit_sets_flags_and_runs_early_cleanup():
    tracker, SarTracker = _build_tracker()
    coordinates_controller = tracker.coordinates_controller
    mission_lifecycle_controller = tracker.mission_lifecycle_controller
    mission_storage_controller = tracker.mission_storage_controller
    layers_controller = tracker.layers_controller
    mission_controller = tracker.mission_controller
    map_tools_controller = tracker.map_tools_controller

    SarTracker._on_app_about_to_quit(tracker)

    assert tracker._app_is_quitting is True
    assert tracker._skip_layer_ops is True
    assert tracker._is_unloading is True
    tracker._restore_focus_mode_before_quit.assert_called_once_with()
    tracker._stop_sar_panel_timers.assert_called_once_with(
        "application about to quit (early)"
    )
    tracker.layer_manager.set_application_closing.assert_called_once_with(True)
    tracker.task_manager.begin_shutdown.assert_called_once_with()
    tracker._shutdown_provider_controller.assert_called_once_with(
        "application about to quit (early)",
        nullify=True,
    )
    tracker.task_manager.cancel_all.assert_called_once_with(wait_timeout_ms=3000)
    coordinates_controller.cleanup.assert_called_once_with(
        "application about to quit"
    )
    mission_lifecycle_controller.cleanup.assert_called_once_with()
    mission_storage_controller.cleanup.assert_called_once_with()
    layers_controller.cleanup.assert_called_once_with()
    mission_controller.cleanup.assert_called_once_with()
    map_tools_controller.cleanup.assert_called_once_with(
        "application about to quit"
    )
    assert tracker.coordinates_controller is None
    assert tracker.mission_lifecycle_controller is None
    assert tracker.mission_storage_controller is None
    assert tracker.layers_controller is None
    assert tracker.mission_controller is None
    assert tracker.map_tools_controller is None
    assert tracker._coords_updates_enabled is False
    assert tracker._map_canvas_connected is False


def test_about_to_quit_nulls_controllers_even_if_cleanup_raises():
    tracker, SarTracker = _build_tracker()
    tracker.coordinates_controller.cleanup.side_effect = RuntimeError("boom")
    tracker.mission_storage_controller.cleanup.side_effect = RuntimeError("boom")
    tracker.layers_controller.cleanup.side_effect = RuntimeError("boom")

    SarTracker._on_app_about_to_quit(tracker)

    assert tracker.coordinates_controller is None
    assert tracker.mission_storage_controller is None
    assert tracker.layers_controller is None
    assert tracker.mission_lifecycle_controller is None
    assert tracker.mission_controller is None
    assert tracker.map_tools_controller is None


def test_about_to_quit_skips_task_cancellation_when_no_active_tasks():
    tracker, SarTracker = _build_tracker()
    tracker.task_manager.get_active_count.return_value = 0

    SarTracker._on_app_about_to_quit(tracker)

    tracker.task_manager.cancel_all.assert_not_called()


def test_unload_disconnect_signals_disconnects_app_and_project_hooks(monkeypatch):
    from sartracker import sartracker as sartracker_module

    tracker, SarTracker = _build_tracker()
    tracker._map_canvas_connected = True
    tracker._exit_blocker_registered = True
    tracker._focus_mode_exit_blocker = object()
    tracker._on_project_read = MagicMock()
    tracker._on_new_project_created = MagicMock()
    tracker._on_mission_state_changed = MagicMock()
    tracker._on_mission_timing_update = MagicMock()
    tracker._safe_disconnect = MagicMock()

    project_read = SimpleNamespace(disconnect=MagicMock())
    new_project = SimpleNamespace(disconnect=MagicMock())
    tracker.iface = MagicMock(
        projectRead=project_read,
        newProjectCreated=new_project,
        unregisterApplicationExitBlocker=MagicMock(),
    )
    mission_controller = MagicMock(
        mission_state_changed=MagicMock(),
        mission_timing_updated=MagicMock(),
        cleanup=MagicMock(),
    )
    tracker.mission_controller = mission_controller

    app = SimpleNamespace(aboutToQuit=SimpleNamespace(disconnect=MagicMock()))
    monkeypatch.setattr(sartracker_module.QCoreApplication, "instance", MagicMock(return_value=app))

    SarTracker._unload_disconnect_signals(tracker)

    app.aboutToQuit.disconnect.assert_called_once_with(tracker._on_app_about_to_quit)
    project_read.disconnect.assert_called_once_with(tracker._on_project_read)
    new_project.disconnect.assert_called_once_with(tracker._on_new_project_created)
    tracker.iface.unregisterApplicationExitBlocker.assert_called_once_with(
        tracker._focus_mode_exit_blocker
    )
    tracker._safe_disconnect.assert_any_call(
        mission_controller.mission_state_changed,
        tracker._on_mission_state_changed,
        "mission_state_changed",
    )
    tracker._safe_disconnect.assert_any_call(
        mission_controller.mission_timing_updated,
        tracker._on_mission_timing_update,
        "mission_timing_updated",
    )
    mission_controller.cleanup.assert_called_once_with()
    assert tracker._map_canvas_connected is False
    assert tracker._exit_blocker_registered is False
    assert tracker.mission_controller is None


def test_unload_set_flags_starts_shutdown_and_protects_callbacks():
    from sartracker import sartracker as sartracker_module

    tracker, SarTracker = _build_tracker()
    tracker.error_handler = MagicMock()

    SarTracker._unload_set_flags(tracker)

    assert tracker._is_unloading is True
    assert tracker._skip_layer_ops is True
    tracker.error_handler.set_unloading.assert_called_once_with(True)
    tracker._stop_sar_panel_timers.assert_called_once_with("plugin unload (early)")
    tracker.task_manager.begin_shutdown.assert_called_once_with()
    tracker._shutdown_provider_controller.assert_called_once_with(
        "plugin unload (early)"
    )
    tracker.coordinates_controller.cleanup.assert_called_once_with(
        "plugin unload (early cleanup)"
    )
    tracker.layer_manager.set_application_closing.assert_called_once_with(True)
    assert tracker._coords_updates_enabled is False
    assert tracker._map_canvas_connected is False


def test_unload_set_flags_still_clears_coordinate_flags_when_cleanup_raises():
    from sartracker import sartracker as sartracker_module

    tracker, SarTracker = _build_tracker()
    tracker.coordinates_controller.cleanup.side_effect = RuntimeError("boom")

    SarTracker._unload_set_flags(tracker)

    assert tracker._is_unloading is True
    assert tracker._skip_layer_ops is True
    assert tracker._coords_updates_enabled is False
    assert tracker._map_canvas_connected is False
    tracker.layer_manager.set_application_closing.assert_called_once_with(True)


def test_unload_cancel_tasks_cancels_when_active_tasks_exist():
    from sartracker import sartracker as sartracker_module

    tracker, SarTracker = _build_tracker()
    tracker.task_manager.get_active_count.return_value = 3

    SarTracker._unload_cancel_tasks(tracker)

    tracker.task_manager.cancel_all.assert_called_once_with(wait_timeout_ms=5000)


def test_unload_cancel_tasks_skips_cancel_when_no_active_tasks():
    from sartracker import sartracker as sartracker_module

    tracker, SarTracker = _build_tracker()
    tracker.task_manager.get_active_count.return_value = 0

    SarTracker._unload_cancel_tasks(tracker)

    tracker.task_manager.cancel_all.assert_not_called()


def test_unload_remove_actions_cleans_toolbar_menu_and_context_action():
    from sartracker import sartracker as sartracker_module

    tracker, SarTracker = _build_tracker()
    tracker.tr = lambda text: text
    tracker.actions = [MagicMock(), MagicMock()]
    edit_marker_action = MagicMock()
    tracker._edit_marker_action = edit_marker_action
    tracker.iface = MagicMock(
        removePluginMenu=MagicMock(),
        removeToolBarIcon=MagicMock(),
        removeCustomActionForLayerType=MagicMock(),
    )

    SarTracker._unload_remove_actions(tracker)

    assert tracker.iface.removePluginMenu.call_count == 2
    assert tracker.iface.removeToolBarIcon.call_count == 2
    tracker.iface.removeCustomActionForLayerType.assert_called_once_with(
        edit_marker_action
    )
    assert tracker._edit_marker_action is None


def test_unload_remove_actions_skips_deleted_actions():
    from sartracker import sartracker as sartracker_module

    tracker, SarTracker = _build_tracker()
    valid_action = MagicMock()
    deleted_action = MagicMock()
    tracker.tr = lambda text: text
    tracker.actions = [valid_action, deleted_action]
    tracker._edit_marker_action = None
    tracker.iface = MagicMock(
        removePluginMenu=MagicMock(),
        removeToolBarIcon=MagicMock(),
    )
    tracker._is_qt_deleted.side_effect = lambda obj: obj is deleted_action

    SarTracker._unload_remove_actions(tracker)

    tracker.iface.removePluginMenu.assert_called_once_with("&sartracker", valid_action)
    tracker.iface.removeToolBarIcon.assert_called_once_with(valid_action)
