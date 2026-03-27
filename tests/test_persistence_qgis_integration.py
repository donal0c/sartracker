# -*- coding: utf-8 -*-
"""QGIS integration tests for persistence validation behavior."""

from pathlib import Path

import pytest


@pytest.mark.qgis_required
def test_validate_persistence_ignores_missing_optional_layers_in_real_qgis(tmp_path):
    """
    Optional/lazy layers should not trigger persistence warnings when unused.

    This guards against noisy autosave warnings that can mask real persistence issues.
    """
    from sartracker.layers.manager import LayerManager

    class _MessageBar:
        def pushMessage(self, *_args, **_kwargs):
            return None

    class _Iface:
        def messageBar(self):
            return _MessageBar()

        def mainWindow(self):
            return None

    manager = LayerManager(_Iface())
    mission_store = Path(tmp_path) / "integration_mission.gpkg"
    manager.set_mission_store(str(mission_store))

    # Mirror plugin startup path: ensure schema-managed structure is present.
    assert manager.ensure_structure(auto_migrate=False) is True

    issues = manager.validate_persistence(quiet=True)
    assert issues == {}
