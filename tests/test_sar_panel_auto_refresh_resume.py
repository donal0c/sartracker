# -*- coding: utf-8 -*-
"""
Auto-refresh lifecycle tests for SARPanel.

TDD: Failing test added before fix.
"""
import importlib
import sys
import types
from unittest.mock import MagicMock, patch

from sartracker.controllers.mission_controller import MissionState


class FakeTimer:
    """Simple QTimer stub with interval tracking."""
    def __init__(self, parent=None):
        self.parent = parent
        self._interval = None
        self._active = False
        self.timeout = MagicMock()

    def setInterval(self, ms):
        self._interval = ms

    def start(self, *args):
        if args:
            self._interval = args[0]
        self._active = True

    def stop(self):
        self._active = False

    def isActive(self):
        return self._active


def test_auto_refresh_resumes_after_close_and_show():
    """
    Auto-refresh should resume when SAR panel is dismissed and then shown again.
    """
    class StubDockWidget:
        def __init__(self, *args, **kwargs):
            pass

        def setAllowedAreas(self, *args, **kwargs):
            pass

        def closeEvent(self, event):
            pass

        def showEvent(self, event):
            pass

    def stub_class(name):
        return type(name, (), {})

    qtwidgets_module = types.ModuleType("qgis.PyQt.QtWidgets")
    qtwidgets_module.QDockWidget = StubDockWidget
    qtwidgets_module.QWidget = stub_class("QWidget")
    qtwidgets_module.QVBoxLayout = stub_class("QVBoxLayout")
    qtwidgets_module.QHBoxLayout = stub_class("QHBoxLayout")
    qtwidgets_module.QGridLayout = stub_class("QGridLayout")
    qtwidgets_module.QPushButton = stub_class("QPushButton")
    qtwidgets_module.QLabel = stub_class("QLabel")
    qtwidgets_module.QListWidget = stub_class("QListWidget")
    qtwidgets_module.QListWidgetItem = stub_class("QListWidgetItem")
    qtwidgets_module.QGroupBox = stub_class("QGroupBox")
    qtwidgets_module.QFileDialog = stub_class("QFileDialog")
    qtwidgets_module.QLineEdit = stub_class("QLineEdit")
    qtwidgets_module.QSpinBox = stub_class("QSpinBox")
    qtwidgets_module.QScrollArea = stub_class("QScrollArea")
    qtwidgets_module.QComboBox = stub_class("QComboBox")
    qtwidgets_module.QStackedWidget = stub_class("QStackedWidget")
    qtwidgets_module.QToolButton = stub_class("QToolButton")
    qtwidgets_module.QMessageBox = stub_class("QMessageBox")
    qtwidgets_module.QStyle = stub_class("QStyle")

    qtgui_module = types.ModuleType("qgis.PyQt.QtGui")
    qtgui_module.QColor = stub_class("QColor")
    qtgui_module.QFont = stub_class("QFont")
    qtgui_module.QIcon = stub_class("QIcon")

    qtcore_module = types.ModuleType("qgis.PyQt.QtCore")
    qtcore_module.Qt = stub_class("Qt")
    qtcore_module.QTimer = FakeTimer
    qtcore_module.QSettings = stub_class("QSettings")
    qtcore_module.QObject = stub_class("QObject")
    qtcore_module.pyqtSignal = lambda *args, **kwargs: MagicMock()

    sys.modules["qgis.PyQt.QtWidgets"] = qtwidgets_module
    sys.modules["qgis.PyQt.QtGui"] = qtgui_module
    sys.modules["qgis.PyQt.QtCore"] = qtcore_module
    if "qgis.PyQt" in sys.modules:
        sys.modules["qgis.PyQt"].QtWidgets = qtwidgets_module
        sys.modules["qgis.PyQt"].QtGui = qtgui_module
        sys.modules["qgis.PyQt"].QtCore = qtcore_module

    if "sartracker.ui.sar_panel" in sys.modules:
        del sys.modules["sartracker.ui.sar_panel"]
    sar_panel = importlib.import_module("sartracker.ui.sar_panel")
    SARPanel = sar_panel.SARPanel

    with patch("sartracker.ui.sar_panel.QTimer", FakeTimer), \
         patch.object(SARPanel, "_setup_ui", lambda self: None), \
         patch.object(SARPanel, "_initialize_auto_settings", lambda self: None), \
         patch.object(SARPanel, "_refresh_mission_controls", lambda self: None):
        panel = SARPanel(None, None, None)

    panel.auto_refresh_enabled = True
    panel.auto_refresh_interval_seconds = 5
    panel._is_active = True
    panel._mission_state = MissionState.ACTIVE

    panel._apply_auto_refresh_timer()
    assert panel.refresh_timer.isActive() is True

    panel.closeEvent(MagicMock())
    panel.showEvent(MagicMock())

    assert panel.refresh_timer.isActive() is True
