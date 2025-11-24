# -*- coding: utf-8 -*-
"""Unit tests for controllers.layer_catalog helper utilities."""

import json
import types

import pytest

from tests.test_layer_manager_resilience import _ensure_qgis


class DummySignal:
    def __init__(self):
        self.emitted = []

    def emit(self, *args):
        self.emitted.append(args)


class StubLayerDef:
    def __init__(self, layer_id, name, position=0):
        self.layer_id = layer_id
        self.name = name
        self.position = position


class StubGroupDef:
    def __init__(self, name, position=0, layers=None, subgroups=None):
        self.name = name
        self.position = position
        self.layers = layers or []
        self.subgroups = subgroups or []


def _install_catalog_module(monkeypatch):
    import importlib

    _ensure_qgis(monkeypatch)
    return importlib.import_module("sartracker.controllers.layer_catalog")


class MetadataStubLayerManager:
    def __init__(self, read_fail=False, write_fail=False):
        self.read_fail = read_fail
        self.write_fail = write_fail
        self._metadata = {}

    def ensure_structure(self):
        return None

    def get_layer_metadata(self, _layer_id):
        if self.read_fail:
            raise RuntimeError("read failure")
        return dict(self._metadata)

    def set_layer_metadata(self, _layer_id, metadata):
        if self.write_fail:
            raise RuntimeError("write failure")
        self._metadata = dict(metadata)


def _make_service(layer_catalog, layer_manager):
    svc = layer_catalog.LayerCatalogService.__new__(layer_catalog.LayerCatalogService)
    svc.layer_manager = layer_manager
    svc._layers = {
        "LAYER_ALPHA": layer_catalog.LayerInfo(
            id="LAYER_ALPHA",
            canonical_name="Alpha",
            group_id=layer_catalog.GroupNames.ROOT,
            qgis_layer_id="qgis::alpha"
        )
    }
    root_group = layer_catalog.LayerGroupInfo(
        id=layer_catalog.GroupNames.ROOT,
        name=layer_catalog.GroupNames.ROOT,
        order=0,
        parent_id=None,
        children=list(svc._layers.keys()),
        subgroups=[],
        visible=True,
        expanded=True
    )
    svc._groups = {root_group.id: root_group}
    svc.alias_changed = DummySignal()
    svc.layer_updated = DummySignal()
    svc._message_bar = None
    svc._pending_refresh_layers = set()
    svc._cleanup_in_progress = False
    svc._notify_error = lambda title, message: svc._notifications.append((title, message))
    svc._notify_warning = lambda title, message: svc._notifications.append((title, message))
    svc._notifications = []  # type: ignore[attr-defined]
    svc._task_manager = None
    svc._owned_task_manager = False
    svc._signal_connections = []
    svc._layer_signal_connections = {}
    svc._refresh_timer = None
    return svc


class StubTaskManager:
    def __init__(self):
        self.started = []
        self.cancelled = []
        self.cancel_all_called = False
        self._last_entry = None

    def start_task(self, task, on_complete, on_error, task_id):
        self.started.append(task_id)
        self._last_entry = (task, on_complete, on_error, task_id)
        return task_id

    def cancel_task(self, task_id):
        self.cancelled.append(task_id)
        return True

    def cancel_all(self):
        self.cancel_all_called = True


def test_catalog_cache_builder_builds_expected_structure(monkeypatch):
    layer_catalog = _install_catalog_module(monkeypatch)

    root_stub = StubGroupDef(
        name=layer_catalog.GroupNames.ROOT,
        position=0,
        layers=[StubLayerDef("LAYER_ALPHA", "Alpha Layer", position=1)],
        subgroups=[
            StubGroupDef(
                name="OPS",
                position=2,
                layers=[StubLayerDef("LAYER_BRAVO", "Bravo Layer", position=0)],
            )
        ],
    )
    monkeypatch.setattr(layer_catalog, "get_expected_structure", lambda: root_stub)

    class FakeLayer:
        def __init__(self, layer_id):
            self._layer_id = layer_id
            self._geometry_type = getattr(layer_catalog.QgsWkbTypes, "PointGeometry", 1)

        def isValid(self):
            return True

        def dataProvider(self):
            return types.SimpleNamespace(name=lambda: "memory")

        def featureCount(self):
            return 3

        def fields(self):
            return [types.SimpleNamespace(name=lambda: "name"), types.SimpleNamespace(name=lambda: "type")]

        def geometryType(self):
            return self._geometry_type

        def source(self):
            return f"memory::{self._layer_id}"

        def id(self):
            return f"qgis::{self._layer_id}"

    class FakeLayerManager:
        def get_layer(self, layer_id):
            return FakeLayer(layer_id)

        def get_layer_metadata(self, layer_id):
            return {
                "alias": f"Alias {layer_id}",
                "favorite": layer_id.endswith("O"),
                "display_order": 42,
                "updated_at": "2024-01-01T12:00:00",
            }

    project = layer_catalog.QgsProject.instance()
    builder = layer_catalog._CatalogCacheBuilder(FakeLayerManager(), project, layer_catalog.logger)

    result = builder.build()

    assert layer_catalog.GroupNames.ROOT in result.groups
    ops_group_id = f"{layer_catalog.GroupNames.ROOT}/OPS"
    assert ops_group_id in result.groups
    root_children = result.groups[layer_catalog.GroupNames.ROOT].children
    assert root_children == ["LAYER_ALPHA"]
    ops_children = result.groups[ops_group_id].children
    assert ops_children == ["LAYER_BRAVO"]

    assert set(result.layers.keys()) == {"LAYER_ALPHA", "LAYER_BRAVO"}
    alpha = result.layers["LAYER_ALPHA"]
    assert alpha.display_name == "Alias LAYER_ALPHA"
    assert alpha.feature_count == 3
    assert alpha.geometry_type == "Point"

    assert set(result.layer_refs.keys()) == {"LAYER_ALPHA", "LAYER_BRAVO"}


def test_build_layer_info_handles_provider_failures(monkeypatch):
    layer_catalog = _install_catalog_module(monkeypatch)

    class NoisyLayer:
        def __init__(self):
            self._calls = {"geometryType": 0}

        def dataProvider(self):
            raise RuntimeError("provider missing")

        def featureCount(self):
            raise RuntimeError("feature count broke")

        def fields(self):
            raise RuntimeError("fields missing")

        def geometryType(self):
            self._calls["geometryType"] += 1
            raise RuntimeError("geometry missing")

        def source(self):
            raise RuntimeError("source missing")

        def id(self):
            return "qgis::noisy"

    class FaultyLayerManager:
        def get_layer_metadata(self, _layer_id):
            raise RuntimeError("metadata failure")

    layer_def = types.SimpleNamespace(name="Faulty", position=5)
    project = layer_catalog.QgsProject.instance()
    info = layer_catalog.build_layer_info(
        layer_manager=FaultyLayerManager(),
        project=project,
        layer_id="LAYER_FAULTY",
        layer=NoisyLayer(),
        layer_def=layer_def,
        group_id=layer_catalog.GroupNames.ROOT,
        logger_instance=layer_catalog.logger,
    )

    assert info.provider == "unknown"
    assert info.feature_count == 0
    assert info.schema_fields == []
    assert info.geometry_type == ""
    assert info.data_source_uri == ""
    assert info.order == layer_def.position


def test_set_layer_alias_notifies_on_write_failure(monkeypatch):
    layer_catalog = _install_catalog_module(monkeypatch)
    manager = MetadataStubLayerManager(write_fail=True)
    svc = _make_service(layer_catalog, manager)

    with pytest.raises(RuntimeError):
        svc.set_layer_alias("LAYER_ALPHA", "New Alias")

    assert svc._notifications  # type: ignore[attr-defined]
    title, message = svc._notifications[0]  # type: ignore[index]
    assert "Layer Metadata" in title
    assert "set alias" in message
    assert svc._layers["LAYER_ALPHA"].alias is None


def test_set_layer_alias_returns_when_metadata_unavailable(monkeypatch):
    layer_catalog = _install_catalog_module(monkeypatch)
    manager = MetadataStubLayerManager(read_fail=True)
    svc = _make_service(layer_catalog, manager)

    result = svc.set_layer_alias("LAYER_ALPHA", "Alias")
    assert result is None
    assert svc._layers["LAYER_ALPHA"].alias is None
    assert svc._notifications  # type: ignore[attr-defined]


def test_dump_catalog_writes_file(monkeypatch, tmp_path):
    layer_catalog = _install_catalog_module(monkeypatch)
    manager = MetadataStubLayerManager()
    svc = _make_service(layer_catalog, manager)
    svc._layers["LAYER_BETA"] = layer_catalog.LayerInfo(
        id="LAYER_BETA",
        canonical_name="Beta",
        group_id=layer_catalog.GroupNames.ROOT,
        qgis_layer_id="qgis::beta",
        provider="ogr",
        feature_count=2
    )
    svc._groups[layer_catalog.GroupNames.ROOT].children.append("LAYER_BETA")
    svc.get_catalog_snapshot = lambda: {"status": "ok"}

    path = tmp_path / "catalog.json"
    svc.dump_catalog(str(path))
    data = json.loads(path.read_text())
    assert data["snapshot"] == {"status": "ok"}
    assert len(data["layers"]) == 2


def test_dump_catalog_handles_oserror(monkeypatch, tmp_path):
    layer_catalog = _install_catalog_module(monkeypatch)
    manager = MetadataStubLayerManager()
    svc = _make_service(layer_catalog, manager)

    def failing_open(*_args, **_kwargs):
        raise OSError("denied")

    monkeypatch.setattr("builtins.open", failing_open)
    svc.dump_catalog(str(tmp_path / "catalog.json"))
    assert svc._notifications  # type: ignore[attr-defined]
    assert "Catalog Dump Failed" in svc._notifications[-1][0]  # type: ignore[index]


def test_get_catalog_snapshot_warns_on_mission_store_error(monkeypatch):
    layer_catalog = _install_catalog_module(monkeypatch)

    class FailingStoreManager(MetadataStubLayerManager):
        def get_mission_store(self):
            raise RuntimeError("boom")

    svc = _make_service(layer_catalog, FailingStoreManager())
    svc._layers = {
        "LAYER_ALPHA": layer_catalog.LayerInfo(
            id="LAYER_ALPHA",
            canonical_name="Alpha",
            group_id=layer_catalog.GroupNames.ROOT,
            qgis_layer_id="qgis::alpha",
            feature_count=3,
            provider="memory"
        ),
        "LAYER_BETA": layer_catalog.LayerInfo(
            id="LAYER_BETA",
            canonical_name="Beta",
            group_id=layer_catalog.GroupNames.ROOT,
            qgis_layer_id="qgis::beta",
            feature_count=5,
            provider="ogr"
        )
    }
    snapshot = svc.get_catalog_snapshot()
    assert snapshot["layer_count"] == 2
    assert snapshot["total_features"] == 8
    assert any("Mission store lookup failed" in warning for warning in snapshot["warnings"])


def test_start_console_model_task_uses_task_manager(monkeypatch):
    layer_catalog = _install_catalog_module(monkeypatch)
    manager = MetadataStubLayerManager()
    svc = _make_service(layer_catalog, manager)
    stub_tm = StubTaskManager()
    svc._task_manager = stub_tm
    svc._owned_task_manager = False

    payloads = []

    task_id = svc.start_console_model_task(
        include_features=False,
        feature_limit=50,
        show_hidden=False,
        filter_favorites_only=True,
        on_complete=lambda payload: payloads.append(payload)
    )

    assert task_id == "catalog_fetch"
    assert stub_tm.started == ["catalog_fetch"]
    task, on_complete, _, _ = stub_tm._last_entry
    task.result = {"groups": []}
    on_complete(task)
    assert payloads == [{"groups": []}]


def test_cancel_task_delegates(monkeypatch):
    layer_catalog = _install_catalog_module(monkeypatch)
    manager = MetadataStubLayerManager()
    svc = _make_service(layer_catalog, manager)
    stub_tm = StubTaskManager()
    svc._task_manager = stub_tm
    svc.cancel_task("abc")
    assert stub_tm.cancelled == ["abc"]


def test_cleanup_cancels_owned_task_manager(monkeypatch):
    layer_catalog = _install_catalog_module(monkeypatch)
    manager = MetadataStubLayerManager()
    svc = _make_service(layer_catalog, manager)
    stub_tm = StubTaskManager()
    svc._task_manager = stub_tm
    svc._owned_task_manager = True
    svc._refresh_timer = None
    svc._signal_connections = []
    svc._pending_refresh_layers = set()
    svc._groups = {}
    svc._layers = {}
    svc.cleanup()
    assert stub_tm.cancel_all_called is True
    assert svc._task_manager is None
