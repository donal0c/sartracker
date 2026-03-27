# -*- coding: utf-8 -*-
"""Task lifecycle and TaskManager unit tests.

Tests marked with @requires_stubs need controlled signal behavior that
isn't possible with real QGIS signals. They run when QGIS is not loaded.
"""
import sys
import types
import pytest


pytestmark = pytest.mark.mock_qgis_only


def _has_real_qgis():
    """Check if real QGIS is loaded (pytest-qgis environment)."""
    try:
        from qgis.core import QgsTask
        return hasattr(QgsTask, 'taskCompleted')
    except Exception:
        return False


# Skip decorator for tests that need stub signal control
requires_stubs = pytest.mark.skipif(
    _has_real_qgis(),
    reason="Test requires stub signals - cannot emit real QGIS signals"
)



def _install_qgis_task_stubs(monkeypatch=None):
    """Install minimal qgis stubs for task-related imports.

    When real QGIS is available (pytest-qgis), we use real QGIS objects.
    Stubs are only installed when running without QGIS.
    """
    # Check if real QGIS is properly loaded (pytest-qgis environment)
    try:
        from qgis.core import QgsTask, QgsApplication
        # Real QGIS available - verify it's functional
        if hasattr(QgsTask, 'taskCompleted') and hasattr(QgsApplication, 'taskManager'):
            return  # Use real QGIS, no stubs needed
    except Exception:
        pass  # Real QGIS not available, install stubs

    # Only clear modules if we're installing stubs (no real QGIS)
    for mod_name in ['qgis', 'qgis.core', 'qgis.PyQt', 'qgis.PyQt.QtCore']:
        if mod_name in sys.modules:
            sys.modules.pop(mod_name, None)

    qgis_mod = types.ModuleType("qgis")
    pyqt_mod = types.ModuleType("qgis.PyQt")
    qtcore_mod = types.ModuleType("qgis.PyQt.QtCore")
    core_mod = types.ModuleType("qgis.core")

    class QObject:
        pass

    class QEventLoop:
        def processEvents(self):
            return None

    class QTimer:
        @staticmethod
        def singleShot(_ms, func):
            func()

    qtcore_mod.QObject = QObject
    qtcore_mod.QEventLoop = QEventLoop
    qtcore_mod.QTimer = QTimer

    class FakeSignal:
        def __init__(self):
            self._slots = []

        def connect(self, slot):
            self._slots.append(slot)

        def disconnect(self, slot):
            if slot not in self._slots:
                raise TypeError("slot not connected")
            self._slots.remove(slot)

        def emit(self, *args, **kwargs):
            for slot in list(self._slots):
                slot(*args, **kwargs)

    class QgsTask:
        CanCancel = 1

        def __init__(self, description="", flags=0):
            self._description = description
            self._flags = flags
            self._canceled = False
            self.taskCompleted = FakeSignal()
            self.taskTerminated = FakeSignal()

        def cancel(self):
            self._canceled = True

        def isCanceled(self):
            return self._canceled

        def setProgress(self, _progress):
            return None

        def run(self):
            """Default run implementation for subclasses."""
            return True

    class FakeTaskManager:
        def __init__(self):
            self.tasks = []

        def addTask(self, task):
            self.tasks.append(task)

        def countActiveTasks(self):
            return len(self.tasks)

    class QgsApplication:
        _task_manager = FakeTaskManager()

        @classmethod
        def taskManager(cls):
            return cls._task_manager

    core_mod.QgsTask = QgsTask
    core_mod.QgsApplication = QgsApplication

    qgis_mod.PyQt = pyqt_mod
    qgis_mod.core = core_mod
    pyqt_mod.QtCore = qtcore_mod

    if monkeypatch:
        monkeypatch.setitem(sys.modules, "qgis", qgis_mod)
        monkeypatch.setitem(sys.modules, "qgis.PyQt", pyqt_mod)
        monkeypatch.setitem(sys.modules, "qgis.PyQt.QtCore", qtcore_mod)
        monkeypatch.setitem(sys.modules, "qgis.core", core_mod)
    else:
        sys.modules["qgis"] = qgis_mod
        sys.modules["qgis.PyQt"] = pyqt_mod
        sys.modules["qgis.PyQt.QtCore"] = qtcore_mod
        sys.modules["qgis.core"] = core_mod


@requires_stubs
def test_task_manager_cancel_skips_callbacks(monkeypatch):
    """Test that cancelled tasks don't trigger completion callbacks.

    VALUE: CRITICAL - prevents crashes from accessing destroyed UI components
    when completion signals arrive after cancellation.
    """
    _install_qgis_task_stubs(monkeypatch)
    from qgis.core import QgsTask
    from sartracker.utils.task_manager import TaskManager

    manager = TaskManager()
    called = {"complete": 0}

    task = QgsTask("test")
    task_id = manager.start_task(
        task=task,
        on_complete=lambda _task: called.__setitem__("complete", called["complete"] + 1),
    )

    assert manager.cancel_task(task_id) is True

    # Simulate a queued completion signal after cancellation.
    task.taskCompleted.emit()

    assert called["complete"] == 0
    assert manager.get_active_count() == 0
    assert task_id not in manager.get_active_task_ids()
    assert not getattr(manager, "_cancelled_tasks")


@requires_stubs
def test_task_manager_cancel_all_forces_cleanup(monkeypatch):
    """Test that cancel_all() properly cleans up all tracked tasks.

    VALUE: CRITICAL - ensures clean plugin unload without dangling callbacks.
    """
    _install_qgis_task_stubs(monkeypatch)
    from qgis.core import QgsTask
    from sartracker.utils.task_manager import TaskManager

    manager = TaskManager()
    task = QgsTask("long")
    manager.start_task(task)

    manager.cancel_all(wait_timeout_ms=0)

    assert manager.get_active_count() == 0
    assert not getattr(manager, "_active_tasks")


@requires_stubs
def test_task_id_reuse_keeps_new_task(monkeypatch):
    """Test that reusing a task ID replaces the old task tracking.

    VALUE: HIGH - prevents stale callback issues when polling tasks restart.
    """
    _install_qgis_task_stubs(monkeypatch)
    from qgis.core import QgsTask
    from sartracker.utils.task_manager import TaskManager

    manager = TaskManager()
    task1 = QgsTask("old")
    task2 = QgsTask("new")
    seen = {"new": 0}

    manager.start_task(task1, task_id="shared")
    manager.start_task(task2, task_id="shared", on_complete=lambda _t: seen.__setitem__("new", 1))

    task1.taskCompleted.emit()

    assert manager.get_active_count() == 1
    assert manager._active_tasks.get("shared") is task2

    task2.taskCompleted.emit()

    assert seen["new"] == 1
    assert manager.get_active_count() == 0


@requires_stubs
def test_task_overlap_skips_old_callbacks(monkeypatch):
    """Test that overlapping tasks with same ID ignore old task callbacks.

    VALUE: HIGH - ensures only the current task's callbacks fire, preventing
    race conditions with stale data.
    """
    _install_qgis_task_stubs(monkeypatch)
    from qgis.core import QgsTask
    from sartracker.utils.task_manager import TaskManager

    manager = TaskManager()
    seen = {"old": 0, "new": 0}

    task1 = QgsTask("old")
    task2 = QgsTask("new")

    manager.start_task(
        task1,
        task_id="refresh",
        on_complete=lambda _t: seen.__setitem__("old", seen["old"] + 1)
    )
    manager.start_task(
        task2,
        task_id="refresh",
        on_complete=lambda _t: seen.__setitem__("new", seen["new"] + 1)
    )

    task1.taskCompleted.emit()
    task2.taskCompleted.emit()

    assert seen["old"] == 0
    assert seen["new"] == 1


def test_require_components_skips_deleted(monkeypatch):
    from sartracker.utils import task_guards

    class Holder:
        pass

    holder = Holder()
    holder.panel = object()
    holder.controller = object()
    called = {"count": 0}

    @task_guards.require_components("panel", "controller")
    def _run(self):
        called["count"] += 1

    monkeypatch.setattr(task_guards, "_is_qobject_alive", lambda obj: obj is not holder.panel)

    _run(holder)

    assert called["count"] == 0


def test_guard_ui_update_skips_deleted_iface(monkeypatch):
    from sartracker.utils import task_guards

    class Holder:
        pass

    holder = Holder()
    holder.iface = object()
    holder.panel = object()
    called = {"count": 0}

    @task_guards.guard_ui_update(panel_attr="panel")
    def _run(self):
        called["count"] += 1

    monkeypatch.setattr(task_guards, "_is_qobject_alive", lambda obj: obj is not holder.iface)

    _run(holder)

    assert called["count"] == 0


def test_is_qobject_alive_handles_non_qt(monkeypatch):
    from sartracker.utils import task_guards

    qgis_mod = types.ModuleType("qgis")
    pyqt_mod = types.ModuleType("qgis.PyQt")
    sip_mod = types.ModuleType("qgis.PyQt.sip")

    def isdeleted(_obj):
        raise TypeError("not a sip wrapper")

    sip_mod.isdeleted = isdeleted

    monkeypatch.setitem(sys.modules, "qgis", qgis_mod)
    monkeypatch.setitem(sys.modules, "qgis.PyQt", pyqt_mod)
    monkeypatch.setitem(sys.modules, "qgis.PyQt.sip", sip_mod)

    assert task_guards._is_qobject_alive(object()) is True


def test_connection_test_task_respects_cancel(monkeypatch):
    _install_qgis_task_stubs(monkeypatch)

    # Force reload to pick up our stubs instead of conftest mocks
    import importlib
    modules_to_reload = [
        'sartracker.utils.task_manager',
        'sartracker.providers.tasks'
    ]
    for mod_name in modules_to_reload:
        if mod_name in sys.modules:
            importlib.reload(sys.modules[mod_name])

    from sartracker.providers.tasks import ConnectionTestTask

    class FakeSession:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    class Provider:
        def __init__(self):
            self.session = None
            self.task = None

        def _create_session(self):
            self.session = FakeSession()
            return self.session

        def test_connection(self, session=None):
            if self.task:
                self.task.cancel()
            return True

    provider = Provider()
    task = ConnectionTestTask(provider)
    provider.task = task

    ok = task.run()

    assert ok is False
    assert task.success is False
    assert task.error_message == "Task cancelled"
    assert provider.session.closed is True
