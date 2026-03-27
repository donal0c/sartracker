# -*- coding: utf-8 -*-
"""Helpers for distinguishing real QGIS from the mock test harness."""

from __future__ import annotations

import sys
import types

import pytest


def has_real_qgis() -> bool:
    """Return True only when tests are running against a real QGIS runtime."""
    qgis_core = sys.modules.get("qgis.core")
    if qgis_core is None:
        try:
            import qgis.core as qgis_core  # type: ignore[no-redef]
        except Exception:
            return False

    if getattr(qgis_core, "__sartracker_mock_qgis__", False):
        return False

    if not isinstance(qgis_core, types.ModuleType):
        return False

    if not getattr(qgis_core, "__file__", None):
        return False

    qgs_project = getattr(qgis_core, "QgsProject", None)
    return qgs_project is not None and hasattr(qgs_project, "instance")


def require_real_qgis(reason: str = "Real QGIS runtime required") -> None:
    """Skip the current test or module unless real QGIS is available."""
    if not has_real_qgis():
        pytest.skip(reason, allow_module_level=True)
