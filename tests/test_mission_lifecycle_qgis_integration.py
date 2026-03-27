# -*- coding: utf-8 -*-
"""Real-QGIS integration tests for mission lifecycle project sync behavior."""

from pathlib import Path

import pytest

from sartracker.tests.qgis_runtime import require_real_qgis

require_real_qgis("Mission lifecycle QGIS integration tests require real QGIS runtime")
pytestmark = pytest.mark.qgis_required


class _MessageBar:
    def pushMessage(self, *_args, **_kwargs):
        return None


class _Iface:
    def messageBar(self):
        return _MessageBar()

    def mainWindow(self):
        return None


def _reset_project_state(project):
    """Restore shared QGIS project state between real-QGIS integration tests."""
    project.clear()
    try:
        project.setCustomVariables({})
    except Exception:
        pass


def test_sync_project_state_does_not_dirty_unsaved_non_sar_project():
    """
    Real-QGIS check: startup sync should not create the SAR root group in a
    fresh unsaved project with no mission store configured.
    """
    from qgis.core import QgsProject
    from sartracker.layers import GroupNames, LayerManager
    from sartracker.controllers.mission_lifecycle_controller import MissionLifecycleController

    controller = None
    try:
        project = QgsProject.instance()
        _reset_project_state(project)
        assert project.fileName() == ""

        layer_manager = LayerManager(_Iface())
        controller = MissionLifecycleController(
            iface=_Iface(),
            layer_manager=layer_manager,
        )
        result = controller.sync_project_state(reason="integration_unsaved")

        assert result is True
        assert project.layerTreeRoot().findGroup(GroupNames.ROOT) is None
        assert layer_manager.get_mission_store() is None
    finally:
        if controller is not None:
            controller.cleanup()
        _reset_project_state(QgsProject.instance())


def test_sync_project_state_ensures_sar_structure_when_mission_store_configured(tmp_path):
    """
    Real-QGIS check: once a mission store is configured, project sync should
    build the SAR layer/group structure automatically.
    """
    from qgis.core import QgsProject
    from sartracker.layers import GroupNames, LayerManager
    from sartracker.controllers.mission_lifecycle_controller import MissionLifecycleController

    controller = None
    try:
        project = QgsProject.instance()
        _reset_project_state(project)

        layer_manager = LayerManager(_Iface())
        controller = MissionLifecycleController(
            iface=_Iface(),
            layer_manager=layer_manager,
        )
        controller.load_existing_storage_state = lambda: False

        mission_store = Path(tmp_path) / "integration_sync.gpkg"
        layer_manager.set_mission_store(str(mission_store))

        result = controller.sync_project_state(reason="integration_store")

        assert result is True
        assert project.layerTreeRoot().findGroup(GroupNames.ROOT) is not None
        assert layer_manager.get_mission_store() == str(mission_store)
    finally:
        if controller is not None:
            controller.cleanup()
        _reset_project_state(QgsProject.instance())


def test_recover_missing_layers_rebuilds_missing_startup_groups():
    """
    Real-QGIS check: if the SAR root exists but startup-critical subgroups are
    missing, recovery should rebuild them without requiring manual Repair.
    """
    from qgis.core import QgsProject
    from sartracker.layers import GroupNames, LayerManager
    from sartracker import sartracker as sartracker_module

    try:
        project = QgsProject.instance()
        _reset_project_state(project)

        root = project.layerTreeRoot()
        sar_group = root.addGroup(GroupNames.ROOT)
        sar_group.addGroup(GroupNames.TRACKING)

        layer_manager = LayerManager(_Iface())

        SarTracker = sartracker_module.sartracker
        tracker = SarTracker.__new__(SarTracker)
        tracker._should_skip_layer_ops = lambda: False
        tracker.layer_manager = layer_manager
        tracker.layers_controller = type(
            "_LayersController",
            (),
            {
                "ensure_helicopter_layers": staticmethod(lambda: True),
                "catalog": None,
            },
        )()
        tracker._log_exception = lambda *_args, **_kwargs: None

        SarTracker._recover_missing_layers(tracker)

        restored_root = project.layerTreeRoot().findGroup(GroupNames.ROOT)
        assert restored_root is not None
        assert restored_root.findGroup(GroupNames.TRACKING) is not None
        assert restored_root.findGroup(GroupNames.MAP_TOOLS) is not None
        assert restored_root.findGroup(GroupNames.HELICOPTERS) is not None
    finally:
        _reset_project_state(QgsProject.instance())
