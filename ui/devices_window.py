# -*- coding: utf-8 -*-
"""
Devices Window

Standalone window for displaying connected tracking devices.
Replaces the cramped Devices section in the SAR Panel with a full-height,
resizable window accessible from a dedicated toolbar icon.

Qt5/Qt6 Compatible: Uses qgis.PyQt imports and qt_compat helpers.
"""

from typing import Dict, List, Optional

from qgis.PyQt.QtCore import pyqtSignal, QSettings
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget,
    QListWidgetItem, QPushButton, QLabel, QApplication
)

# sip for checking deleted Qt objects
try:
    from qgis.PyQt.sip import isdeleted as sip_isdeleted
except ImportError:
    try:
        import sip
        sip_isdeleted = sip.isdeleted
    except ImportError:
        sip_isdeleted = lambda obj: False

from ..utils.dialog_utils import BaseDialog
from ..utils.qt_compat import WA_DeleteOnClose, UserRole


class DevicesWindow(BaseDialog):
    """
    Standalone window for displaying connected tracking devices.

    Shows device name, status (online/offline/unknown), and last update time.
    Designed to be opened to ~90% screen height for better visibility than
    the cramped panel section.

    Signals:
        closed: Emitted when window is closed
        device_selected(str): Emitted with device_id when a device is selected
        refresh_requested: Emitted when manual refresh is requested
    """

    closed = pyqtSignal()
    device_selected = pyqtSignal(str)
    refresh_requested = pyqtSignal()

    # Settings keys for window geometry
    SETTINGS_GEOMETRY_KEY = "SARTracker/DevicesWindow/geometry"

    def __init__(self, parent=None):
        super().__init__(parent)

        self._cleanup_in_progress = False
        self._devices: List[Dict] = []

        self._setup_ui()
        self._load_settings()

    def _setup_ui(self):
        """Build the window UI."""
        self.setWindowTitle("Connected Devices")
        self.setMinimumSize(400, 300)

        # Ensure the window is destroyed on close to avoid orphaned dialogs
        self.setAttribute(WA_DeleteOnClose, True)

        layout = QVBoxLayout()
        layout.setContentsMargins(8, 8, 8, 8)

        # Header label
        header = QLabel("Connected Devices")
        header.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(header)

        # Device list - no max height, fills available space
        self.devices_list = QListWidget()
        self.devices_list.setAlternatingRowColors(True)
        self.devices_list.itemClicked.connect(self._on_device_clicked)
        self.devices_list.itemDoubleClicked.connect(self._on_device_double_clicked)
        layout.addWidget(self.devices_list, 1)  # stretch factor 1

        # Button bar
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setToolTip("Request device list refresh")
        self.refresh_button.clicked.connect(self._on_refresh_clicked)
        button_layout.addWidget(self.refresh_button)

        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        button_layout.addWidget(self.close_button)

        layout.addLayout(button_layout)

        self.setLayout(layout)

    def _setup_default_geometry(self):
        """Set default size to ~90% of screen height if no saved geometry."""
        screen = QApplication.primaryScreen()
        if screen:
            available = screen.availableGeometry()
            target_height = int(available.height() * 0.9)
            target_width = 500
            x = available.right() - target_width - 50  # Near right edge
            y = (available.height() - target_height) // 2
            self.setGeometry(x, y, target_width, target_height)

    def _load_settings(self):
        """Restore window geometry from settings."""
        settings = QSettings()
        geometry = settings.value(self.SETTINGS_GEOMETRY_KEY)
        if geometry:
            self.restoreGeometry(geometry)
        else:
            # First time - use default tall geometry
            self._setup_default_geometry()

    def _save_settings(self):
        """Persist window geometry to settings."""
        settings = QSettings()
        settings.setValue(self.SETTINGS_GEOMETRY_KEY, self.saveGeometry())

    def update_devices(self, devices: List[Dict]):
        """
        Update the device list display.

        Args:
            devices: List of device dicts, each containing:
                - device_id: str (required)
                - name: str (required)
                - status: str ('online', 'offline', or 'unknown')
                - last_update: str (ISO8601 timestamp or human-readable)
        """
        if self._cleanup_in_progress:
            return

        self._devices = devices or []
        self.devices_list.clear()

        if devices is None:
            return

        if not isinstance(devices, list):
            print("[DevicesWindow] WARNING: devices must be a list")
            return

        for device in devices:
            if not isinstance(device, dict):
                continue

            device_id = device.get('device_id') or device.get('id') or 'Unknown'
            device_name = device.get('name') or device_id
            status = device.get('status', 'unknown')
            last_update = device.get('last_update', 'Never')

            # Format display text with status indicator
            if status == 'online':
                text = f"\U0001F7E2 {device_name}"  # Green circle
            elif status == 'offline':
                text = f"\U0001F534 {device_name}"  # Red circle
            else:
                text = f"\U000026AA {device_name}"  # White circle

            text += f"\n  Last: {last_update}"

            item = QListWidgetItem(text)
            item.setData(UserRole, device_id)
            self.devices_list.addItem(item)

    def get_device_count(self) -> int:
        """Return the number of devices currently displayed."""
        return self.devices_list.count()

    def _on_device_clicked(self, item: QListWidgetItem):
        """Handle single click on device item."""
        device_id = item.data(UserRole)
        if device_id:
            self.device_selected.emit(str(device_id))

    def _on_device_double_clicked(self, item: QListWidgetItem):
        """Handle double click on device item (future: zoom to device)."""
        device_id = item.data(UserRole)
        if device_id:
            # For now, just emit selection signal
            # Future enhancement: emit zoom_to_device signal
            self.device_selected.emit(str(device_id))

    def _on_refresh_clicked(self):
        """Handle refresh button click."""
        self.refresh_requested.emit()

    def showEvent(self, event):
        """Handle show event."""
        super().showEvent(event)
        # Emit refresh request when shown (if not cleaning up)
        if not self._cleanup_in_progress:
            self.refresh_requested.emit()

    def closeEvent(self, event):
        """Handle close event - cleanup, save state, and emit signal."""
        # Emit closed signal before cleanup (cleanup blocks signals)
        try:
            self.closed.emit()
        except Exception:
            pass

        # Run cleanup before destruction
        self.cleanup()
        super().closeEvent(event)

    def cleanup(self):
        """Clean up resources before destruction."""
        # Guard against double cleanup
        if self._cleanup_in_progress:
            return
        self._cleanup_in_progress = True

        # Block signals to prevent emissions during destruction
        try:
            self.blockSignals(True)
        except Exception:
            pass

        # Save settings first
        try:
            self._save_settings()
        except Exception as exc:
            print(f"[DevicesWindow] Warning: Failed to save settings: {exc}")

        # Disconnect button signals
        try:
            self.refresh_button.clicked.disconnect(self._on_refresh_clicked)
        except (TypeError, RuntimeError):
            pass

        try:
            self.close_button.clicked.disconnect(self.close)
        except (TypeError, RuntimeError):
            pass

        # Disconnect list signals
        try:
            self.devices_list.itemClicked.disconnect(self._on_device_clicked)
        except (TypeError, RuntimeError):
            pass

        try:
            self.devices_list.itemDoubleClicked.disconnect(self._on_device_double_clicked)
        except (TypeError, RuntimeError):
            pass

        # Clear data
        self._devices = []
        if self.devices_list and not sip_isdeleted(self.devices_list):
            try:
                self.devices_list.clear()
            except Exception:
                pass


__all__ = ['DevicesWindow']
