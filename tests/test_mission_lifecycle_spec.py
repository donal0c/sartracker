# -*- coding: utf-8 -*-
"""
Mission lifecycle specification tests.

These tests are intentionally behavior-first:
- some describe expected lifecycle behavior that already passes today
- some are strict xfails that document expected behavior not yet implemented

The goal is to turn mission startup/resume/autosave/cleanup expectations into
executable specifications before we change production code.
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def _iface_stub():
    return SimpleNamespace(
        messageBar=lambda: None,
        mainWindow=lambda: None,
    )


class _LayerManagerStub:
    def __init__(self, store_path=None, coordinators=""):
        self._store_path = store_path
        self._coordinators = coordinators

    def get_mission_store(self):
        return self._store_path

    def get_mission_coordinators(self):
        return self._coordinators


def test_handle_mission_resume_without_store_falls_back_to_new_mission(monkeypatch):
    """
    Resuming with no mission store should create a new mission store instead of
    leaving the controller in an ambiguous half-resumed state.
    """
    from sartracker.controllers.mission_lifecycle_controller import MissionLifecycleController
    from sartracker.controllers import mission_lifecycle_controller as module

    warning_calls = []
    monkeypatch.setattr(
        module,
        "warning",
        lambda *_args, **_kwargs: warning_calls.append((_args, _kwargs)),
    )

    controller = MissionLifecycleController(
        iface=_iface_stub(),
        layer_manager=_LayerManagerStub(store_path=None),
        mission_storage=object(),
    )
    controller.prepare_new_mission = MagicMock(return_value=True)

    result = controller.handle_mission_resume("Fresh Mission")

    assert result is True
    controller.prepare_new_mission.assert_called_once_with("Fresh Mission")
    assert warning_calls, "Missing-store fallback should warn operators"


def test_load_existing_storage_state_start_fresh_clears_saved_mission_state(tmp_path, monkeypatch):
    """
    Choosing Start Fresh should clear any persisted paused-mission state so a
    later startup does not silently resume the abandoned mission.
    """
    from sartracker.controllers.mission_lifecycle_controller import MissionLifecycleController

    gpkg_path = tmp_path / "existing_mission" / "existing_mission.gpkg"
    gpkg_path.parent.mkdir(parents=True)
    gpkg_path.touch()

    mission_controller = SimpleNamespace(
        clear_saved_state=MagicMock(),
        is_active=lambda: False,
    )

    controller = MissionLifecycleController(
        iface=_iface_stub(),
        layer_manager=_LayerManagerStub(store_path=str(gpkg_path)),
        mission_storage=object(),
        mission_controller=mission_controller,
    )

    controller.show_resume_prompt = MagicMock(return_value=False)
    controller.prompt_new_mission_name = MagicMock(return_value="Fresh Mission")
    controller.prepare_new_mission = MagicMock(return_value=True)

    result = controller.load_existing_storage_state()

    assert result is True
    controller.prepare_new_mission.assert_called_once_with("Fresh Mission")
    mission_controller.clear_saved_state.assert_called_once_with()


def test_load_existing_storage_state_start_fresh_cancel_leaves_existing_store_untouched(tmp_path):
    """
    If the operator backs out of naming a fresh mission, startup should leave
    the existing mission store alone rather than creating or clearing anything.
    """
    from sartracker.controllers.mission_lifecycle_controller import MissionLifecycleController

    gpkg_path = tmp_path / "existing_mission" / "existing_mission.gpkg"
    gpkg_path.parent.mkdir(parents=True)
    gpkg_path.touch()

    mission_controller = SimpleNamespace(
        clear_saved_state=MagicMock(),
        is_active=lambda: False,
    )

    controller = MissionLifecycleController(
        iface=_iface_stub(),
        layer_manager=_LayerManagerStub(store_path=str(gpkg_path)),
        mission_storage=object(),
        mission_controller=mission_controller,
    )

    controller.show_resume_prompt = MagicMock(return_value=False)
    controller.prompt_new_mission_name = MagicMock(return_value=None)
    controller.prepare_new_mission = MagicMock(return_value=True)

    result = controller.load_existing_storage_state()

    assert result is False
    controller.prepare_new_mission.assert_not_called()
    mission_controller.clear_saved_state.assert_not_called()


def test_start_fresh_prepare_failure_clears_stale_session_state(tmp_path):
    """
    Spec: a failed Start Fresh attempt should not leave prior mission session
    data hanging around in memory.
    """
    from sartracker.controllers.mission_lifecycle_controller import MissionLifecycleController

    gpkg_path = tmp_path / "existing_mission" / "existing_mission.gpkg"
    gpkg_path.parent.mkdir(parents=True)
    gpkg_path.touch()

    mission_controller = SimpleNamespace(
        clear_saved_state=MagicMock(),
        is_active=lambda: False,
    )

    controller = MissionLifecycleController(
        iface=_iface_stub(),
        layer_manager=_LayerManagerStub(store_path=str(gpkg_path)),
        mission_storage=object(),
        mission_controller=mission_controller,
    )
    controller._update_session_state(
        mission_name="Stale Mission",
        coordinators="Alice",
        metadata_collected=True,
        is_active=True,
    )

    controller.show_resume_prompt = MagicMock(return_value=False)
    controller.prompt_new_mission_name = MagicMock(return_value="Fresh Mission")
    controller.prepare_new_mission = MagicMock(return_value=False)

    assert controller.load_existing_storage_state() is False
    snapshot = controller.status_snapshot()
    assert snapshot["mission_name"] is None
    assert snapshot["coordinators"] is None
    assert snapshot["metadata_collected"] is False
    assert snapshot["is_active"] is False


def test_load_existing_storage_state_without_store_clears_stale_session_state():
    """
    Startup with no configured mission store should reset any stale in-memory
    lifecycle session state back to empty.
    """
    from sartracker.controllers.mission_lifecycle_controller import MissionLifecycleController

    controller = MissionLifecycleController(
        iface=_iface_stub(),
        layer_manager=_LayerManagerStub(store_path=None),
    )
    controller._update_session_state(
        mission_name="Stale Mission",
        coordinators="Alice,Bob",
        metadata_collected=True,
        is_active=True,
    )

    result = controller.load_existing_storage_state()

    assert result is False
    snapshot = controller.status_snapshot()
    assert snapshot["mission_name"] is None
    assert snapshot["coordinators"] is None
    assert snapshot["metadata_collected"] is False
    assert snapshot["is_active"] is False


def test_missing_configured_store_clears_stale_session_state(tmp_path):
    """
    Spec: if a configured mission store points to a missing file, startup should
    not keep advertising old session state from memory.
    """
    from sartracker.controllers.mission_lifecycle_controller import MissionLifecycleController

    gpkg_path = tmp_path / "missing_mission" / "missing_mission.gpkg"

    controller = MissionLifecycleController(
        iface=_iface_stub(),
        layer_manager=_LayerManagerStub(store_path=str(gpkg_path)),
    )
    controller._update_session_state(
        mission_name="Stale Mission",
        coordinators="Alice",
        metadata_collected=True,
        is_active=True,
    )

    assert controller.load_existing_storage_state() is False
    snapshot = controller.status_snapshot()
    assert snapshot["mission_name"] is None
    assert snapshot["coordinators"] is None
    assert snapshot["is_active"] is False


def test_load_existing_storage_state_prompts_for_metadata_when_resume_lacks_coordinators(tmp_path):
    """
    Resuming existing storage without recorded coordinators should trigger the
    metadata collection flow exactly once.
    """
    from sartracker.controllers.mission_lifecycle_controller import MissionLifecycleController

    gpkg_path = tmp_path / "mission_resume" / "mission_resume.gpkg"
    gpkg_path.parent.mkdir(parents=True)
    gpkg_path.touch()

    controller = MissionLifecycleController(
        iface=_iface_stub(),
        layer_manager=_LayerManagerStub(store_path=str(gpkg_path), coordinators=""),
        mission_controller=SimpleNamespace(is_active=lambda: False),
    )
    controller.show_resume_prompt = MagicMock(return_value=True)
    controller.collect_mission_metadata = MagicMock(return_value=True)

    result = controller.load_existing_storage_state()

    assert result is True
    controller.collect_mission_metadata.assert_called_once_with(
        mode="resume",
        allow_resume_time=True,
        preselected=None,
    )


def test_load_existing_storage_state_skips_metadata_prompt_when_resume_has_coordinators(tmp_path):
    """
    Resuming existing storage with coordinator metadata already present should
    not re-prompt and risk clobbering that state.
    """
    from sartracker.controllers.mission_lifecycle_controller import MissionLifecycleController

    gpkg_path = tmp_path / "mission_resume" / "mission_resume.gpkg"
    gpkg_path.parent.mkdir(parents=True)
    gpkg_path.touch()

    controller = MissionLifecycleController(
        iface=_iface_stub(),
        layer_manager=_LayerManagerStub(store_path=str(gpkg_path), coordinators="Alice,Bob"),
        mission_controller=SimpleNamespace(is_active=lambda: False),
    )
    controller.show_resume_prompt = MagicMock(return_value=True)
    controller.collect_mission_metadata = MagicMock(return_value=True)

    result = controller.load_existing_storage_state()

    assert result is True
    controller.collect_mission_metadata.assert_not_called()
    snapshot = controller.status_snapshot()
    assert snapshot["coordinators"] == "Alice,Bob"
    assert snapshot["metadata_collected"] is True


def test_collect_mission_metadata_persists_selection_into_session_state(monkeypatch):
    """
    Successful coordinator collection should persist the chosen roster and mark
    metadata as collected in lifecycle state.
    """
    from sartracker.controllers import mission_lifecycle_controller as module
    from sartracker.controllers.mission_lifecycle_controller import MissionLifecycleController
    from sartracker.ui import mission_metadata_dialog as dialog_module

    class _Dialog:
        def __init__(self, *args, **kwargs):
            return None

        def selected_coordinators(self):
            return ["Alice", "Bob"]

        def pending_entry(self):
            return None

        def updated_roster(self):
            return ["Alice", "Bob"]

        def resume_timestamp(self):
            return None

        def all_entries(self):
            return ["Alice", "Bob"]

    layer_manager = SimpleNamespace(
        get_mission_coordinators=lambda: "",
        set_mission_coordinators=MagicMock(),
    )

    monkeypatch.setattr(module.ConfigStore, "get_coordinator_list", lambda: ["Alice", "Bob"])
    monkeypatch.setattr(module.ConfigStore, "set_coordinator_roster", lambda _value: None)
    monkeypatch.setattr(dialog_module, "MissionMetadataDialog", _Dialog)
    monkeypatch.setattr(module, "dialog_exec", lambda _dialog: module.DialogAccepted)

    controller = MissionLifecycleController(
        iface=_iface_stub(),
        layer_manager=layer_manager,
    )

    result = controller.collect_mission_metadata(
        mode="resume",
        allow_resume_time=True,
        preselected=None,
    )

    assert result is True
    layer_manager.set_mission_coordinators.assert_called_once_with("Alice,Bob")
    snapshot = controller.status_snapshot()
    assert snapshot["coordinators"] == "Alice,Bob"
    assert snapshot["metadata_collected"] is True


def test_collect_mission_metadata_does_not_claim_success_when_persist_fails(monkeypatch):
    """
    Spec: if coordinator persistence fails, lifecycle state should not claim
    metadata was collected successfully.
    """
    from sartracker.controllers import mission_lifecycle_controller as module
    from sartracker.controllers.mission_lifecycle_controller import MissionLifecycleController
    from sartracker.ui import mission_metadata_dialog as dialog_module

    class _Dialog:
        def __init__(self, *args, **kwargs):
            return None

        def selected_coordinators(self):
            return ["Alice"]

        def pending_entry(self):
            return None

        def updated_roster(self):
            return ["Alice"]

        def resume_timestamp(self):
            return None

        def all_entries(self):
            return ["Alice"]

    layer_manager = SimpleNamespace(
        get_mission_coordinators=lambda: "",
        set_mission_coordinators=MagicMock(side_effect=RuntimeError("project variable write failed")),
    )

    monkeypatch.setattr(module.ConfigStore, "get_coordinator_list", lambda: ["Alice"])
    monkeypatch.setattr(module.ConfigStore, "set_coordinator_roster", lambda _value: None)
    monkeypatch.setattr(dialog_module, "MissionMetadataDialog", _Dialog)
    monkeypatch.setattr(module, "dialog_exec", lambda _dialog: module.DialogAccepted)
    monkeypatch.setattr(module, "warning", lambda *args, **kwargs: None)

    controller = MissionLifecycleController(
        iface=_iface_stub(),
        layer_manager=layer_manager,
    )

    result = controller.collect_mission_metadata(
        mode="resume",
        allow_resume_time=True,
        preselected=None,
    )

    assert result is False
    snapshot = controller.status_snapshot()
    assert snapshot["coordinators"] in ("", None)
    assert snapshot["metadata_collected"] is False


def test_load_resumed_storage_creates_attachments_and_backup_paths(tmp_path):
    """
    Resumed storage loading should recreate the attachments folder if needed and
    carry forward the resolved backup directory into session state.
    """
    from sartracker.controllers.mission_lifecycle_controller import MissionLifecycleController

    gpkg_path = tmp_path / "mission_resume" / "mission_resume.gpkg"
    gpkg_path.parent.mkdir(parents=True)
    gpkg_path.touch()

    backup_dir = tmp_path / "backup_root" / "mission_resume"
    controller = MissionLifecycleController(
        iface=_iface_stub(),
        layer_manager=_LayerManagerStub(store_path=str(gpkg_path), coordinators="Alice"),
        mission_storage=SimpleNamespace(
            ensure_backup_directory=MagicMock(return_value=backup_dir)
        ),
    )

    result = controller._load_resumed_storage(gpkg_path)

    assert result is True
    assert controller.attachments_dir == gpkg_path.parent / "attachments"
    assert controller.attachments_dir.exists()
    assert controller.backup_dir == backup_dir
    assert controller.mission_name == "mission_resume"


def test_load_resumed_storage_tolerates_backup_directory_failure(tmp_path):
    """
    Backup directory preparation is helpful but non-fatal; resumed storage
    should still load if the backup root cannot be resolved.
    """
    from sartracker.controllers.mission_lifecycle_controller import MissionLifecycleController

    gpkg_path = tmp_path / "mission_resume" / "mission_resume.gpkg"
    gpkg_path.parent.mkdir(parents=True)
    gpkg_path.touch()

    controller = MissionLifecycleController(
        iface=_iface_stub(),
        layer_manager=_LayerManagerStub(store_path=str(gpkg_path), coordinators="Alice"),
        mission_storage=SimpleNamespace(
            ensure_backup_directory=MagicMock(side_effect=RuntimeError("backup root missing"))
        ),
    )

    result = controller._load_resumed_storage(gpkg_path)

    assert result is True
    assert controller.backup_dir is None
    assert controller.attachments_dir == gpkg_path.parent / "attachments"


def test_load_resumed_storage_missing_file_clears_stale_session_state(tmp_path):
    """
    Spec: if a mission file disappears between detection and load, lifecycle
    session state should be cleared so operators are not left with stale
    mission context.
    """
    from sartracker.controllers.mission_lifecycle_controller import MissionLifecycleController

    gpkg_path = tmp_path / "mission_resume" / "mission_resume.gpkg"

    controller = MissionLifecycleController(
        iface=_iface_stub(),
        layer_manager=_LayerManagerStub(store_path=str(gpkg_path)),
    )
    controller._update_session_state(
        mission_name="Stale Mission",
        coordinators="Alice",
        metadata_collected=True,
        is_active=True,
    )

    assert controller._load_resumed_storage(gpkg_path) is False
    snapshot = controller.status_snapshot()
    assert snapshot["mission_name"] is None
    assert snapshot["coordinators"] is None
    assert snapshot["metadata_collected"] is False
    assert snapshot["is_active"] is False


def test_handle_mission_resume_invalid_store_starts_fresh(monkeypatch):
    """
    If the configured mission store is invalid, resume should degrade to a new
    mission setup instead of leaving the mission controller in limbo.
    """
    from sartracker.controllers import mission_lifecycle_controller as module
    from sartracker.controllers.mission_lifecycle_controller import MissionLifecycleController

    warning_calls = []
    monkeypatch.setattr(
        module,
        "warning",
        lambda *_args, **_kwargs: warning_calls.append((_args, _kwargs)),
    )

    layer_manager = _LayerManagerStub(store_path="/tmp/missing.gpkg")
    mission_storage = SimpleNamespace(
        handle_resume=MagicMock(side_effect=FileNotFoundError("missing store"))
    )
    controller = MissionLifecycleController(
        iface=_iface_stub(),
        layer_manager=layer_manager,
        mission_storage=mission_storage,
    )
    controller.prepare_new_mission = MagicMock(return_value=True)

    result = controller.handle_mission_resume("Replacement Mission")

    assert result is True
    controller.prepare_new_mission.assert_called_once_with("Replacement Mission")
    assert warning_calls, "Invalid-store fallback should warn operators"


def test_legacy_handle_mission_resume_storage_invalid_store_starts_fresh(tmp_path):
    """
    Legacy paused-mission storage recovery should fall back to fresh storage if
    the configured mission store cannot be resumed.
    """
    from sartracker import sartracker as sartracker_module

    gpkg_path = tmp_path / "missing_resume.gpkg"

    SarTracker = sartracker_module.sartracker
    tracker = SarTracker.__new__(SarTracker)
    tracker.layer_manager = SimpleNamespace(get_mission_store=lambda: str(gpkg_path))
    tracker.mission_storage = SimpleNamespace(
        handle_resume=MagicMock(side_effect=FileNotFoundError("missing store"))
    )
    tracker.iface = MagicMock()
    tracker._log_exception = MagicMock()
    tracker._prepare_new_mission_storage = MagicMock()

    SarTracker._handle_mission_resume_storage(tracker, "Replacement Mission")

    tracker._prepare_new_mission_storage.assert_called_once_with("Replacement Mission")


def test_cleanup_freezes_lifecycle_state_against_late_updates():
    """
    After cleanup, late mission-controller syncs should not mutate lifecycle
    state. This guards against unload-time callbacks racing with teardown.
    """
    from sartracker.controllers.mission_lifecycle_controller import MissionLifecycleController

    class _MissionControllerStub:
        def is_active(self):
            return True

        def status_snapshot(self):
            return {"started_at": "2026-03-27T12:00:00+00:00"}

    controller = MissionLifecycleController(
        iface=_iface_stub(),
        mission_controller=_MissionControllerStub(),
    )

    controller.cleanup()
    controller.sync_active_state()

    snapshot = controller.status_snapshot()
    assert snapshot["is_shutting_down"] is True
    assert snapshot["is_active"] is False
    assert snapshot["start_time"] is None


def test_prepare_new_mission_clears_finalize_and_resume_metadata(tmp_path):
    """
    Starting a fresh mission should reset finalized/coordinator/resume metadata
    before pointing the layer manager at the new store.
    """
    from sartracker.utils.mission_storage import MissionStorageHelper

    class _LayerManager:
        def __init__(self):
            self.calls = []

        def set_mission_finalized(self, value):
            self.calls.append(("finalized", value))

        def set_mission_coordinators(self, value):
            self.calls.append(("coordinators", value))

        def set_resume_timestamp(self, value):
            self.calls.append(("resume", value))

        def set_mission_store(self, value):
            self.calls.append(("store", value))

        def ensure_structure(self, auto_migrate=False):
            self.calls.append(("ensure_structure", auto_migrate))

    class _Config:
        def get_mission_primary_root(self):
            return str(tmp_path / "primary")

        def get_mission_backup_root(self):
            return str(tmp_path / "backup")

    layer_manager = _LayerManager()
    helper = MissionStorageHelper(layer_manager=layer_manager, config_store=_Config())

    paths = helper.prepare_new_mission("Mission Alpha")

    assert ("finalized", False) in layer_manager.calls
    assert ("coordinators", "") in layer_manager.calls
    assert ("resume", "") in layer_manager.calls
    assert layer_manager.calls[-1] == ("ensure_structure", False)
    assert paths.gpkg_path.name == "Mission_Alpha.gpkg"


def test_sync_project_state_unsaved_non_sar_project_does_not_ensure_structure(monkeypatch):
    """
    Project sync should not dirty an unsaved non-SAR project by forcing SAR
    structure into it during startup.
    """
    from sartracker.controllers import mission_lifecycle_controller as module
    from sartracker.controllers.mission_lifecycle_controller import MissionLifecycleController

    project = SimpleNamespace(fileName=lambda: "")
    monkeypatch.setattr(module.QgsProject, "instance", MagicMock(return_value=project))

    layer_manager = SimpleNamespace(
        get_mission_store=lambda: "",
        on_project_read=MagicMock(),
        is_sar_project=lambda: False,
        ensure_structure=MagicMock(),
    )

    controller = MissionLifecycleController(
        iface=_iface_stub(),
        layer_manager=layer_manager,
    )
    controller.load_existing_storage_state = MagicMock(return_value=False)

    result = controller.sync_project_state(reason="startup")

    assert result is True
    layer_manager.ensure_structure.assert_not_called()
    controller.load_existing_storage_state.assert_called_once_with()


def test_post_init_state_with_controller_uses_single_deferred_startup_sync(monkeypatch):
    """
    Startup should not load mission storage twice when the lifecycle controller
    is present. The initial storage prompt/load should flow through the
    deferred project sync path exactly once.
    """
    from sartracker import sartracker as sartracker_module

    SarTracker = sartracker_module.sartracker
    tracker = SarTracker.__new__(SarTracker)
    tracker._is_unloading = False
    tracker._app_is_quitting = False
    tracker.tool_registry = object()
    tracker.sar_panel = MagicMock()
    tracker._init_coordinates_controller = MagicMock()
    tracker._check_for_paused_mission = MagicMock()
    tracker._check_focus_mode_crash_recovery = MagicMock()
    tracker._log_exception = MagicMock()
    tracker._load_existing_mission_storage_state = MagicMock()
    tracker.mission_lifecycle_controller = SimpleNamespace(
        load_existing_storage_state=MagicMock(),
        sync_project_state=MagicMock(),
    )

    def _run_immediately(_delay, callback):
        callback()

    monkeypatch.setattr(sartracker_module.QTimer, "singleShot", _run_immediately, raising=False)

    SarTracker._post_init_state(tracker)

    tracker.mission_lifecycle_controller.load_existing_storage_state.assert_not_called()
    tracker.mission_lifecycle_controller.sync_project_state.assert_called_once_with(reason="startup")
    tracker._load_existing_mission_storage_state.assert_not_called()


def test_post_init_state_without_controller_uses_single_deferred_startup_sync(monkeypatch):
    """
    Legacy startup should also avoid an immediate mission-storage load followed
    by a second deferred sync load.
    """
    from sartracker import sartracker as sartracker_module

    SarTracker = sartracker_module.sartracker
    tracker = SarTracker.__new__(SarTracker)
    tracker._is_unloading = False
    tracker._app_is_quitting = False
    tracker.tool_registry = object()
    tracker.sar_panel = MagicMock()
    tracker._init_coordinates_controller = MagicMock()
    tracker._check_for_paused_mission = MagicMock()
    tracker._check_focus_mode_crash_recovery = MagicMock()
    tracker._load_existing_mission_storage_state = MagicMock()
    tracker._sync_project_state = MagicMock()
    tracker.mission_lifecycle_controller = None

    def _run_immediately(_delay, callback):
        callback()

    monkeypatch.setattr(sartracker_module.QTimer, "singleShot", _run_immediately, raising=False)

    SarTracker._post_init_state(tracker)

    tracker._load_existing_mission_storage_state.assert_not_called()
    tracker._sync_project_state.assert_called_once_with(reason="startup")


def test_spec_hidden_startup_defers_lifecycle_sync_until_explicit_activation(monkeypatch):
    """
    Spec: when the SAR panel starts hidden, plugin initialization should not
    trigger mission-storage prompting until the operator explicitly activates
    SAR Tracker.
    """
    from sartracker import sartracker as sartracker_module

    callbacks = []

    SarTracker = sartracker_module.sartracker
    tracker = SarTracker.__new__(SarTracker)
    tracker._is_unloading = False
    tracker._app_is_quitting = False
    tracker.tool_registry = object()
    tracker.sar_panel = MagicMock()
    tracker.sar_panel.isVisible.return_value = False
    tracker._init_coordinates_controller = MagicMock()
    tracker._check_for_paused_mission = MagicMock()
    tracker._check_focus_mode_crash_recovery = MagicMock()
    tracker._safe_mode_block = MagicMock(return_value=False)
    tracker._log_exception = MagicMock()
    tracker.mission_lifecycle_controller = SimpleNamespace(
        sync_project_state=MagicMock(),
    )

    def _capture_callback(delay, callback):
        callbacks.append((delay, callback))

    monkeypatch.setattr(sartracker_module.QTimer, "singleShot", _capture_callback, raising=False)

    SarTracker._post_init_state(tracker)

    assert callbacks, "Expected startup to schedule deferred work"
    tracker.mission_lifecycle_controller.sync_project_state.assert_not_called()

    SarTracker.run(tracker)

    tracker.sar_panel.show.assert_called_once_with()
    tracker.mission_lifecycle_controller.sync_project_state.assert_called_once_with(reason="startup")


def test_spec_hidden_startup_defers_provider_auto_connect_until_activation():
    """
    Spec: provider auto-connect should not start network/provider activity while
    SAR Tracker is still hidden on startup.
    """
    from sartracker import sartracker as sartracker_module

    SarTracker = sartracker_module.sartracker
    tracker = SarTracker.__new__(SarTracker)
    tracker.sar_panel = MagicMock()
    tracker.layers_controller = None
    tracker.layer_manager = MagicMock(
        set_temp_mission_store=MagicMock(),
        clear_temp_mission_store=MagicMock(),
        get_temp_mission_store=MagicMock(return_value=None),
    )
    tracker.provider_controller = MagicMock()
    tracker.provider_controller.status_changed = MagicMock(connect=MagicMock())
    tracker.provider_controller.provider_connected = MagicMock(connect=MagicMock())
    tracker.provider_controller.replay_mode_changed = MagicMock(connect=MagicMock())
    tracker._get_mission_start_iso = MagicMock(return_value=None)
    tracker._is_mission_active = MagicMock(return_value=False)
    tracker._on_panel_refresh_requested = MagicMock()
    tracker._check_for_paused_mission = MagicMock()
    tracker._startup_activation_pending = True

    SarTracker._wire_provider_controller(tracker)

    tracker.provider_controller.load_config_and_auto_connect.assert_not_called()

    tracker._deferred_sync_project_state = MagicMock()
    tracker._safe_mode_block = MagicMock(return_value=False)
    tracker.sar_panel.isVisible.return_value = False
    SarTracker.run(tracker)

    tracker.provider_controller.load_config_and_auto_connect.assert_called_once_with()


def test_spec_hidden_startup_defers_paused_mission_prompt_until_activation(monkeypatch):
    """
    Spec: paused-mission recovery prompting should wait until the operator has
    explicitly activated SAR Tracker for this QGIS session.
    """
    from sartracker import sartracker as sartracker_module

    callbacks = []

    SarTracker = sartracker_module.sartracker
    tracker = SarTracker.__new__(SarTracker)
    tracker._is_unloading = False
    tracker._app_is_quitting = False
    tracker.tool_registry = object()
    tracker.sar_panel = MagicMock()
    tracker.sar_panel.isVisible.return_value = False
    tracker._init_coordinates_controller = MagicMock()
    tracker._check_for_paused_mission = MagicMock()
    tracker._check_focus_mode_crash_recovery = MagicMock()
    tracker._safe_mode_block = MagicMock(return_value=False)
    tracker._log_exception = MagicMock()
    tracker.mission_lifecycle_controller = SimpleNamespace(
        sync_project_state=MagicMock(),
    )

    def _capture_callback(delay, callback):
        callbacks.append((delay, callback))

    monkeypatch.setattr(sartracker_module.QTimer, "singleShot", _capture_callback, raising=False)

    SarTracker._post_init_state(tracker)

    assert tracker._check_for_paused_mission.call_count == 0
    assert all(callback != tracker._check_for_paused_mission for _delay, callback in callbacks)

    SarTracker.run(tracker)

    assert any(callback == tracker._check_for_paused_mission for _delay, callback in callbacks)


def test_startup_activation_only_runs_once(monkeypatch):
    """
    Once the hidden-startup activation work has run, later hide/show cycles
    should not re-run startup-only sync and auto-connect behavior.
    """
    from sartracker import sartracker as sartracker_module

    SarTracker = sartracker_module.sartracker
    tracker = SarTracker.__new__(SarTracker)
    tracker._safe_mode_block = MagicMock(return_value=False)
    tracker.sar_panel = MagicMock()
    tracker.sar_panel.isVisible.side_effect = [False, True, False]
    tracker.provider_controller = MagicMock()
    tracker._deferred_sync_project_state = MagicMock()
    tracker._check_for_paused_mission = MagicMock()
    tracker._startup_activation_pending = True

    monkeypatch.setattr(
        sartracker_module.QTimer,
        "singleShot",
        lambda _delay, callback: callback(),
        raising=False,
    )

    SarTracker.run(tracker)
    SarTracker.run(tracker)
    SarTracker.run(tracker)

    assert tracker.provider_controller.load_config_and_auto_connect.call_count == 1
    assert tracker._deferred_sync_project_state.call_count == 1
    assert tracker._check_for_paused_mission.call_count == 1


def test_sync_project_state_ignores_duplicate_signature(monkeypatch):
    """
    Repeated syncs with the same project/store signature should be skipped to
    avoid duplicate rebuild work and duplicate prompts.
    """
    from sartracker.controllers import mission_lifecycle_controller as module
    from sartracker.controllers.mission_lifecycle_controller import MissionLifecycleController

    project = SimpleNamespace(fileName=lambda: "/tmp/test.qgz")
    monkeypatch.setattr(module.QgsProject, "instance", MagicMock(return_value=project))

    layer_manager = SimpleNamespace(
        get_mission_store=lambda: "/tmp/mission.gpkg",
        on_project_read=MagicMock(),
        is_sar_project=lambda: True,
        ensure_structure=MagicMock(),
    )

    controller = MissionLifecycleController(
        iface=_iface_stub(),
        layer_manager=layer_manager,
    )
    controller.load_existing_storage_state = MagicMock(return_value=False)

    assert controller.sync_project_state(reason="first") is True
    assert controller.sync_project_state(reason="second") is False
    assert layer_manager.on_project_read.call_count == 1
    assert layer_manager.ensure_structure.call_count == 1
    assert controller.load_existing_storage_state.call_count == 1


def test_sync_project_state_with_store_ensures_structure(monkeypatch):
    """
    When a mission store is configured, project sync should ensure SAR
    structure before loading mission storage state.
    """
    from sartracker.controllers import mission_lifecycle_controller as module
    from sartracker.controllers.mission_lifecycle_controller import MissionLifecycleController

    project = SimpleNamespace(fileName=lambda: "")
    monkeypatch.setattr(module.QgsProject, "instance", MagicMock(return_value=project))

    layer_manager = SimpleNamespace(
        get_mission_store=lambda: "/tmp/mission.gpkg",
        on_project_read=MagicMock(),
        is_sar_project=lambda: False,
        ensure_structure=MagicMock(),
    )

    controller = MissionLifecycleController(
        iface=_iface_stub(),
        layer_manager=layer_manager,
    )
    controller.load_existing_storage_state = MagicMock(return_value=False)

    result = controller.sync_project_state(reason="storeConfigured")

    assert result is True
    layer_manager.ensure_structure.assert_called_once_with(auto_migrate=True)
    controller.load_existing_storage_state.assert_called_once_with()


def test_legacy_sync_project_state_unsaved_non_sar_project_does_not_ensure_structure(monkeypatch):
    """
    Legacy project sync should also avoid dirtying an unsaved non-SAR project.
    """
    from sartracker import sartracker as sartracker_module

    SarTracker = sartracker_module.sartracker
    tracker = SarTracker.__new__(SarTracker)
    tracker._is_unloading = False
    tracker._app_is_quitting = False
    tracker._last_project_signature = ""
    tracker.sar_panel = object()
    tracker.layers_controller = None
    tracker.iface = MagicMock()

    project = SimpleNamespace(fileName=lambda: "")
    monkeypatch.setattr(sartracker_module.QgsProject, "instance", MagicMock(return_value=project))

    tracker.layer_manager = SimpleNamespace(
        get_mission_store=lambda: "",
        on_project_read=MagicMock(),
        is_sar_project=lambda: False,
        ensure_structure=MagicMock(),
    )
    tracker._load_existing_mission_storage_state = MagicMock()

    SarTracker._sync_project_state(tracker, reason="legacy_startup")

    tracker.layer_manager.ensure_structure.assert_not_called()
    tracker._load_existing_mission_storage_state.assert_called_once_with()


def test_recover_missing_layers_rebuilds_when_required_subgroups_are_missing(monkeypatch):
    """
    Startup recovery should not stop at the SAR root group if key subgroups are
    missing. Tracking-only trees should be rebuilt to restore Map Tools and
    Helicopters without requiring a manual Repair action.
    """
    from sartracker import sartracker as sartracker_module
    from sartracker.layers import GroupNames

    class _Group:
        def __init__(self, groups=None):
            self._groups = groups or {}

        def findGroup(self, name):
            return self._groups.get(name)

    sar_group = _Group(groups={GroupNames.TRACKING: _Group()})
    root = _Group(groups={GroupNames.ROOT: sar_group})
    project = SimpleNamespace(layerTreeRoot=lambda: root)
    monkeypatch.setattr(sartracker_module.QgsProject, "instance", MagicMock(return_value=project))

    SarTracker = sartracker_module.sartracker
    tracker = SarTracker.__new__(SarTracker)
    tracker._should_skip_layer_ops = MagicMock(return_value=False)
    tracker.layer_manager = SimpleNamespace(ensure_structure=MagicMock())
    tracker.layers_controller = SimpleNamespace(
        ensure_helicopter_layers=MagicMock(return_value=True),
        catalog=None,
    )
    tracker._log_exception = MagicMock()

    SarTracker._recover_missing_layers(tracker)

    tracker.layer_manager.ensure_structure.assert_called_once_with(auto_migrate=False)
    tracker.layers_controller.ensure_helicopter_layers.assert_called_once_with()


def test_recover_missing_layers_noops_when_required_groups_are_present(monkeypatch):
    """
    Once Tracking, Map Tools, and Helicopters are present, recovery should not
    rebuild the structure again.
    """
    from sartracker import sartracker as sartracker_module
    from sartracker.layers import GroupNames

    class _Group:
        def __init__(self, groups=None):
            self._groups = groups or {}

        def findGroup(self, name):
            return self._groups.get(name)

    sar_group = _Group(
        groups={
            GroupNames.TRACKING: _Group(),
            GroupNames.MAP_TOOLS: _Group(),
            GroupNames.HELICOPTERS: _Group(),
        }
    )
    root = _Group(groups={GroupNames.ROOT: sar_group})
    project = SimpleNamespace(layerTreeRoot=lambda: root)
    monkeypatch.setattr(sartracker_module.QgsProject, "instance", MagicMock(return_value=project))

    SarTracker = sartracker_module.sartracker
    tracker = SarTracker.__new__(SarTracker)
    tracker._should_skip_layer_ops = MagicMock(return_value=False)
    tracker.layer_manager = SimpleNamespace(ensure_structure=MagicMock())
    tracker.layers_controller = SimpleNamespace(
        ensure_helicopter_layers=MagicMock(return_value=True),
        catalog=None,
    )
    tracker._log_exception = MagicMock()

    SarTracker._recover_missing_layers(tracker)

    tracker.layer_manager.ensure_structure.assert_not_called()
    tracker.layers_controller.ensure_helicopter_layers.assert_not_called()


def test_legacy_missing_configured_store_does_not_rebuild_runtime_state(tmp_path):
    """
    Spec: legacy startup should not advertise mission runtime paths when the
    configured mission store file no longer exists.
    """
    from sartracker import sartracker as sartracker_module

    missing_gpkg = tmp_path / "missing_mission" / "missing_mission.gpkg"

    SarTracker = sartracker_module.sartracker
    tracker = SarTracker.__new__(SarTracker)
    tracker.layer_manager = SimpleNamespace(
        get_mission_store=lambda: str(missing_gpkg),
        get_mission_coordinators=lambda: "",
    )
    tracker.mission_storage = SimpleNamespace(
        ensure_backup_directory=MagicMock(return_value=None)
    )
    tracker.iface = MagicMock()
    tracker.sar_panel = MagicMock()
    tracker.mission_controller = SimpleNamespace(is_active=lambda: False)
    tracker._mission_gpkg_path = Path("/tmp/stale.gpkg")
    tracker._mission_directory = Path("/tmp/stale")
    tracker._mission_folder_name = "Stale Mission"
    tracker._mission_backup_directory = Path("/tmp/stale_backup")
    tracker._mission_attachments_dir = Path("/tmp/stale_attachments")
    tracker._mission_coordinators_cache = "Alice,Bob"
    tracker._metadata_collected = True
    tracker._update_mission_storage_status = MagicMock()
    tracker._check_mission_finalized = MagicMock(return_value=False)
    tracker._recover_missing_layers = MagicMock()
    tracker._collect_mission_metadata = MagicMock()
    tracker._log_exception = MagicMock()

    SarTracker._load_existing_mission_storage_state(tracker)

    assert tracker._mission_gpkg_path is None
    assert tracker._mission_directory is None
    assert tracker._mission_folder_name is None
    assert tracker._mission_backup_directory is None
    assert tracker._mission_attachments_dir is None
    assert tracker._mission_coordinators_cache in ("", None)
    assert tracker._metadata_collected is False


def test_legacy_sync_project_state_retries_after_failed_storage_load(monkeypatch):
    """
    Spec: transient failures in the legacy project-sync load path should not
    prevent the next sync attempt with the same project/store pair.
    """
    from sartracker import sartracker as sartracker_module

    SarTracker = sartracker_module.sartracker
    tracker = SarTracker.__new__(SarTracker)
    tracker._is_unloading = False
    tracker._app_is_quitting = False
    tracker._last_project_signature = ""
    tracker.sar_panel = object()
    tracker.layers_controller = None
    tracker.iface = MagicMock()
    tracker._log_exception = MagicMock()

    project = SimpleNamespace(fileName=lambda: "/tmp/test.qgz")
    monkeypatch.setattr(sartracker_module.QgsProject, "instance", MagicMock(return_value=project))

    tracker.layer_manager = SimpleNamespace(
        get_mission_store=lambda: "/tmp/mission.gpkg",
        on_project_read=MagicMock(),
        is_sar_project=lambda: True,
        ensure_structure=MagicMock(),
    )
    tracker._load_existing_mission_storage_state = MagicMock(
        side_effect=[RuntimeError("transient load failure"), None]
    )

    SarTracker._sync_project_state(tracker, reason="first")
    SarTracker._sync_project_state(tracker, reason="retry")

    assert tracker._load_existing_mission_storage_state.call_count == 2


def test_on_project_read_delegates_to_sync_project_state():
    """
    The project-read hook should route through sync_project_state() with a
    stable reason label so startup diagnostics stay understandable.
    """
    from sartracker.controllers.mission_lifecycle_controller import MissionLifecycleController

    controller = MissionLifecycleController(iface=_iface_stub())
    controller.sync_project_state = MagicMock(return_value=True)

    controller.on_project_read()

    controller.sync_project_state.assert_called_once_with(reason="projectRead")


def test_on_new_project_created_delegates_to_sync_project_state():
    """
    The new-project hook should route through sync_project_state() so mission
    session state is refreshed consistently on project resets.
    """
    from sartracker.controllers.mission_lifecycle_controller import MissionLifecycleController

    controller = MissionLifecycleController(iface=_iface_stub())
    controller.sync_project_state = MagicMock(return_value=True)

    controller.on_new_project_created()

    controller.sync_project_state.assert_called_once_with(reason="newProjectCreated")


def test_update_project_path_tracks_saved_project(monkeypatch):
    """
    update_project_path() should mirror the active QGIS project file into
    lifecycle session state for diagnostics and archive flows.
    """
    from pathlib import Path
    from sartracker.controllers import mission_lifecycle_controller as module
    from sartracker.controllers.mission_lifecycle_controller import MissionLifecycleController

    project = SimpleNamespace(fileName=lambda: "/tmp/mission_alpha.qgz")
    monkeypatch.setattr(module.QgsProject, "instance", MagicMock(return_value=project))

    controller = MissionLifecycleController(iface=_iface_stub())

    controller.update_project_path()

    assert controller.get_session_state().project_path == Path("/tmp/mission_alpha.qgz")


def test_sync_project_state_retries_after_failed_storage_load(monkeypatch):
    """
    Spec: a transient storage-load failure should not poison future syncs with
    the same project/store signature; the next sync should be allowed to retry.
    """
    from sartracker.controllers import mission_lifecycle_controller as module
    from sartracker.controllers.mission_lifecycle_controller import MissionLifecycleController

    project = SimpleNamespace(fileName=lambda: "/tmp/test.qgz")
    monkeypatch.setattr(module.QgsProject, "instance", MagicMock(return_value=project))

    layer_manager = SimpleNamespace(
        get_mission_store=lambda: "/tmp/mission.gpkg",
        on_project_read=MagicMock(),
        is_sar_project=lambda: True,
        ensure_structure=MagicMock(),
    )

    controller = MissionLifecycleController(
        iface=_iface_stub(),
        layer_manager=layer_manager,
    )
    controller.load_existing_storage_state = MagicMock(
        side_effect=[RuntimeError("transient load failure"), False]
    )

    assert controller.sync_project_state(reason="first") is True
    assert controller.sync_project_state(reason="retry") is True
    assert controller.load_existing_storage_state.call_count == 2


@pytest.mark.xfail(
    strict=True,
    reason="prepare_new_mission() reuses existing mission directories and leaves stale files behind when mission names collide",
)
def test_spec_start_fresh_with_same_name_removes_stale_attachment_files(tmp_path):
    """
    Spec: starting fresh with an existing mission name should produce a clean
    mission workspace instead of preserving stale attachments from the old run.
    """
    from sartracker.utils.mission_storage import MissionStorageHelper

    class _LayerManager:
        def set_mission_finalized(self, _value):
            return None

        def set_mission_coordinators(self, _value):
            return None

        def set_resume_timestamp(self, _value):
            return None

        def set_mission_store(self, _value):
            return None

        def ensure_structure(self, auto_migrate=False):
            return None

    class _Config:
        def get_mission_primary_root(self):
            return str(tmp_path / "primary")

        def get_mission_backup_root(self):
            return str(tmp_path / "backup")

    stale_dir = tmp_path / "primary" / "Mission_Alpha" / "attachments"
    stale_dir.mkdir(parents=True)
    stale_file = stale_dir / "stale.txt"
    stale_file.write_text("old mission artifact")

    helper = MissionStorageHelper(layer_manager=_LayerManager(), config_store=_Config())
    paths = helper.prepare_new_mission("Mission Alpha")

    assert paths.attachments_dir.exists()
    assert list(paths.attachments_dir.iterdir()) == []


def test_finalize_request_rejects_active_mission_before_archive_start(monkeypatch):
    """
    Finalization should be blocked while a mission is still active so operators
    cannot archive mid-mission by accident.
    """
    from pathlib import Path
    from sartracker import sartracker as sartracker_module

    SarTracker = sartracker_module.sartracker
    tracker = SarTracker.__new__(SarTracker)
    tracker.iface = MagicMock()
    tracker.sar_panel = MagicMock()
    tracker.layer_manager = MagicMock()
    tracker.mission_controller = SimpleNamespace(is_active=lambda: True)
    tracker._mission_gpkg_path = Path("/tmp/mission.gpkg")
    tracker._mission_directory = Path("/tmp")
    tracker._is_finalizing = False
    tracker._check_mission_finalized = MagicMock(return_value=False)
    tracker._start_archive_task = MagicMock()
    tracker._notify = MagicMock()

    SarTracker._on_finalize_mission_requested(tracker)

    tracker._start_archive_task.assert_not_called()
    tracker._notify.assert_called()


def test_new_lifecycle_finalize_request_keeps_in_progress_guard_when_archive_starts(monkeypatch):
    """
    The extracted lifecycle controller should keep its finalization guard raised
    after successfully starting an async archive task.
    """
    from sartracker.controllers import mission_lifecycle_controller as module
    from sartracker.controllers.mission_lifecycle_controller import MissionLifecycleController
    from sartracker.utils.mission_storage import MissionPaths

    project = MagicMock()
    project.fileName.return_value = "/tmp/test.qgz"
    project.write.return_value = True
    monkeypatch.setattr(module.QgsProject, "instance", MagicMock(return_value=project))

    controller = MissionLifecycleController(
        iface=_iface_stub(),
        mission_controller=SimpleNamespace(is_active=lambda: False),
    )
    controller._update_session_state(
        mission_name="Mission Alpha",
        mission_dir=Path("/tmp/mission_alpha"),
        attachments_dir=Path("/tmp/mission_alpha/attachments"),
        backup_dir=Path("/tmp/backup"),
        gpkg_path=Path("/tmp/mission_alpha/mission_alpha.gpkg"),
    )
    controller.start_archive_task = MagicMock(return_value=True)
    controller._warn_uncommitted_edits = MagicMock(return_value=[])
    controller.check_finalized = MagicMock(return_value=False)

    result = controller.on_finalize_requested()

    assert result is True
    assert controller._get_is_finalizing() is True
    controller.start_archive_task.assert_called_once()


def test_new_lifecycle_finalize_request_requires_saved_project(monkeypatch):
    """
    Finalization should fail fast on the extracted controller path when the
    QGIS project has never been saved.
    """
    from sartracker.controllers import mission_lifecycle_controller as module
    from sartracker.controllers.mission_lifecycle_controller import MissionLifecycleController

    project = MagicMock()
    project.fileName.return_value = ""
    monkeypatch.setattr(module.QgsProject, "instance", MagicMock(return_value=project))

    controller = MissionLifecycleController(
        iface=_iface_stub(),
        mission_controller=SimpleNamespace(is_active=lambda: False),
    )
    controller._update_session_state(
        mission_name="Mission Alpha",
        mission_dir=Path("/tmp/mission_alpha"),
        attachments_dir=Path("/tmp/mission_alpha/attachments"),
        backup_dir=Path("/tmp/backup"),
        gpkg_path=Path("/tmp/mission_alpha/mission_alpha.gpkg"),
    )
    controller.start_archive_task = MagicMock(return_value=True)
    controller.check_finalized = MagicMock(return_value=False)

    result = controller.on_finalize_requested()

    assert result is False
    assert controller._get_is_finalizing() is False
    controller.start_archive_task.assert_not_called()


def test_new_lifecycle_finalize_request_clears_guard_when_archive_start_fails(monkeypatch):
    """
    If archive startup fails, the extracted controller should release the
    finalization guard so the operator can retry.
    """
    from sartracker.controllers import mission_lifecycle_controller as module
    from sartracker.controllers.mission_lifecycle_controller import MissionLifecycleController

    project = MagicMock()
    project.fileName.return_value = "/tmp/test.qgz"
    project.write.return_value = True
    monkeypatch.setattr(module.QgsProject, "instance", MagicMock(return_value=project))

    controller = MissionLifecycleController(
        iface=_iface_stub(),
        mission_controller=SimpleNamespace(is_active=lambda: False),
        mission_storage_controller=SimpleNamespace(start_archive_task=lambda **kwargs: False),
    )
    controller._update_session_state(
        mission_name="Mission Alpha",
        mission_dir=Path("/tmp/mission_alpha"),
        attachments_dir=Path("/tmp/mission_alpha/attachments"),
        backup_dir=Path("/tmp/backup"),
        gpkg_path=Path("/tmp/mission_alpha/mission_alpha.gpkg"),
    )
    controller._warn_uncommitted_edits = MagicMock(return_value=[])
    controller.check_finalized = MagicMock(return_value=False)

    result = controller.on_finalize_requested()

    assert result is False
    assert controller._get_is_finalizing() is False


def test_start_archive_task_async_success_keeps_finalization_guard_raised(tmp_path):
    """
    When async archive startup succeeds, the extracted controller should keep
    its finalization guard raised until success/failure callback.
    """
    from sartracker.controllers.mission_lifecycle_controller import MissionLifecycleController
    from sartracker.utils.mission_storage import MissionPaths

    mission_dir = tmp_path / "mission_alpha"
    mission_dir.mkdir()
    gpkg_path = mission_dir / "mission_alpha.gpkg"
    gpkg_path.touch()

    paths = MissionPaths(
        name="Mission Alpha",
        mission_dir=mission_dir,
        attachments_dir=mission_dir / "attachments",
        backup_dir=tmp_path / "backup",
        gpkg_path=gpkg_path,
    )

    controller = MissionLifecycleController(
        iface=_iface_stub(),
        mission_storage_controller=SimpleNamespace(
            start_archive_task=lambda **kwargs: True
        ),
    )
    controller._set_is_finalizing(True)
    controller._start_finalization_watchdog = MagicMock()

    assert controller.start_archive_task(paths, project_path=Path("/tmp/test.qgz")) is True
    assert controller._get_is_finalizing() is True


def test_on_archive_complete_marks_finalized_only_when_archive_exists(tmp_path):
    """
    Archive completion should flip finalized state only after the archive path is
    real and validation can proceed.
    """
    from sartracker.controllers.mission_lifecycle_controller import MissionLifecycleController
    import zipfile

    mission_dir = tmp_path / "mission_alpha"
    mission_dir.mkdir()
    gpkg_path = mission_dir / "mission_alpha.gpkg"
    gpkg_path.write_text("gpkg placeholder")
    archive_path = tmp_path / "mission_finalized.zip"
    with zipfile.ZipFile(archive_path, "w") as zipf:
        zipf.writestr("Mission Alpha/mission_alpha.gpkg", "gpkg placeholder")

    controller = MissionLifecycleController(iface=_iface_stub())
    controller._update_session_state(
        mission_name="Mission Alpha",
        mission_dir=mission_dir,
        attachments_dir=mission_dir / "attachments",
        backup_dir=tmp_path / "backup",
        gpkg_path=gpkg_path,
    )

    controller.on_archive_complete(str(archive_path))

    snapshot = controller.status_snapshot()
    assert snapshot["is_finalized"] is True


def test_on_archive_complete_ignores_missing_archive_path():
    """
    Archive success callbacks with no real file must not mark the mission as
    finalized.
    """
    from sartracker.controllers.mission_lifecycle_controller import MissionLifecycleController

    controller = MissionLifecycleController(iface=_iface_stub())
    controller._update_session_state(
        mission_name="Mission Alpha",
        is_finalized=False,
    )

    controller.on_archive_complete("/tmp/definitely-missing-archive.zip")

    snapshot = controller.status_snapshot()
    assert snapshot["is_finalized"] is False


def test_on_archive_failed_clears_in_progress_guard():
    """
    Archive failures should release the in-progress guard on the extracted
    controller path.
    """
    from sartracker.controllers.mission_lifecycle_controller import MissionLifecycleController

    controller = MissionLifecycleController(iface=_iface_stub())
    controller._set_is_finalizing(True)

    controller.on_archive_failed("disk full")

    assert controller._get_is_finalizing() is False


def test_on_unlock_requested_returns_false_when_not_finalized():
    """
    Unlock requests should be ignored if the mission is not finalized.
    """
    from sartracker.controllers.mission_lifecycle_controller import MissionLifecycleController

    controller = MissionLifecycleController(
        iface=_iface_stub(),
        layer_manager=SimpleNamespace(is_mission_finalized=lambda: False),
    )

    result = controller.on_unlock_requested()

    assert result is False


def test_on_unlock_requested_rejects_unknown_admin(monkeypatch):
    """
    Unlock should be denied when an admin roster exists and the entered name is
    not on it.
    """
    from sartracker.controllers import mission_lifecycle_controller as module
    from sartracker.controllers.mission_lifecycle_controller import MissionLifecycleController

    monkeypatch.setattr(module.ConfigStore, "get_admin_list", lambda: ["Alice Admin"])
    monkeypatch.setattr(module.QInputDialog, "getText", lambda *args, **kwargs: ("Mallory", True))

    controller = MissionLifecycleController(
        iface=_iface_stub(),
        layer_manager=SimpleNamespace(is_mission_finalized=lambda: True),
    )
    controller.set_finalized = MagicMock(return_value=True)

    result = controller.on_unlock_requested()

    assert result is False
    controller.set_finalized.assert_not_called()


def test_on_unlock_requested_with_valid_admin_unlocks(monkeypatch):
    """
    Unlock should succeed when the mission is finalized and a valid admin name
    is provided.
    """
    from sartracker.controllers import mission_lifecycle_controller as module
    from sartracker.controllers.mission_lifecycle_controller import MissionLifecycleController

    monkeypatch.setattr(module.ConfigStore, "get_admin_list", lambda: ["Alice Admin"])
    monkeypatch.setattr(module.QInputDialog, "getText", lambda *args, **kwargs: ("Alice Admin", True))

    controller = MissionLifecycleController(
        iface=_iface_stub(),
        layer_manager=SimpleNamespace(is_mission_finalized=lambda: True),
    )
    controller.set_finalized = MagicMock(return_value=True)

    result = controller.on_unlock_requested()

    assert result is True
    controller.set_finalized.assert_called_once_with(False, finalized_by="Alice Admin")


def test_paused_mission_prompt_cancel_clears_saved_state(monkeypatch):
    """
    Declining the paused-mission resume prompt should clear the saved paused
    state so the operator is not nagged again on the next startup.
    """
    from sartracker import sartracker as sartracker_module

    SarTracker = sartracker_module.sartracker
    tracker = SarTracker.__new__(SarTracker)
    tracker._is_unloading = False
    tracker._app_is_quitting = False
    tracker.sar_panel = MagicMock()
    tracker.iface = MagicMock()
    tracker.mission_controller = MagicMock(
        load_saved_state=MagicMock(return_value={"name": "Mission 1"}),
        clear_saved_state=MagicMock(),
    )

    monkeypatch.setattr(sartracker_module, "MissionResumeDialog", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(sartracker_module, "dialog_exec", lambda _dialog: object())

    SarTracker._check_for_paused_mission(tracker)

    tracker.mission_controller.clear_saved_state.assert_called_once_with()


def test_legacy_load_existing_storage_state_without_store_clears_runtime_paths():
    """
    Legacy startup path should clear mission runtime paths when no mission store
    is configured in the current project.
    """
    from sartracker import sartracker as sartracker_module

    SarTracker = sartracker_module.sartracker
    tracker = SarTracker.__new__(SarTracker)
    tracker.layer_manager = SimpleNamespace(get_mission_store=lambda: None)
    tracker._mission_gpkg_path = Path("/tmp/stale.gpkg")
    tracker._mission_directory = Path("/tmp/stale")
    tracker._mission_folder_name = "Stale Mission"
    tracker._mission_backup_directory = Path("/tmp/stale_backup")
    tracker._mission_attachments_dir = Path("/tmp/stale_attachments")
    tracker._update_mission_storage_status = MagicMock()

    SarTracker._load_existing_mission_storage_state(tracker)

    assert tracker._mission_gpkg_path is None
    assert tracker._mission_directory is None
    assert tracker._mission_folder_name is None
    assert tracker._mission_backup_directory is None
    assert tracker._mission_attachments_dir is None
    tracker._update_mission_storage_status.assert_called_once_with(active=False)


def test_legacy_collect_mission_metadata_persists_selection(monkeypatch):
    """
    Legacy metadata collection should cache persisted coordinators when the
    dialog is accepted successfully.
    """
    from sartracker import sartracker as sartracker_module

    class _Dialog:
        def __init__(self, *args, **kwargs):
            return None

        def selected_coordinators(self):
            return ["Alice", "Bob"]

        def pending_entry(self):
            return None

        def updated_roster(self):
            return ["Alice", "Bob"]

        def resume_timestamp(self):
            return None

        def all_entries(self):
            return ["Alice", "Bob"]

    SarTracker = sartracker_module.sartracker
    tracker = SarTracker.__new__(SarTracker)
    tracker.layer_manager = SimpleNamespace(
        get_mission_coordinators=lambda: "",
        set_mission_coordinators=MagicMock(),
    )
    tracker.iface = MagicMock()
    tracker._mission_coordinators_cache = ""
    tracker._metadata_collected = False

    monkeypatch.setattr(sartracker_module.ConfigStore, "get_coordinator_list", lambda: ["Alice", "Bob"])
    monkeypatch.setattr(sartracker_module.ConfigStore, "set_coordinator_roster", lambda _value: None)
    monkeypatch.setattr(sartracker_module, "MissionMetadataDialog", _Dialog)
    monkeypatch.setattr(sartracker_module, "dialog_exec", lambda _dialog: sartracker_module.DialogAccepted)

    SarTracker._collect_mission_metadata(
        tracker,
        mode="resume",
        allow_resume_time=True,
        preselected=None,
    )

    tracker.layer_manager.set_mission_coordinators.assert_called_once_with("Alice,Bob")
    assert tracker._mission_coordinators_cache == "Alice,Bob"
    assert tracker._metadata_collected is True


def test_legacy_handle_resume_prepare_failure_clears_runtime_state(tmp_path):
    """
    Spec: if legacy resume recovery falls back to Start Fresh and that fresh
    setup fails, the old mission runtime state should be cleared.
    """
    from sartracker import sartracker as sartracker_module

    gpkg_path = tmp_path / "missing_resume.gpkg"

    SarTracker = sartracker_module.sartracker
    tracker = SarTracker.__new__(SarTracker)
    tracker.layer_manager = SimpleNamespace(get_mission_store=lambda: str(gpkg_path))
    tracker.mission_storage = SimpleNamespace(
        handle_resume=MagicMock(side_effect=FileNotFoundError("missing store"))
    )
    tracker.iface = MagicMock()
    tracker._log_exception = MagicMock()
    tracker._prepare_new_mission_storage = MagicMock(return_value=None)
    tracker._mission_gpkg_path = Path("/tmp/stale.gpkg")
    tracker._mission_directory = Path("/tmp/stale")
    tracker._mission_folder_name = "Stale Mission"
    tracker._mission_backup_directory = Path("/tmp/stale_backup")
    tracker._mission_attachments_dir = Path("/tmp/stale_attachments")
    tracker._mission_coordinators_cache = "Alice"
    tracker._metadata_collected = True

    SarTracker._handle_mission_resume_storage(tracker, "Replacement Mission")

    assert tracker._mission_gpkg_path is None
    assert tracker._mission_directory is None
    assert tracker._mission_folder_name is None
    assert tracker._mission_backup_directory is None
    assert tracker._mission_attachments_dir is None
    assert tracker._mission_coordinators_cache in ("", None)
    assert tracker._metadata_collected is False


def test_legacy_no_store_clears_cached_metadata_flags():
    """
    Spec: if no mission store is configured, the legacy startup path should
    also clear cached coordinator metadata instead of leaving stale mission
    context behind.
    """
    from sartracker import sartracker as sartracker_module

    SarTracker = sartracker_module.sartracker
    tracker = SarTracker.__new__(SarTracker)
    tracker.layer_manager = SimpleNamespace(get_mission_store=lambda: None)
    tracker._mission_gpkg_path = Path("/tmp/stale.gpkg")
    tracker._mission_directory = Path("/tmp/stale")
    tracker._mission_folder_name = "Stale Mission"
    tracker._mission_backup_directory = Path("/tmp/stale_backup")
    tracker._mission_attachments_dir = Path("/tmp/stale_attachments")
    tracker._mission_coordinators_cache = "Alice,Bob"
    tracker._metadata_collected = True
    tracker._update_mission_storage_status = MagicMock()

    SarTracker._load_existing_mission_storage_state(tracker)

    assert tracker._mission_coordinators_cache in ("", None)
    assert tracker._metadata_collected is False


def test_legacy_collect_mission_metadata_does_not_claim_success_when_persist_fails(monkeypatch):
    """
    Spec: legacy metadata collection should not mark success if coordinator
    persistence fails.
    """
    from sartracker import sartracker as sartracker_module

    class _Dialog:
        def __init__(self, *args, **kwargs):
            return None

        def selected_coordinators(self):
            return ["Alice"]

        def pending_entry(self):
            return None

        def updated_roster(self):
            return ["Alice"]

        def resume_timestamp(self):
            return None

        def all_entries(self):
            return ["Alice"]

    SarTracker = sartracker_module.sartracker
    tracker = SarTracker.__new__(SarTracker)
    tracker.layer_manager = SimpleNamespace(
        get_mission_coordinators=lambda: "",
        set_mission_coordinators=MagicMock(side_effect=RuntimeError("project variable write failed")),
    )
    tracker.iface = MagicMock()
    tracker._mission_coordinators_cache = ""
    tracker._metadata_collected = False

    monkeypatch.setattr(sartracker_module.ConfigStore, "get_coordinator_list", lambda: ["Alice"])
    monkeypatch.setattr(sartracker_module.ConfigStore, "set_coordinator_roster", lambda _value: None)
    monkeypatch.setattr(sartracker_module, "MissionMetadataDialog", _Dialog)
    monkeypatch.setattr(sartracker_module, "dialog_exec", lambda _dialog: sartracker_module.DialogAccepted)
    monkeypatch.setattr(sartracker_module, "warning", lambda *args, **kwargs: None)

    SarTracker._collect_mission_metadata(
        tracker,
        mode="resume",
        allow_resume_time=True,
        preselected=None,
    )

    assert tracker._mission_coordinators_cache in ("", None)
    assert tracker._metadata_collected is False


def test_paused_mission_resume_success_shows_panel(monkeypatch):
    """
    Accepting a valid paused-mission restore should surface the SAR panel and
    leave saved state alone.
    """
    from sartracker import sartracker as sartracker_module

    accepted = getattr(sartracker_module, "DialogAccepted")

    SarTracker = sartracker_module.sartracker
    tracker = SarTracker.__new__(SarTracker)
    tracker._is_unloading = False
    tracker._app_is_quitting = False
    tracker.sar_panel = MagicMock()
    tracker.iface = MagicMock()
    tracker.mission_controller = MagicMock(
        load_saved_state=MagicMock(return_value={"name": "Mission 1"}),
        restore_from_state=MagicMock(return_value=True),
        clear_saved_state=MagicMock(),
    )

    monkeypatch.setattr(sartracker_module, "MissionResumeDialog", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(sartracker_module, "dialog_exec", lambda _dialog: accepted)
    monkeypatch.setattr(sartracker_module, "success", lambda *args, **kwargs: None)

    SarTracker._check_for_paused_mission(tracker)

    tracker.sar_panel.show.assert_called_once_with()
    tracker.mission_controller.clear_saved_state.assert_not_called()


def test_legacy_start_fresh_prepare_failure_clears_runtime_paths(tmp_path):
    """
    Spec: if legacy Start Fresh preparation fails, the old mission runtime paths
    should not remain advertised in memory.
    """
    from sartracker import sartracker as sartracker_module

    SarTracker = sartracker_module.sartracker
    tracker = SarTracker.__new__(SarTracker)
    tracker.layer_manager = SimpleNamespace(get_mission_store=lambda: str(tmp_path / "existing.gpkg"))
    tracker.iface = MagicMock()
    tracker.sar_panel = MagicMock()
    tracker.mission_controller = SimpleNamespace(
        clear_saved_state=MagicMock(),
        is_active=lambda: False,
    )
    tracker._mission_gpkg_path = Path("/tmp/stale.gpkg")
    tracker._mission_directory = Path("/tmp/stale")
    tracker._mission_folder_name = "Stale Mission"
    tracker._mission_backup_directory = Path("/tmp/stale_backup")
    tracker._mission_attachments_dir = Path("/tmp/stale_attachments")
    tracker._show_resume_mission_prompt = MagicMock(return_value=False)
    tracker._prompt_new_mission_name = MagicMock(return_value="Fresh Mission")
    tracker._prepare_new_mission_storage = MagicMock(return_value=None)
    tracker._update_mission_storage_status = MagicMock()
    tracker._check_mission_finalized = MagicMock(return_value=False)

    existing = Path(tmp_path) / "existing.gpkg"
    existing.touch()

    SarTracker._load_existing_mission_storage_state(tracker)

    assert tracker._mission_gpkg_path is None
    assert tracker._mission_directory is None
    assert tracker._mission_folder_name is None
    assert tracker._mission_backup_directory is None
    assert tracker._mission_attachments_dir is None


def test_paused_mission_restore_exception_clears_saved_state(monkeypatch):
    """
    Exceptions during paused-mission restore should clear saved state so the
    same broken payload does not keep reappearing.
    """
    from sartracker import sartracker as sartracker_module

    accepted = getattr(sartracker_module, "DialogAccepted")

    SarTracker = sartracker_module.sartracker
    tracker = SarTracker.__new__(SarTracker)
    tracker._is_unloading = False
    tracker._app_is_quitting = False
    tracker.sar_panel = MagicMock()
    tracker.iface = MagicMock()
    tracker.mission_controller = MagicMock(
        load_saved_state=MagicMock(return_value={"name": "Mission 1"}),
        restore_from_state=MagicMock(side_effect=RuntimeError("broken state")),
        clear_saved_state=MagicMock(),
    )

    monkeypatch.setattr(sartracker_module, "MissionResumeDialog", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(sartracker_module, "dialog_exec", lambda _dialog: accepted)
    monkeypatch.setattr(sartracker_module, "error", lambda *args, **kwargs: None)

    SarTracker._check_for_paused_mission(tracker)

    tracker.mission_controller.clear_saved_state.assert_called_once_with()


def test_malformed_paused_state_clears_saved_state_when_dialog_setup_fails(monkeypatch):
    """
    Spec: if the paused-mission resume dialog cannot even be constructed from
    saved state, that saved payload should be cleared to avoid repeated startup
    failures.
    """
    from sartracker import sartracker as sartracker_module

    SarTracker = sartracker_module.sartracker
    tracker = SarTracker.__new__(SarTracker)
    tracker._is_unloading = False
    tracker._app_is_quitting = False
    tracker.sar_panel = MagicMock()
    tracker.iface = MagicMock()
    tracker.mission_controller = MagicMock(
        load_saved_state=MagicMock(return_value={"broken": object()}),
        clear_saved_state=MagicMock(),
    )

    monkeypatch.setattr(
        sartracker_module,
        "MissionResumeDialog",
        MagicMock(side_effect=ValueError("invalid paused mission payload")),
    )
    monkeypatch.setattr(sartracker_module, "error", lambda *args, **kwargs: None)

    SarTracker._check_for_paused_mission(tracker)

    tracker.mission_controller.clear_saved_state.assert_called_once_with()


def test_handle_mission_resume_refreshes_finalized_state(tmp_path):
    """
    Spec: resuming a non-finalized mission should clear any stale finalized flag
    left over from a previous session snapshot.
    """
    from sartracker.controllers.mission_lifecycle_controller import MissionLifecycleController
    from sartracker.utils.mission_storage import MissionPaths

    gpkg_path = tmp_path / "mission_resume" / "mission_resume.gpkg"
    gpkg_path.parent.mkdir(parents=True)
    gpkg_path.touch()

    mission_paths = MissionPaths(
        name="mission_resume",
        mission_dir=gpkg_path.parent,
        attachments_dir=gpkg_path.parent / "attachments",
        backup_dir=gpkg_path.parent / "backup",
        gpkg_path=gpkg_path,
    )

    layer_manager = _LayerManagerStub(store_path=str(gpkg_path), coordinators="")
    layer_manager.is_mission_finalized = lambda: False

    controller = MissionLifecycleController(
        iface=_iface_stub(),
        layer_manager=layer_manager,
        mission_storage=SimpleNamespace(handle_resume=lambda _path: mission_paths),
    )
    controller._update_session_state(is_finalized=True)

    assert controller.handle_mission_resume("mission_resume") is True
    assert controller.status_snapshot()["is_finalized"] is False


def test_starting_new_mission_from_paused_state_is_rejected():
    """
    Spec: a paused mission should require explicit resume/finish/abandon flow,
    not silent replacement by starting a second mission.
    """
    from sartracker.controllers.mission_controller import MissionController

    controller = MissionController()
    controller.start_mission("Original Mission")
    controller.pause_mission()

    with pytest.raises(RuntimeError):
        controller.start_mission("Replacement Mission")


@pytest.mark.xfail(
    strict=True,
    reason="Auto-save currently reports success when async backup merely starts rather than completes",
)
def test_spec_autosave_waits_for_backup_completion_before_reporting_success(monkeypatch):
    """
    Spec: project-save success is not the same as mission-backup success.
    Operators should not get a green autosave signal until backup completion is known.
    """
    from sartracker import sartracker as sartracker_module
    from qgis.core import QgsProject

    SarTracker = sartracker_module.sartracker
    tracker = SarTracker.__new__(SarTracker)
    tracker._is_unloading = False
    tracker._app_is_quitting = False
    tracker._log_exception = MagicMock()
    tracker.iface = MagicMock()
    tracker.sar_panel = MagicMock()
    tracker.layer_manager = MagicMock(validate_persistence=MagicMock(return_value={}))

    # In current code this boolean is treated as "backup succeeded", but in the
    # async path it really means "backup task accepted/started".
    tracker._sync_mission_backup = MagicMock(return_value=True)

    project = MagicMock()
    project.fileName.return_value = "/tmp/test.qgz"
    project.write.return_value = True
    monkeypatch.setattr(QgsProject, "instance", MagicMock(return_value=project))

    success_calls = []
    monkeypatch.setattr(
        sartracker_module,
        "success",
        lambda *_args, **_kwargs: success_calls.append((_args, _kwargs)),
    )
    monkeypatch.setattr(sartracker_module, "warning", lambda *args, **kwargs: None)

    SarTracker._on_autosave_requested(tracker)

    assert success_calls == []
    tracker.sar_panel.update_autosave_status.assert_not_called()


def test_finalize_request_keeps_in_progress_guard_until_archive_callback(monkeypatch):
    """
    Spec: once archive start succeeds, duplicate finalization should stay blocked
    until the archive completion/failure callback clears the in-progress state.
    """
    from pathlib import Path
    from sartracker import sartracker as sartracker_module
    from qgis.core import QgsProject

    SarTracker = sartracker_module.sartracker
    tracker = SarTracker.__new__(SarTracker)
    tracker.iface = MagicMock()
    tracker.sar_panel = MagicMock()
    tracker.layer_manager = MagicMock()
    tracker.mission_controller = SimpleNamespace(is_active=lambda: False)
    tracker._mission_gpkg_path = Path("/tmp/mission.gpkg")
    tracker._mission_directory = Path("/tmp")
    tracker._is_finalizing = False
    tracker._check_mission_finalized = MagicMock(return_value=False)
    tracker._current_mission_paths = MagicMock(return_value=SimpleNamespace())
    tracker._warn_uncommitted_edits = MagicMock(return_value=[])
    tracker._start_archive_task = MagicMock()
    tracker._notify = MagicMock()

    project = MagicMock()
    project.fileName.return_value = "/tmp/test.qgz"
    project.write.return_value = True
    monkeypatch.setattr(QgsProject, "instance", MagicMock(return_value=project))

    SarTracker._on_finalize_mission_requested(tracker)

    tracker._start_archive_task.assert_called_once()
    assert tracker._is_finalizing is True


def test_failed_paused_restore_clears_saved_state_even_without_exception(monkeypatch):
    """
    Spec: if paused-mission restore is accepted but cannot be restored, the
    saved paused state should still be cleared to avoid an endless bad prompt.
    """
    from sartracker import sartracker as sartracker_module

    accepted = getattr(sartracker_module, "DialogAccepted")

    SarTracker = sartracker_module.sartracker
    tracker = SarTracker.__new__(SarTracker)
    tracker._is_unloading = False
    tracker._app_is_quitting = False
    tracker.sar_panel = MagicMock()
    tracker.iface = MagicMock()
    tracker.mission_controller = MagicMock(
        load_saved_state=MagicMock(return_value={"name": "Mission 1"}),
        restore_from_state=MagicMock(return_value=False),
        clear_saved_state=MagicMock(),
    )

    monkeypatch.setattr(sartracker_module, "MissionResumeDialog", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(sartracker_module, "dialog_exec", lambda _dialog: accepted)
    monkeypatch.setattr(sartracker_module, "success", lambda *args, **kwargs: None)

    SarTracker._check_for_paused_mission(tracker)

    tracker.mission_controller.clear_saved_state.assert_called_once_with()
