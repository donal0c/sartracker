# -*- coding: utf-8 -*-
"""
Autosave guard tests.
"""
from unittest.mock import MagicMock


def test_autosave_handles_missing_panel(monkeypatch):
    """Autosave should not crash if SAR panel is missing."""
    from sartracker import sartracker as sartracker_module
    from qgis.core import QgsProject

    SarTracker = sartracker_module.sartracker
    tracker = SarTracker.__new__(SarTracker)
    tracker._is_unloading = False
    tracker._app_is_quitting = False
    tracker.sar_panel = None
    tracker.layer_manager = None
    tracker._sync_mission_backup = MagicMock(return_value=True)
    tracker._log_exception = MagicMock()
    tracker.iface = MagicMock()

    project = MagicMock()
    project.fileName.return_value = "/tmp/test.qgz"
    project.write.return_value = True
    monkeypatch.setattr(QgsProject, "instance", MagicMock(return_value=project))

    SarTracker._on_autosave_requested(tracker)
