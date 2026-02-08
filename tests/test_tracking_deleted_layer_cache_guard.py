# -*- coding: utf-8 -*-
"""Regression tests for stale/deleted per-device layer cache handling."""

try:
    import qgis  # type: ignore  # noqa: F401
except ImportError:  # pragma: no cover - test env without QGIS
    from tests.test_layer_manager_resilience import (  # type: ignore
        _install_notify_stub,
        _install_qgis_stubs,
    )

    _install_qgis_stubs()
    _install_notify_stub()

from sartracker.controllers.layer_managers.tracking_manager import TrackingLayerManager


class _DeletedLayer:
    def isValid(self):
        raise RuntimeError("wrapped C/C++ object of type QgsVectorLayer has been deleted")


class _LiveLayer:
    def isValid(self):
        return True


def _build_manager():
    mgr = TrackingLayerManager.__new__(TrackingLayerManager)
    mgr._device_position_layers = {}
    mgr._device_trail_layers = {}
    mgr._stale_layer_cache_events = 0
    mgr._last_stale_layer_cache_event = None
    mgr._get_device_layers_by_property = lambda _device_id: {"position": None, "trail": None}
    return mgr


def test_get_existing_device_position_layer_ignores_deleted_cached_layer():
    mgr = _build_manager()
    mgr._device_position_layers["dev-1"] = _DeletedLayer()

    layer = mgr._get_existing_device_position_layer("dev-1")

    assert layer is None
    assert "dev-1" not in mgr._device_position_layers
    assert mgr._stale_layer_cache_events == 1
    assert mgr._last_stale_layer_cache_event["layer_kind"] == "position"
    assert mgr._last_stale_layer_cache_event["device_id"] == "dev-1"


def test_get_existing_device_trail_layer_ignores_deleted_cached_layer():
    mgr = _build_manager()
    mgr._device_trail_layers["dev-1"] = _DeletedLayer()

    layer = mgr._get_existing_device_trail_layer("dev-1")

    assert layer is None
    assert "dev-1" not in mgr._device_trail_layers
    assert mgr._stale_layer_cache_events == 1
    assert mgr._last_stale_layer_cache_event["layer_kind"] == "trail"
    assert mgr._last_stale_layer_cache_event["device_id"] == "dev-1"


def test_ensure_device_position_layer_recovers_from_deleted_cache():
    mgr = _build_manager()
    mgr._device_position_layers["dev-1"] = _DeletedLayer()
    live = _LiveLayer()
    mgr._get_device_layers_by_property = lambda _device_id: {"position": live, "trail": None}
    mgr._get_per_device_factory = lambda: object()
    mgr._ensure_tracking_layer_placement = lambda *args, **kwargs: None
    mgr._ensure_tracking_layer_name = lambda *args, **kwargs: None

    layer = mgr._ensure_device_position_layer("dev-1", {"name": "Device 1"})

    assert layer is live
    assert mgr._device_position_layers["dev-1"] is live
    assert mgr._stale_layer_cache_events == 1


def test_tracking_diagnostics_include_stale_cache_event():
    mgr = _build_manager()
    mgr._device_position_layers["dev-1"] = _DeletedLayer()

    mgr._get_existing_device_position_layer("dev-1")
    diag = mgr.get_diagnostics()

    assert diag["status"] == "operational"
    assert diag["stale_layer_cache_events"] == 1
    assert diag["last_stale_layer_cache_event"]["device_id"] == "dev-1"
