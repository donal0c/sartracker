# -*- coding: utf-8 -*-
"""Tests ensuring per-device tracking falls back to shared layers when unavailable."""

import types

import pytest

try:
    import qgis  # type: ignore  # noqa: F401
except ImportError:  # pragma: no cover - executed only in CI without QGIS
    from tests.test_layer_manager_resilience import (  # type: ignore
        _install_notify_stub,
        _install_qgis_stubs,
    )

    _install_qgis_stubs()
    _install_notify_stub()

from sartracker.controllers.layer_managers.tracking_manager import TrackingLayerManager
from sartracker.utils.exceptions import LayerError


def _build_manager():
    mgr = TrackingLayerManager.__new__(TrackingLayerManager)
    mgr.iface = types.SimpleNamespace()
    mgr.layer_manager = types.SimpleNamespace(_application_closing=False)
    mgr._layer_diag_enabled = False
    mgr.task_manager = None
    mgr._breadcrumb_task_id = None
    mgr._mission_generation = 0
    mgr.first_load = False
    mgr.USE_PER_DEVICE_POSITIONS = True
    mgr.USE_PER_DEVICE_TRAILS = True
    mgr._report_validation_warning = lambda *args, **kwargs: None
    mgr._log_tracking_event = lambda *args, **kwargs: None
    mgr._maybe_schedule_breadcrumb_task = lambda *args, **kwargs: False
    return mgr


def test_update_current_positions_falls_back_to_shared_when_per_device_unavailable():
    mgr = _build_manager()

    def _raise_unavailable():
        raise LayerError("Mission Store Required", title="Mission Store Required")

    mgr._ensure_per_device_ready = _raise_unavailable

    fake_layer = object()
    called = {}

    mgr._get_or_create_current_layer = lambda: fake_layer

    def _fake_delta(layer, positions):
        called["delta"] = (layer, positions)
        return (0, len(positions), 0)

    mgr._delta_update_current_positions = _fake_delta
    mgr._apply_current_positions_style = lambda layer: called.setdefault("styled", True)

    positions = [{
        "device_id": "dev1",
        "name": "Dev 1",
        "ts": "2024-01-01T00:00:00Z",
        "lat": 1.0,
        "lon": 2.0,
    }]

    mgr.update_current_positions(positions)

    assert called["delta"][0] is fake_layer
    assert called["delta"][1][0]["device_id"] == "dev1"
    assert called.get("styled") is True


def test_update_breadcrumbs_falls_back_to_shared_when_per_device_unavailable():
    mgr = _build_manager()

    def _raise_unavailable():
        raise LayerError("Mission Store Required", title="Mission Store Required")

    mgr._ensure_per_device_ready = _raise_unavailable

    fake_layer = object()
    mgr._get_or_create_breadcrumbs_layer = lambda: fake_layer

    applied = {}

    def _fake_apply(layer, segments, total_inputs, invalid_count, last_error, expected_generation=None):
        applied["layer"] = layer
        applied["segments"] = segments
        applied["total_inputs"] = total_inputs
        applied["invalid_count"] = invalid_count
        applied["last_error"] = last_error

    mgr._apply_breadcrumb_results = _fake_apply

    positions = [
        {
            "device_id": "dev1",
            "name": "Dev 1",
            "ts": "2024-01-01T00:00:00Z",
            "lat": 1.0,
            "lon": 2.0,
        },
        {
            "device_id": "dev1",
            "name": "Dev 1",
            "ts": "2024-01-01T00:05:00Z",
            "lat": 1.1,
            "lon": 2.1,
        },
    ]

    mgr.update_breadcrumbs(positions, time_gap_minutes=5)

    assert applied["layer"] is fake_layer
    assert applied["total_inputs"] == 2
    assert applied["invalid_count"] == 0
    assert applied["segments"]
