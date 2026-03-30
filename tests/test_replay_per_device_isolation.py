# -*- coding: utf-8 -*-
"""Regression tests for replay temp-store isolation in per-device tracking."""

from types import SimpleNamespace

try:
    import qgis  # type: ignore  # noqa: F401
except ImportError:  # pragma: no cover - test env without QGIS
    from tests.test_layer_manager_resilience import (  # type: ignore
        _install_notify_stub,
        _install_qgis_stubs,
    )

    _install_qgis_stubs()
    _install_notify_stub()

from qgis.core import QgsVectorLayer

from sartracker.controllers.layer_managers.tracking_manager import TrackingLayerManager
from sartracker.controllers.per_item_layer_factory import ItemType, SAR_ITEM_TYPE


class _FakeLayer(QgsVectorLayer):
    """Small QgsVectorLayer-compatible double with source/custom-property support."""

    def __init__(self, *, device_id: str, item_type: str, source: str):
        super().__init__()
        self._source = source
        self.setCustomProperty("sartracker:device_id", device_id)
        self.setCustomProperty(SAR_ITEM_TYPE, item_type)

    def source(self):
        return self._source

    def isValid(self):
        return True


def _build_tracking_manager():
    manager = TrackingLayerManager.__new__(TrackingLayerManager)
    manager.iface = SimpleNamespace()
    manager.layer_manager = None
    manager._device_position_layers = {}
    manager._device_trail_layers = {}
    manager._device_generations = {}
    manager._per_device_factory = object()
    manager._per_device_migration_checked = True
    manager._per_device_layout_normalized = True
    manager._stale_layer_cache_events = 0
    manager._last_stale_layer_cache_event = None
    return manager


def test_require_mission_store_prefers_effective_store_path():
    manager = _build_tracking_manager()
    manager.layer_manager = SimpleNamespace(
        get_mission_store=lambda: "/tmp/live-mission.gpkg",
        get_effective_store_path=lambda: "/tmp/replay-temp.gpkg",
    )

    store_path = manager._require_mission_store("Per-device tracking")

    assert store_path == "/tmp/replay-temp.gpkg"


def test_layer_matches_effective_store_rejects_live_layer_during_replay():
    manager = _build_tracking_manager()
    manager.layer_manager = SimpleNamespace(
        get_mission_store=lambda: "/tmp/live-mission.gpkg",
        get_effective_store_path=lambda: "/tmp/replay-temp.gpkg",
    )

    live_layer = _FakeLayer(
        device_id="dev-1",
        item_type=ItemType.DEVICE_POSITION,
        source="/tmp/live-mission.gpkg|layername=pos_dev1",
    )
    assert manager._layer_matches_effective_store(live_layer) is False


def test_store_path_change_invalidates_per_device_caches():
    manager = _build_tracking_manager()
    manager._device_position_layers = {"dev-1": object()}
    manager._device_trail_layers = {"dev-1": object()}

    manager._on_store_path_changed("/tmp/replay-temp.gpkg")

    assert manager._per_device_factory is None
    assert manager._per_device_migration_checked is False
    assert manager._per_device_layout_normalized is False
    assert manager._device_position_layers == {}
    assert manager._device_trail_layers == {}
