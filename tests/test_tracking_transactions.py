# -*- coding: utf-8 -*-
"""Tests targeting tracking manager transaction helpers."""

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
from sartracker.utils.exceptions import LayerTransactionError


def _build_manager():
    mgr = TrackingLayerManager.__new__(TrackingLayerManager)
    mgr.iface = types.SimpleNamespace(messageBar=lambda: None)
    mgr._layer_diag_enabled = False
    mgr.task_manager = None
    mgr._breadcrumb_task_id = None
    return mgr


class _FakeLayerBase:
    def __init__(self, commit_success=True):
        self._editable = False
        self._valid = True
        self._commit_success = commit_success
        self.rollback_calls = 0

    def isValid(self):
        return self._valid

    def isEditable(self):
        return self._editable

    def startEditing(self):
        self._editable = True
        return True

    def commitChanges(self):
        if not self._commit_success:
            return False
        self._editable = False
        return True

    def commitErrors(self):
        return ["commit failed"] if not self._commit_success else []

    def rollBack(self):
        self._editable = False
        self.rollback_calls += 1


class _FakeProvider:
    def __init__(self, layer, raise_error=False):
        self._layer = layer
        self.raise_error = raise_error
        self.truncate_calls = 0

    def truncate(self):
        self.truncate_calls += 1
        if self.raise_error:
            raise RuntimeError("truncate unsupported")
        self._layer._feature_ids = []


class _FakeFeatureLayer(_FakeLayerBase):
    def __init__(self, truncate_raises=False, delete_result=True):
        super().__init__()
        self._feature_ids = [1, 2, 3]
        self.delete_result = delete_result
        self.delete_calls = 0
        self.provider = _FakeProvider(self, raise_error=truncate_raises)

    def featureCount(self):
        return len(self._feature_ids)

    def dataProvider(self):
        return self.provider

    def deleteFeatures(self, ids):
        self.delete_calls += 1
        if not self.delete_result:
            return False
        remaining = [fid for fid in self._feature_ids if fid not in ids]
        self._feature_ids = remaining
        return True

    def allFeatureIds(self):
        return list(self._feature_ids)


def test_layer_transaction_rolls_back_on_commit_failure():
    mgr = _build_manager()
    layer = _FakeLayerBase(commit_success=False)

    with pytest.raises(LayerTransactionError):
        with mgr._layer_transaction(layer, "Test Layer", "unit op"):
            assert layer.isEditable()

    assert not layer.isEditable()
    assert layer.rollback_calls >= 1


def test_clear_layer_features_prefers_truncate():
    mgr = _build_manager()
    layer = _FakeFeatureLayer(truncate_raises=False)

    mgr._clear_layer_features(layer, "Layer X")

    assert layer.provider.truncate_calls == 1
    assert layer.delete_calls == 0
    assert layer.featureCount() == 0


def test_clear_layer_features_falls_back_to_delete():
    mgr = _build_manager()
    layer = _FakeFeatureLayer(truncate_raises=True)

    mgr._clear_layer_features(layer, "Layer Y")

    assert layer.provider.truncate_calls == 1
    assert layer.delete_calls == 1


def test_clear_layer_features_raises_when_delete_fails():
    mgr = _build_manager()
    layer = _FakeFeatureLayer(truncate_raises=True, delete_result=False)

    with pytest.raises(RuntimeError):
        mgr._clear_layer_features(layer, "Layer Z")
