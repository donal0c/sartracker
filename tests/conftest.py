# -*- coding: utf-8 -*-
"""
Test bootstrap to avoid importing full QGIS plugin while enabling package-relative imports.
"""
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Ensure repo root and vendored site-packages are importable
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
vendor_path = ROOT / "vendor" / "site-packages"
if vendor_path.exists() and str(vendor_path) not in sys.path:
    sys.path.insert(0, str(vendor_path))

# Stub lightweight sartracker package to satisfy relative imports without running QGIS entrypoint
if "sartracker" not in sys.modules:
    pkg = types.ModuleType("sartracker")
    pkg.__path__ = [str(ROOT)]
    sys.modules["sartracker"] = pkg

# ====================================================================
# QGIS Mock Setup - Global mocks for tests that don't need real QGIS
# ====================================================================

class MockQObject:
    """Mock QObject for testing."""
    def __init__(self, parent=None):
        self.parent = parent

class MockSignal:
    """Mock Qt signal."""
    def __init__(self):
        self._callbacks = []

    def connect(self, callback):
        self._callbacks.append(callback)

    def emit(self, *args, **kwargs):
        for callback in self._callbacks:
            callback(*args, **kwargs)

class MockQTimer:
    """Mock QTimer for testing."""
    def __init__(self, parent=None):
        self.parent = parent
        self._interval = 1000
        self._active = False
        self.timeout = MockSignal()  # Signal as an attribute, not a method

    def setInterval(self, ms):
        self._interval = ms

    def start(self):
        self._active = True

    def stop(self):
        self._active = False

    def isActive(self):
        return self._active

class MockQSettings:
    """Mock QSettings for testing."""
    def __init__(self):
        self._data = {}

    def value(self, key, default=None, type=None):
        val = self._data.get(key, default)
        if type == bool:
            return bool(val)
        return val

    def setValue(self, key, value):
        self._data[key] = value

    def remove(self, key):
        self._data.pop(key, None)

    def sync(self):
        pass

def mock_pyqtSignal(*args):
    """Mock pyqtSignal decorator."""
    return MockSignal()

# Only set up mocks if QGIS is not already available
# Check if we can actually import QGIS
_qgis_available = False
try:
    import qgis.core
    _qgis_available = True
except ImportError:
    pass

if not _qgis_available:
    from unittest.mock import MagicMock

    # Set up QGIS/Qt mocks
    qgis_mock = MagicMock()
    qgis_core_mock = MagicMock()
    qgis_pyqt_mock = MagicMock()
    qgis_pyqt_qtcore_mock = MagicMock()

    # Configure PyQt mocks with our custom classes
    qgis_pyqt_qtcore_mock.QObject = MockQObject
    qgis_pyqt_qtcore_mock.QTimer = MockQTimer
    qgis_pyqt_qtcore_mock.QSettings = MockQSettings
    qgis_pyqt_qtcore_mock.pyqtSignal = mock_pyqtSignal

    qgis_pyqt_mock.QtCore = qgis_pyqt_qtcore_mock
    qgis_mock.PyQt = qgis_pyqt_mock
    qgis_mock.core = qgis_core_mock

    sys.modules['qgis'] = qgis_mock
    sys.modules['qgis.core'] = qgis_core_mock
    sys.modules['qgis.PyQt'] = qgis_pyqt_mock
    sys.modules['qgis.PyQt.QtCore'] = qgis_pyqt_qtcore_mock
    sys.modules['qgis.PyQt.QtWidgets'] = MagicMock()
    sys.modules['qgis.PyQt.QtGui'] = MagicMock()

    # Mock additional modules that may cause import issues
    sys.modules['layers'] = MagicMock()
    sys.modules['utils.qt_compat'] = MagicMock()

    print("Warning: QGIS not available - using mocked QGIS classes for unit testing")
else:
    print("QGIS available - using real QGIS for integration testing")
