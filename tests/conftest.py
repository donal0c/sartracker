# -*- coding: utf-8 -*-
"""
Test bootstrap to avoid importing full QGIS plugin while enabling package-relative imports.

This module sets up the test environment for SAR Tracker plugin testing.

Test modes:
1. Unit tests (QGIS not available): Uses mock QGIS classes
2. Integration tests (QGIS available): Uses real QGIS via pytest-qgis

To run integration tests with pytest-qgis:
    - Ensure QGIS is installed
    - Install pytest-qgis: pip install pytest-qgis
    - Run with QGIS Python or with --system-site-packages venv

To skip integration tests:
    pytest -m 'not qgis_required'
"""
import os
import sys
import types
from pathlib import Path

import pytest

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

class MockQgsTask:
    """Mock QgsTask for unit tests that instantiate provider tasks."""
    CanCancel = 0

    def __init__(self, description="", flags=None):
        self._description = description
        self._flags = flags
        self._progress = 0.0
        self._canceled = False

    def isCanceled(self):
        return self._canceled

    def setProgress(self, value):
        try:
            self._progress = float(value)
        except Exception:
            self._progress = 0.0

class MockQSettings:
    """Mock QSettings for testing."""
    _data = {}

    def __init__(self):
        pass

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
# Check if we can actually import QGIS (allow force-mock override)
_qgis_available = False
_force_mock_qgis = os.environ.get("SARTRACKER_FORCE_MOCK_QGIS") == "1"
if not _force_mock_qgis:
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
    qgis_core_mock.QgsTask = MockQgsTask

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

# ====================================================================
# QApplication Handling
# ====================================================================
# NOTE: We do NOT create QApplication at conftest import time.
# pytest-qgis handles QApplication creation via its qgis_app fixture.
#
# On macOS with Rosetta 2, creating QApplication in conftest causes
# SIGSEGV crashes during Python shutdown (Py_FinalizeEx).
#
# Tests that need Qt widgets should:
# 1. Use the qgis_app fixture (provided by pytest-qgis)
# 2. Be skipped on macOS if they cause crashes (see test_devices_window.py)
#
# See SAR-efn7 and SAR-1t49 for crash investigation details.
# ====================================================================


# ====================================================================
# pytest-qgis Integration
# ====================================================================

# Check if pytest-qgis is available
_pytest_qgis_available = False
try:
    import pytest_qgis
    _pytest_qgis_available = True
except ImportError:
    pass


def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers", "qgis_required: mark test as requiring real QGIS environment"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow-running"
    )
    config.addinivalue_line(
        "markers", "integration: mark test as integration test"
    )


def pytest_collection_modifyitems(config, items):
    """Auto-skip qgis_required tests when QGIS is not available."""
    if _qgis_available:
        # QGIS is available, don't skip anything
        return

    skip_qgis = pytest.mark.skip(reason="QGIS not available - install QGIS and pytest-qgis for integration tests")
    for item in items:
        if "qgis_required" in item.keywords:
            item.add_marker(skip_qgis)


# ====================================================================
# Common Test Fixtures
# ====================================================================

if not _qgis_available:
    @pytest.fixture(autouse=True)
    def _reset_mock_qsettings():
        """Clear mock QSettings between tests to avoid cross-test leakage."""
        MockQSettings._data.clear()
        yield

# Note: When pytest-qgis is available, it provides the qgis_app fixture.
# We only define our own when pytest-qgis is NOT available.
if not _pytest_qgis_available:
    @pytest.fixture(scope="session")
    def qgis_app():
        """
        Provide a QApplication instance for the test session (fallback).

        This fixture is only used when pytest-qgis is not available.
        When pytest-qgis IS available, its qgis_app fixture takes precedence.

        Returns a mock for non-QGIS test environments.
        """
        from unittest.mock import MagicMock
        return MagicMock()


@pytest.fixture
def temp_gpkg(tmp_path):
    """Create a temporary GeoPackage file path."""
    return tmp_path / "test.gpkg"


@pytest.fixture
def mock_iface():
    """Return a minimal mock iface for unit tests."""
    from unittest.mock import MagicMock

    iface = MagicMock()
    iface.messageBar.return_value = MagicMock()
    iface.mainWindow.return_value = None
    return iface


@pytest.fixture
def sample_coordinates():
    """Return sample valid coordinates for testing."""
    return {
        "wgs84": {"lat": 52.1409, "lon": -9.6938},  # Kerry, Ireland
        "itm": {"easting": 451234.5, "northing": 598765.4},
        "invalid_lat": {"lat": 91.0, "lon": -9.6938},
        "invalid_lon": {"lat": 52.1409, "lon": 181.0},
    }


# ====================================================================
# pytest-qgis Fixture Wrappers (when available)
# ====================================================================

if _pytest_qgis_available and _qgis_available:
    # Re-export pytest-qgis fixtures for convenience
    # These will be available when running with real QGIS

    @pytest.fixture
    def sar_qgis_project(qgis_new_project):
        """
        Provide a clean QGIS project for SAR testing.

        Uses pytest-qgis qgis_new_project to ensure clean state.
        """
        return qgis_new_project

    @pytest.fixture
    def sar_iface(qgis_iface):
        """
        Provide a QGIS iface for SAR testing.

        Uses pytest-qgis qgis_iface which provides a stubbed QgisInterface.
        """
        return qgis_iface
