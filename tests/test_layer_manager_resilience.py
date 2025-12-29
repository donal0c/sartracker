# -*- coding: utf-8 -*-
"""
Focused tests for layers.manager resilience behavior using lightweight QGIS stubs.
"""

import importlib.util
import sys
import types
from pathlib import Path

import pytest


def _install_qgis_stubs():
    """Install minimal qgis stubs if QGIS is not available."""
    if importlib.util.find_spec("qgis") is not None:
        return

    qgis_mod = types.ModuleType("qgis")
    pyqt_mod = types.ModuleType("qgis.PyQt")
    qtcore_mod = types.ModuleType("qgis.PyQt.QtCore")
    qtgui_mod = types.ModuleType("qgis.PyQt.QtGui")
    qtwidgets_mod = types.ModuleType("qgis.PyQt.QtWidgets")
    core_mod = types.ModuleType("qgis.core")

    class DummySignal:
        def __init__(self):
            self._slots = []

        def connect(self, fn):
            self._slots.append(fn)

        def disconnect(self, fn):
            if fn in self._slots:
                self._slots.remove(fn)

        def emit(self, *args, **kwargs):
            for fn in list(self._slots):
                try:
                    fn(*args, **kwargs)
                except Exception:
                    pass

    def pyqtSignal(*_args, **_kwargs):
        return DummySignal()

    class QObject:
        def __init__(self, *args, **kwargs):
            super().__init__()

    class QEvent:
        Close = 19

        def __init__(self, event_type=None):
            self._type = event_type

        def type(self):
            return self._type

    class QCoreApplication:
        _inst = None

        def __init__(self):
            self.aboutToQuit = DummySignal()

        @classmethod
        def instance(cls):
            if cls._inst is None:
                cls._inst = cls()
            return cls._inst

    class QVariant:
        String = "String"
        Int = "Int"
        Double = "Double"
        DateTime = "DateTime"
        Bool = "Bool"

    qtcore_mod.QVariant = QVariant
    qtcore_mod.QObject = QObject
    qtcore_mod.pyqtSignal = pyqtSignal
    qtcore_mod.QEvent = QEvent
    qtcore_mod.QCoreApplication = QCoreApplication

    class QTimer(QObject):
        def __init__(self, *_args, **_kwargs):
            super().__init__()
            self._active = False
            self.timeout = pyqtSignal()

        def setSingleShot(self, _flag):
            return None

        def start(self, _interval):
            self._active = True

        def stop(self):
            self._active = False

        def isActive(self):
            return self._active

        def deleteLater(self):
            self._active = False

    qtcore_mod.QTimer = QTimer

    class QSettings:
        def __init__(self, *_args, **_kwargs):
            self._store = {}

        def value(self, key, default=None):
            return self._store.get(key, default)

        def setValue(self, key, value):
            self._store[key] = value

        def remove(self, key):
            self._store.pop(key, None)

    qtcore_mod.QSettings = QSettings

    class QColor:
        def __init__(self, *_args, **_kwargs):
            pass

    class QFont:
        Bold = 75

        def __init__(self, *_args, **_kwargs):
            self._size = kwargs.get("pointSize", 10)

        def setPointSize(self, size):
            self._size = size

    qtgui_mod.QColor = QColor
    qtgui_mod.QFont = QFont

    class QDialog:
        def __init__(self, *_args, **_kwargs):
            pass

    qtwidgets_mod.QDialog = QDialog

    class QgsProject:
        _instance = None

        def __init__(self):
            self._custom_vars = {}
            self.layersWillBeRemoved = DummySignal()
            self.cleared = DummySignal()

        @classmethod
        def instance(cls):
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

        def customVariables(self):
            return dict(self._custom_vars)

        def setCustomVariables(self, variables):
            self._custom_vars = dict(variables or {})

        def setCustomVariable(self, key, value):
            self._custom_vars[key] = value

        def layerTreeRoot(self):
            return None

        def mapLayers(self):
            return {}

        def mapLayersByName(self, _name):
            return []

        def readEntry(self, *_args):
            return ("", False)

        def writeEntry(self, *_args):
            return None

        def removeEntry(self, *_args):
            return None

        def write(self):
            return None

        def transformContext(self):
            return None

    class QgsVectorLayer:
        def __init__(self, *_args, **_kwargs):
            self._props = {}
            self._read_only = False

        def setReadOnly(self, flag):
            self._read_only = flag

        def providerType(self):
            return "memory"

        def setCustomProperty(self, key, value):
            self._props[key] = value

        def customProperty(self, key):
            return self._props.get(key)

        def isValid(self):
            return True

    class QgsField:
        pass

    class QgsLayerTreeGroup:
        pass

    class QgsLayerTreeLayer:
        pass

    class QgsLayerTreeNode:
        def __init__(self):
            self._visible = True

        def isVisible(self):
            return self._visible

        def setItemVisibilityChecked(self, flag):
            self._visible = bool(flag)

    class QgsPointXY:
        def __init__(self, x=0, y=0):
            self.x = x
            self.y = y

    class QgsRendererCategory:
        def __init__(self, value, symbol, label):
            self.value = value
            self.symbol = symbol
            self.label = label

    class QgsCategorizedSymbolRenderer:
        def __init__(self, field, categories=None):
            self.field = field
            self.categories = categories or []

    class QgsFeatureRequest:
        def __init__(self):
            self._limit = None

        def setLimit(self, limit):
            self._limit = limit

    class QgsVectorLayerSimpleLabeling:
        def __init__(self, *_args, **_kwargs):
            self.settings = _args[0] if _args else None

    class QgsSimpleMarkerSymbolLayer:
        def __init__(self, *_args, **_kwargs):
            self._props = {}

        def setColor(self, *_args, **_kwargs):
            return None

        def setSize(self, *_args, **_kwargs):
            return None

    class QgsPalLayerSettings:
        def __init__(self):
            self.enabled = False

    class QgsTextFormat:
        def __init__(self):
            self.buffer = QgsTextBufferSettings()

    class QgsTextBufferSettings:
        def __init__(self):
            self.enabled = False

        def setEnabled(self, enabled):
            self.enabled = enabled

    class QgsFeature:
        def __init__(self, fid=0):
            self._id = fid
            self._attributes = {}
            self._geometry = None

        def id(self):
            return self._id

        def setAttributes(self, attrs):
            self._attributes = attrs

        def attributes(self):
            return self._attributes

        def attribute(self, key):
            return self._attributes.get(key)

        def setGeometry(self, geom):
            self._geometry = geom

        def geometry(self):
            return self._geometry

    class QgsGeometry:
        def __init__(self, wkt=""):
            self._wkt = wkt

        @classmethod
        def fromPointXY(cls, point):
            return cls(f"POINT({point.x} {point.y})")

        @classmethod
        def fromWkt(cls, wkt):
            return cls(wkt)

        def asWkt(self):
            return self._wkt

        def isNull(self):
            return not bool(self._wkt)

    class QgsCoordinateReferenceSystem:
        def __init__(self, *_args, **_kwargs):
            self._valid = True

        def isValid(self):
            return self._valid

    class QgsCoordinateTransformContext:
        pass

    class QgsDistanceArea:
        def measureLine(self, *_args, **_kwargs):
            return 0.0

    class _GeomTypes:
        Point = 1
        LineString = 2
        Polygon = 3

    class QgsMarkerSymbol:
        pass

    class QgsLineSymbol:
        pass

    class QgsFillSymbol:
        pass

    class QgsMapLayerStyle:
        def readFromLayer(self, *_args, **_kwargs):
            return False

        def writeToLayer(self, *_args, **_kwargs):
            return None

    class QgsTask:
        CanCancel = 1

        def __init__(self, *_args, **_kwargs):
            self.taskCompleted = DummySignal()
            self.taskTerminated = DummySignal()
            self._props = {}

        @classmethod
        def fromFunction(cls, _desc, function, on_finished=None):
            task = cls()
            task._function = function
            task._on_finished = on_finished
            return task

        def setProperty(self, key, value):
            self._props[key] = value

        def property(self, key):
            return self._props.get(key)

        # Helpers for tests to simulate run
        def _run(self):
            result = self._function(self)
            if self._on_finished:
                self._on_finished(self, result)

    class DummyTaskManager:
        def __init__(self):
            self.tasks = []

        def addTask(self, task):
            self.tasks.append(task)
            if hasattr(task, "_run"):
                task._run()

    def _project_instance():
        if not hasattr(_project_instance, "_inst"):
            _project_instance._inst = core_mod.QgsProject()
        return _project_instance._inst

    class QgsVectorLayerExporter:
        class SaveVectorOptions:
            def __init__(self):
                self.driverName = ""
                self.layerName = ""
                self.fileEncoding = ""
                self.onlySelectedFeatures = False

        CreateOrOverwriteLayer = 1
        NoError = 0

        @staticmethod
        def exportLayer(*_args, **_kwargs):
            return QgsVectorLayerExporter.NoError, "", None

    class QgsVectorFileWriter:
        class SaveVectorOptions:
            def __init__(self):
                self.driverName = ""
                self.layerName = ""
                self.fileEncoding = ""
                self.onlySelectedFeatures = False

        CreateOrOverwriteLayer = 1
        NoError = 0

        @staticmethod
        def writeAsVectorFormatV3(*_args, **_kwargs):
            return QgsVectorFileWriter.NoError, ""

    class QgsDataSourceUri:
        def setDatabase(self, _db):
            return None

        def setDataSource(self, *_args, **_kwargs):
            return None

        def uri(self):
            return ""

    NULL = object()

    core_mod.QgsProject = QgsProject
    core_mod.QgsVectorLayer = QgsVectorLayer
    core_mod.QgsField = QgsField
    core_mod.QgsLayerTreeGroup = QgsLayerTreeGroup
    core_mod.QgsLayerTreeLayer = QgsLayerTreeLayer
    core_mod.QgsLayerTreeNode = QgsLayerTreeNode
    core_mod.QgsPointXY = QgsPointXY
    core_mod.QgsRendererCategory = QgsRendererCategory
    core_mod.QgsCategorizedSymbolRenderer = QgsCategorizedSymbolRenderer
    core_mod.QgsFeatureRequest = QgsFeatureRequest
    core_mod.QgsVectorLayerSimpleLabeling = QgsVectorLayerSimpleLabeling
    core_mod.QgsSimpleMarkerSymbolLayer = QgsSimpleMarkerSymbolLayer
    core_mod.QgsPalLayerSettings = QgsPalLayerSettings
    core_mod.QgsTextFormat = QgsTextFormat
    core_mod.QgsTextBufferSettings = QgsTextBufferSettings
    core_mod.QgsFeature = QgsFeature
    core_mod.QgsGeometry = QgsGeometry
    core_mod.QgsCoordinateReferenceSystem = QgsCoordinateReferenceSystem
    core_mod.QgsCoordinateTransformContext = QgsCoordinateTransformContext
    core_mod.QgsDistanceArea = QgsDistanceArea
    core_mod.QgsMarkerSymbol = QgsMarkerSymbol
    core_mod.QgsLineSymbol = QgsLineSymbol
    core_mod.QgsFillSymbol = QgsFillSymbol
    core_mod.QgsWkbTypes = _GeomTypes
    core_mod.QgsMapLayerStyle = QgsMapLayerStyle
    core_mod.QgsTask = QgsTask
    core_mod.QgsVectorLayerExporter = QgsVectorLayerExporter
    core_mod.QgsVectorFileWriter = QgsVectorFileWriter
    core_mod.QgsDataSourceUri = QgsDataSourceUri
    core_mod.NULL = NULL
    core_mod.QgsApplication = types.SimpleNamespace(taskManager=lambda: DummyTaskManager())
    core_mod.QgsProject.instance = classmethod(lambda cls: _project_instance())

    sys.modules["qgis"] = qgis_mod
    sys.modules["qgis.PyQt"] = pyqt_mod
    sys.modules["qgis.PyQt.QtCore"] = qtcore_mod
    sys.modules["qgis.PyQt.QtGui"] = qtgui_mod
    sys.modules["qgis.PyQt.QtWidgets"] = qtwidgets_mod
    sys.modules["qgis.core"] = core_mod
    qgis_mod.PyQt = pyqt_mod
    qgis_mod.core = core_mod
    pyqt_mod.QtCore = qtcore_mod
    pyqt_mod.QtGui = qtgui_mod
    pyqt_mod.QtWidgets = qtwidgets_mod


def _install_notify_stub():
    """Install a minimal utils.qt_compat stub to avoid Qt dependencies."""
    mod = types.ModuleType("sartracker.utils.qt_compat")

    def push_message(_bar, _title, _msg, _level=0, _duration=5):
        return None

    mod.push_message = push_message
    sys.modules["sartracker.utils.qt_compat"] = mod
    # Provide top-level alias as well for direct utils imports
    sys.modules.setdefault("utils.qt_compat", mod)


def _ensure_qgis(monkeypatch):
    """Ensure qgis imports succeed by installing stubs when needed."""
    try:
        import qgis  # noqa: F401
        return
    except ImportError:
        _install_qgis_stubs()
    _install_notify_stub()


def _load_manager_module():
    layers_pkg = types.ModuleType("sartracker.layers")
    layers_pkg.__path__ = [str(Path(__file__).resolve().parent.parent / "layers")]
    sys.modules["sartracker.layers"] = layers_pkg
    from sartracker.layers import manager, schema

    # Ensure schema is also registered for monkeypatching
    sys.modules["sartracker.layers.schema"] = schema
    return manager


def test_set_mission_store_directory_failure(monkeypatch, tmp_path):
    _ensure_qgis(monkeypatch)

    manager = _load_manager_module()

    messages = []

    def fake_error(_bar, title, message, duration=5):
        messages.append((title, message, duration))

    monkeypatch.setattr(manager, "error", fake_error)

    class FakeIface:
        def messageBar(self):
            return "bar"

    mgr = manager.LayerManager(FakeIface())
    bad_path = tmp_path / "nested" / "store" / "mission.gpkg"

    def failing_mkdir(_path_obj, parents=False, exist_ok=False):
        raise PermissionError("no write")

    monkeypatch.setattr(manager.Path, "mkdir", failing_mkdir)

    mgr.set_mission_store(str(bad_path))

    assert mgr.get_mission_store() is None
    assert messages, "mission store failures should surface an error message"
    assert "Failed to prepare mission store directory" in messages[0][1]


def test_get_mission_store_refreshes_from_project(monkeypatch, tmp_path):
    _ensure_qgis(monkeypatch)
    manager = _load_manager_module()

    class FakeIface:
        def messageBar(self):
            return "bar"

        def mainWindow(self):
            return None

    mgr = manager.LayerManager(FakeIface())
    project = manager.QgsProject.instance()
    store_path = tmp_path / "mission.gpkg"
    project.setCustomVariables({manager.LayerManager.MISSION_STORE_VAR: str(store_path)})

    assert mgr.get_mission_store() == str(store_path)


def test_project_cleared_does_not_rebuild_structure(monkeypatch):
    _ensure_qgis(monkeypatch)
    manager = _load_manager_module()

    class FakeIface:
        def messageBar(self):
            return "bar"

        def mainWindow(self):
            return None

    mgr = manager.LayerManager(FakeIface())

    calls = {"ensure_structure": 0}

    def fake_ensure_structure(*_args, **_kwargs):
        calls["ensure_structure"] += 1
        return True

    monkeypatch.setattr(mgr, "ensure_structure", fake_ensure_structure)

    project = manager.QgsProject.instance()
    project.cleared.emit()

    assert calls["ensure_structure"] == 0


def test_metadata_migration_sets_guard_and_resets(monkeypatch):
    _ensure_qgis(monkeypatch)
    manager = _load_manager_module()

    mgr = manager.LayerManager.__new__(manager.LayerManager)
    mgr._metadata_migration_in_progress = False
    mgr.iface = types.SimpleNamespace(messageBar=lambda: "bar")
    mgr._log = lambda *_args, **_kwargs: None

    calls = []

    def fake_set_layer_metadata(layer_id, metadata):
        calls.append((layer_id, metadata.get("updated_at")))

    mgr.set_layer_metadata = fake_set_layer_metadata

    metadata = {"updated_at": "2024-01-01T10:00:00"}
    updated = manager.LayerManager._migrate_datetime_timezone(mgr, metadata, "LAYER_X")

    assert calls == [("LAYER_X", "2024-01-01T10:00:00+00:00")]
    assert updated["updated_at"].endswith("+00:00")
    assert mgr._metadata_migration_in_progress is False


def test_metadata_migration_guard_prevents_reentry(monkeypatch):
    _ensure_qgis(monkeypatch)
    manager = _load_manager_module()

    mgr = manager.LayerManager.__new__(manager.LayerManager)
    mgr._metadata_migration_in_progress = True
    mgr.iface = types.SimpleNamespace(messageBar=lambda: "bar")
    mgr.set_layer_metadata = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("should not run"))
    mgr._log = lambda *_args, **_kwargs: None

    metadata = {"updated_at": "2024-01-01T10:00:00"}
    result = manager.LayerManager._migrate_datetime_timezone(mgr, metadata, "LAYER_Y")

    assert result["updated_at"] == "2024-01-01T10:00:00"


def test_validate_persistence_reports_layer_ids(monkeypatch):
    _ensure_qgis(monkeypatch)
    manager = _load_manager_module()

    mgr = manager.LayerManager.__new__(manager.LayerManager)
    mgr._mission_store_path = "/tmp/mission.gpkg"
    mgr.iface = types.SimpleNamespace(messageBar=lambda: "bar")
    mgr._log = lambda *_args, **_kwargs: None

    defs = [
        manager.LayerDefinition(layer_id="layer_missing", name="Missing", geometry_type="Point"),
        manager.LayerDefinition(layer_id="layer_memory", name="Memory", geometry_type="Point"),
    ]
    mgr._collect_layer_definitions = lambda: defs

    class FakeLayer:
        def __init__(self, provider):
            self._provider = provider

        def providerType(self):
            return self._provider

    def fake_get_layer(layer_id):
        if layer_id == "layer_missing":
            return None
        return FakeLayer("memory")

    mgr.get_layer = fake_get_layer

    messages = []
    monkeypatch.setattr(
        manager,
        "warning",
        lambda _bar, title, message, duration=5: messages.append((title, message, duration)),
    )

    issues = manager.LayerManager.validate_persistence(mgr, quiet=False)

    assert issues == {
        "layer_missing": "missing",
        "layer_memory": "memory",
    }
    assert messages, "warning should surface missing/memory layers"
    assert "layer_missing" in messages[0][1]
    assert "layer_memory" in messages[0][1]


def test_create_vector_layer_falls_back_to_memory(monkeypatch):
    _ensure_qgis(monkeypatch)
    manager = _load_manager_module()

    mgr = manager.LayerManager.__new__(manager.LayerManager)
    mgr._mission_store_path = "/tmp/mission.gpkg"
    mgr.iface = types.SimpleNamespace(messageBar=lambda: "bar")
    mgr._log = lambda *_args, **_kwargs: None

    layer_def = manager.LayerDefinition(layer_id="layer_x", name="Layer X", geometry_type="Point")

    sentinel = object()
    monkeypatch.setattr(mgr, "_ensure_persistent_layer", lambda _ld: (_ for _ in ()).throw(RuntimeError("fail persist")))
    monkeypatch.setattr(mgr, "_create_memory_layer", lambda _ld: sentinel)

    warnings = []
    monkeypatch.setattr(
        manager,
        "warning",
        lambda _bar, title, message, duration=5: warnings.append((title, message)),
    )

    result = manager.LayerManager._create_vector_layer(mgr, layer_def)

    assert result is sentinel
    assert warnings, "should warn when falling back to memory"
    assert "using memory" in warnings[0][1]


def test_route_feature_surfaces_error(monkeypatch):
    _ensure_qgis(monkeypatch)
    manager = _load_manager_module()

    mgr = manager.LayerManager.__new__(manager.LayerManager)
    mgr.iface = types.SimpleNamespace(messageBar=lambda: "bar")
    mgr._log = lambda *_args, **_kwargs: None

    errors = []
    monkeypatch.setattr(
        manager,
        "error",
        lambda _bar, title, message, duration=5: errors.append((title, message)),
    )

    class FakeLayer:
        def __init__(self):
            self._editable = False

        def startEditing(self):
            self._editable = True

        def addFeature(self, _feature):
            return False

        def commitChanges(self):
            return False

        def commitErrors(self):
            return ["bad"]

        def rollBack(self):
            self._editable = False

        def isEditable(self):
            return self._editable

        def name(self):
            return "Fake Layer"

    mgr.get_layer = lambda _id: FakeLayer()
    # Patch schema map used inside route_feature
    monkeypatch.setattr(sys.modules["sartracker.layers.schema"], "ARTIFACT_LAYER_MAP", {"clue": "layer_x"})

    with pytest.raises(RuntimeError):
        manager.LayerManager.route_feature(mgr, "clue", feature=object())

    assert errors, "error notification should be emitted on failure"
    assert "Add Feature Failed" in errors[0][0]


def test_connect_signals_warns_on_failure(monkeypatch):
    _ensure_qgis(monkeypatch)
    manager = _load_manager_module()

    warnings = []
    monkeypatch.setattr(
        manager,
        "warning",
        lambda _bar, title, message, duration=5: warnings.append((title, message)),
    )

    class FakeSignal:
        def connect(self, _fn):
            raise RuntimeError("boom")

    class FakeProject:
        def __init__(self):
            self.layersWillBeRemoved = FakeSignal()

        def customVariables(self):
            return {}

    fake_project = FakeProject()
    monkeypatch.setattr(manager.QgsProject, "_instance", fake_project)
    monkeypatch.setattr(manager.QgsProject, "instance", classmethod(lambda cls: fake_project))

    mgr = manager.LayerManager(types.SimpleNamespace(messageBar=lambda: "bar"))

    assert not mgr._signals_connected
    assert warnings, "warning should be emitted on signal hookup failure"
    assert "Could not connect project signals" in warnings[0][1]


def test_ensure_structure_async_falls_back_without_task(monkeypatch):
    _ensure_qgis(monkeypatch)
    manager = _load_manager_module()

    mgr = manager.LayerManager.__new__(manager.LayerManager)
    mgr.iface = types.SimpleNamespace(messageBar=lambda: "bar")
    mgr._log = lambda *_args, **_kwargs: None

    called = {"ensure": 0}

    def ensure_structure(auto_migrate=True):
        called["ensure"] += 1
        return True

    mgr.ensure_structure = ensure_structure

    result = manager.LayerManager.ensure_structure_async(
        mgr,
        task_manager=None,
        auto_migrate=True,
        on_complete=lambda ok: called.setdefault("complete", ok),
    )

    assert result is True
    assert called["ensure"] == 1
    assert called.get("complete") is True


def test_repair_structure_async_runs_on_ui_thread(monkeypatch):
    _ensure_qgis(monkeypatch)
    manager = _load_manager_module()

    class FakeTaskManager:
        def __init__(self):
            self.tasks = []

        def start_task(self, task, on_complete=None, on_error=None, task_id=None):
            self.tasks.append(task)
            # Simulate task running immediately via stub _run (installed in stubs)
            if hasattr(task, "_run"):
                task._run()

    mgr = manager.LayerManager.__new__(manager.LayerManager)
    mgr.iface = types.SimpleNamespace(messageBar=lambda: "bar")
    mgr._log = lambda *_args, **_kwargs: None

    called = {"repair": 0}

    def repair_structure():
        called["repair"] += 1
        return True

    mgr.repair_structure = repair_structure

    task_manager = FakeTaskManager()
    result = manager.LayerManager.repair_structure_async(
        mgr,
        task_manager=task_manager,
        on_complete=lambda ok: called.setdefault("complete", ok),
    )

    assert result is True
    assert called["repair"] == 1
    assert called.get("complete") is True
    assert not task_manager.tasks, "no background task should be submitted"


def test_set_mission_finalized_uses_helper(monkeypatch):
    _ensure_qgis(monkeypatch)
    manager = _load_manager_module()

    mgr = manager.LayerManager.__new__(manager.LayerManager)
    mgr.iface = types.SimpleNamespace(messageBar=lambda: "bar")
    mgr._log = lambda *_args, **_kwargs: None

    project = manager.QgsProject.instance()
    wrote = {"called": 0}
    project.write = lambda: wrote.__setitem__("called", wrote["called"] + 1)

    set_vars = {}
    monkeypatch.setattr(
        manager.LayerManager,
        "_set_project_variable",
        lambda self, key, value: set_vars.__setitem__(key, value),
    )

    locks = []
    monkeypatch.setattr(
        manager.LayerManager,
        "_set_layers_read_only",
        lambda self, ro: locks.append(ro),
    )

    mgr.set_mission_finalized(True, finalized_by="Alice", finalized_at="2024-01-01T00:00:00Z")

    assert set_vars[manager.LayerManager.MISSION_FINALIZED_VAR] == "true"
    assert set_vars[manager.LayerManager.MISSION_FINALIZED_BY_VAR] == "Alice"
    assert set_vars[manager.LayerManager.MISSION_FINALIZED_AT_VAR] == "2024-01-01T00:00:00Z"
    assert locks[-1] is True
    assert wrote["called"] == 1

    mgr.set_mission_finalized(False)
    assert set_vars[manager.LayerManager.MISSION_FINALIZED_VAR] == ""
    assert locks[-1] is False
    class QgsRendererCategory:
        def __init__(self, value, symbol, label):
            self.value = value
            self.symbol = symbol
            self.label = label

    class QgsCategorizedSymbolRenderer:
        def __init__(self, field, categories=None):
            self.field = field
            self.categories = categories or []

    class QgsFeatureRequest:
        def __init__(self):
            self._limit = None

        def setLimit(self, limit):
            self._limit = limit
