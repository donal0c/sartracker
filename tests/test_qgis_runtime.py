# -*- coding: utf-8 -*-
"""Tests for the Phase 0 QGIS runtime detection helper."""

from types import ModuleType, SimpleNamespace
import sys

import pytest


pytestmark = pytest.mark.mock_qgis_only


def test_has_real_qgis_false_when_module_missing(monkeypatch):
    """Missing qgis.core should be treated as no real QGIS runtime."""
    monkeypatch.delitem(sys.modules, "qgis.core", raising=False)

    from sartracker.tests.qgis_runtime import has_real_qgis

    assert has_real_qgis() is False


def test_has_real_qgis_false_for_mock_harness_module(monkeypatch):
    """Sentinel-marked fake qgis.core must not be mistaken for real QGIS."""
    fake_core = ModuleType("qgis.core")
    fake_core.__sartracker_mock_qgis__ = True
    monkeypatch.setitem(sys.modules, "qgis.core", fake_core)

    from sartracker.tests.qgis_runtime import has_real_qgis

    assert has_real_qgis() is False


def test_has_real_qgis_false_for_non_module_object(monkeypatch):
    """MagicMock-like objects in sys.modules should not count as real QGIS."""
    fake_core = SimpleNamespace(QgsProject=SimpleNamespace(instance=lambda: None))
    monkeypatch.setitem(sys.modules, "qgis.core", fake_core)

    from sartracker.tests.qgis_runtime import has_real_qgis

    assert has_real_qgis() is False


def test_has_real_qgis_true_for_module_with_qgsproject_instance(monkeypatch):
    """A real-looking module with QgsProject.instance should be accepted."""
    fake_core = ModuleType("qgis.core")
    fake_core.__file__ = "/Applications/QGIS.app/Contents/Resources/python/qgis/core/__init__.py"

    class _QgsProject:
        @staticmethod
        def instance():
            return object()

    fake_core.QgsProject = _QgsProject
    monkeypatch.setitem(sys.modules, "qgis.core", fake_core)

    from sartracker.tests.qgis_runtime import has_real_qgis

    assert has_real_qgis() is True
