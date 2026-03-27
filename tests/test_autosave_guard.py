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


def test_autosave_persistence_warning_includes_layer_details(monkeypatch):
    """Persistence warning should include actionable layer identifiers."""
    from sartracker import sartracker as sartracker_module
    from qgis.core import QgsProject

    SarTracker = sartracker_module.sartracker
    tracker = SarTracker.__new__(SarTracker)
    tracker._is_unloading = False
    tracker._app_is_quitting = False
    tracker._sync_mission_backup = MagicMock(return_value=True)
    tracker._log_exception = MagicMock()
    tracker.iface = MagicMock()
    tracker.sar_panel = MagicMock()
    tracker.layer_manager = MagicMock(
        validate_persistence=MagicMock(
            return_value={
                "sar_tracks_current_positions": "memory",
                "sar_tracks_breadcrumbs": "memory",
            }
        )
    )

    project = MagicMock()
    project.fileName.return_value = "/tmp/test.qgz"
    project.write.return_value = True
    monkeypatch.setattr(QgsProject, "instance", MagicMock(return_value=project))

    warning_calls = []

    def _capture_warning(_bar, _title, message, duration=0):
        warning_calls.append((message, duration))

    monkeypatch.setattr(sartracker_module, "warning", _capture_warning)
    monkeypatch.setattr(sartracker_module, "success", lambda *args, **kwargs: None)

    SarTracker._on_autosave_requested(tracker)

    persistence_messages = [msg for msg, _ in warning_calls if "still in memory during auto-save" in msg]
    assert persistence_messages, "Expected a persistence warning message"
    assert "sar_tracks_current_positions" in persistence_messages[0]
    assert "sar_tracks_breadcrumbs" in persistence_messages[0]
    tracker.sar_panel.update_autosave_status.assert_called_once_with("warning")


def test_autosave_persistence_warning_distinguishes_missing_and_memory(monkeypatch):
    """Persistence warning should distinguish missing layers from memory-backed ones."""
    from sartracker import sartracker as sartracker_module
    from qgis.core import QgsProject

    SarTracker = sartracker_module.sartracker
    tracker = SarTracker.__new__(SarTracker)
    tracker._is_unloading = False
    tracker._app_is_quitting = False
    tracker._sync_mission_backup = MagicMock(return_value=True)
    tracker._log_exception = MagicMock()
    tracker.iface = MagicMock()
    tracker.sar_panel = MagicMock()
    tracker.layer_manager = MagicMock(
        validate_persistence=MagicMock(
            return_value={
                "sar_lines": "missing",
                "sar_breadcrumbs": "memory",
            }
        )
    )

    project = MagicMock()
    project.fileName.return_value = "/tmp/test.qgz"
    project.write.return_value = True
    monkeypatch.setattr(QgsProject, "instance", MagicMock(return_value=project))

    warning_calls = []

    def _capture_warning(_bar, _title, message, duration=0):
        warning_calls.append((message, duration))

    monkeypatch.setattr(sartracker_module, "warning", _capture_warning)
    monkeypatch.setattr(sartracker_module, "success", lambda *args, **kwargs: None)

    SarTracker._on_autosave_requested(tracker)

    persistence_messages = [msg for msg, _ in warning_calls if "auto-save" in msg]
    assert persistence_messages, "Expected a persistence warning message"
    message = persistence_messages[0]
    assert "1 in memory" in message
    assert "1 missing" in message
