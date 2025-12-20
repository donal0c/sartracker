# -*- coding: utf-8 -*-
"""
Mission Logs Window

Non-modal window for end-of-mission review combining:
- Layer Console view (hierarchical layer/feature browser)
- Marker Log view (searchable marker list)
- Mission Details view (summary information)

Qt5/Qt6 Compatible: Uses qgis.PyQt imports and qt_compat helpers.
"""

from typing import Callable, Dict, List, Optional, Any

from qgis.PyQt.QtCore import pyqtSignal, QSettings
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QGroupBox,
    QLabel, QTextEdit, QPushButton
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
from ..utils.qt_compat import WA_DeleteOnClose
from .layer_console_widget import LayerConsoleWidget
from .marker_log_widget import MarkerLogWidget


class MissionDetailsWidget(QWidget):
    """
    Widget displaying mission summary information.

    Shows:
    - Mission name and status
    - Start/end times
    - Coordinators on duty
    - Storage paths
    - Layer/feature counts
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mission_info: Dict[str, Any] = {}
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        # Mission info group
        info_group = QGroupBox("Mission Information")
        info_layout = QVBoxLayout()

        self.info_text = QTextEdit()
        self.info_text.setReadOnly(True)
        self.info_text.setPlaceholderText("No mission loaded")
        info_layout.addWidget(self.info_text)

        info_group.setLayout(info_layout)
        layout.addWidget(info_group)

        # Statistics group
        stats_group = QGroupBox("Statistics")
        stats_layout = QVBoxLayout()

        self.stats_text = QTextEdit()
        self.stats_text.setReadOnly(True)
        self.stats_text.setPlaceholderText("No statistics available")
        stats_layout.addWidget(self.stats_text)

        stats_group.setLayout(stats_layout)
        layout.addWidget(stats_group)

        # Refresh button
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self._on_refresh)
        button_layout.addWidget(self.refresh_button)
        layout.addLayout(button_layout)

        self.setLayout(layout)

    def set_mission_info(self, info: Dict[str, Any]):
        """Update displayed mission information."""
        self._mission_info = info or {}
        self._update_display()

    def _update_display(self):
        """Refresh the display from current mission info."""
        info = self._mission_info

        if not info:
            self.info_text.setPlainText("No mission loaded.\n\nStart or resume a mission to see details here.")
            self.stats_text.clear()
            return

        # Build mission info text
        lines = []

        mission_name = info.get("name") or info.get("mission_name", "Unknown")
        lines.append(f"Mission: {mission_name}")

        status = info.get("status", "unknown")
        lines.append(f"Status: {status.title()}")

        if info.get("start_time"):
            lines.append(f"Started: {info['start_time']}")

        if info.get("end_time"):
            lines.append(f"Ended: {info['end_time']}")

        coordinators = info.get("coordinators", "")
        if coordinators:
            # Format coordinators for display
            if isinstance(coordinators, list):
                coord_display = ", ".join(coordinators)
            else:
                coord_display = str(coordinators).replace(",", ", ")
            lines.append(f"Coordinators: {coord_display}")

        if info.get("primary_store"):
            lines.append(f"\nPrimary Store:\n  {info['primary_store']}")

        if info.get("backup_store"):
            lines.append(f"Backup Store:\n  {info['backup_store']}")

        self.info_text.setPlainText("\n".join(lines))

        # Build statistics text
        stats_lines = []

        layer_count = info.get("layer_count", 0)
        feature_count = info.get("feature_count", 0)
        marker_count = info.get("marker_count", 0)

        stats_lines.append(f"Layers: {layer_count}")
        stats_lines.append(f"Total Features: {feature_count}")
        stats_lines.append(f"Markers: {marker_count}")

        if info.get("tracking_devices"):
            stats_lines.append(f"Tracking Devices: {info['tracking_devices']}")

        if info.get("breadcrumb_count"):
            stats_lines.append(f"Breadcrumb Points: {info['breadcrumb_count']}")

        # SAR-31a: Show warning if data may be incomplete
        if info.get("data_incomplete"):
            stats_lines.append("")
            stats_lines.append("⚠ Some statistics may be incomplete")

        self.stats_text.setPlainText("\n".join(stats_lines) if stats_lines else "No statistics available")

    def _on_refresh(self):
        """Handle refresh button click - re-display current data."""
        self._update_display()

    def cleanup(self):
        """Clean up resources."""
        try:
            self.refresh_button.clicked.disconnect(self._on_refresh)
        except (TypeError, RuntimeError):
            pass
        self._mission_info = {}


class MissionLogsWindow(BaseDialog):
    """
    Non-modal window for end-of-mission review.

    Combines Layer Console, Marker Log, and Mission Details in a tabbed interface
    suitable for reviewing mission data at any time, especially end-of-mission.

    Signals:
        closed(): Emitted when window is closed

        # Marker Log signals
        zoom_requested(float lat, float lon): Zoom to coordinates
        edit_marker_requested(str marker_type, str marker_id): Edit a marker
        delete_marker_requested(str marker_type, str marker_id): Delete a marker
        open_attachment_requested(str path): Open an attachment file

        # Layer Console signals - forwarded from LayerConsoleWidget
        feature_zoom_requested(str layer_id, object feature_id): Zoom to feature
        feature_delete_requested(str layer_id, object feature_id): Delete a feature
        feature_rename_requested(str layer_id, object feature_id, str new_name): Rename feature
        bulk_delete_requested(str layer_id, list feature_ids): Bulk delete features
        visibility_toggled(str layer_id, bool visible): Toggle layer visibility
        layer_alias_change_requested(str layer_id, str new_alias): Change layer alias
        layer_favorite_toggled(str layer_id, bool is_favorite): Toggle favorite status
        move_to_section_requested(int feature_id, str section): Move search area to section
        reorder_requested(str layer_id, list feature_ids): Reorder features
        layer_console_refresh_requested(): Manual refresh requested
    """

    closed = pyqtSignal()

    # Marker Log signals
    zoom_requested = pyqtSignal(float, float)
    edit_marker_requested = pyqtSignal(str, str)
    delete_marker_requested = pyqtSignal(str, str)
    open_attachment_requested = pyqtSignal(str)

    # Layer Console signals
    feature_zoom_requested = pyqtSignal(str, object)
    feature_delete_requested = pyqtSignal(str, object)
    feature_rename_requested = pyqtSignal(str, object, str)
    bulk_delete_requested = pyqtSignal(str, list)
    visibility_toggled = pyqtSignal(str, bool)
    layer_alias_change_requested = pyqtSignal(str, str)
    layer_favorite_toggled = pyqtSignal(str, bool)
    move_to_section_requested = pyqtSignal(int, str)
    reorder_requested = pyqtSignal(str, list)
    layer_console_refresh_requested = pyqtSignal()

    # Settings keys for window geometry
    SETTINGS_GEOMETRY_KEY = "SARTracker/MissionLogsWindow/geometry"
    SETTINGS_SPLITTER_KEY = "SARTracker/MissionLogsWindow/splitter"
    SETTINGS_TAB_KEY = "SARTracker/MissionLogsWindow/activeTab"

    def __init__(self, parent=None):
        super().__init__(parent)

        self._layer_console: Optional[LayerConsoleWidget] = None
        self._marker_log: Optional[MarkerLogWidget] = None
        self._mission_details: Optional[MissionDetailsWidget] = None
        self._catalog_service = None
        self._marker_fetcher: Optional[Callable[[], List[Dict]]] = None
        self._mission_info_fetcher: Optional[Callable[[], Dict[str, Any]]] = None
        self._cleanup_in_progress = False

        self._setup_ui()
        self._load_settings()

    def _setup_ui(self):
        """Build the window UI."""
        self.setWindowTitle("Mission Logs")
        self.setMinimumSize(800, 600)
        # Ensure the window is actually destroyed on close to avoid orphaned
        # dialogs accumulating during long-running ops sessions.
        self.setAttribute(WA_DeleteOnClose, True)

        layout = QVBoxLayout()
        layout.setContentsMargins(8, 8, 8, 8)

        # Tab widget for the three views
        self.tab_widget = QTabWidget()

        # Layer Console tab
        self._layer_console = LayerConsoleWidget()
        self.tab_widget.addTab(self._layer_console, "Layer Console")

        # Marker Log tab
        self._marker_log = MarkerLogWidget()
        self.tab_widget.addTab(self._marker_log, "Marker Log")

        # Mission Details tab
        self._mission_details = MissionDetailsWidget()
        self.tab_widget.addTab(self._mission_details, "Mission Details")

        layout.addWidget(self.tab_widget)

        # Bottom button bar
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.refresh_all_button = QPushButton("Refresh All")
        self.refresh_all_button.setToolTip("Refresh all tabs")
        self.refresh_all_button.clicked.connect(self._refresh_all)
        button_layout.addWidget(self.refresh_all_button)

        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        button_layout.addWidget(self.close_button)

        layout.addLayout(button_layout)

        self.setLayout(layout)

        # Connect signals from child widgets
        self._wire_signals()

    def _wire_signals(self):
        """Connect signals from child widgets to window signals."""
        if self._layer_console:
            # Forward all layer console signals
            self._layer_console.feature_zoom_requested.connect(self.feature_zoom_requested.emit)
            self._layer_console.feature_delete_requested.connect(self.feature_delete_requested.emit)
            self._layer_console.feature_rename_requested.connect(self.feature_rename_requested.emit)
            self._layer_console.bulk_delete_requested.connect(self.bulk_delete_requested.emit)
            self._layer_console.visibility_toggled.connect(self.visibility_toggled.emit)
            self._layer_console.layer_alias_change_requested.connect(self.layer_alias_change_requested.emit)
            self._layer_console.layer_favorite_toggled.connect(self.layer_favorite_toggled.emit)
            self._layer_console.move_to_section_requested.connect(self.move_to_section_requested.emit)
            self._layer_console.reorder_requested.connect(self.reorder_requested.emit)
            self._layer_console.refresh_requested.connect(self.layer_console_refresh_requested.emit)

        if self._marker_log:
            # Forward marker signals
            self._marker_log.zoom_requested.connect(self.zoom_requested.emit)
            self._marker_log.edit_requested.connect(self.edit_marker_requested.emit)
            self._marker_log.delete_requested.connect(self.delete_marker_requested.emit)
            self._marker_log.open_attachment_requested.connect(self.open_attachment_requested.emit)

    def set_catalog_service(self, catalog):
        """
        Set the layer catalog service for the Layer Console.

        Args:
            catalog: LayerCatalogService instance
        """
        self._catalog_service = catalog
        if self._layer_console:
            self._layer_console.set_catalog(catalog)

    def set_marker_fetcher(self, fetcher: Callable[[], List[Dict]]):
        """
        Set the marker data fetcher for the Marker Log.

        Args:
            fetcher: Callable that returns list of marker dicts
        """
        self._marker_fetcher = fetcher
        if self._marker_log:
            self._marker_log.set_data_fetcher(fetcher)

    def set_mission_info_fetcher(self, fetcher: Callable[[], Dict[str, Any]]):
        """
        Set the mission info fetcher for the Mission Details tab.

        Args:
            fetcher: Callable that returns mission info dict
        """
        self._mission_info_fetcher = fetcher

    def refresh(self):
        """Refresh all tabs with current data."""
        self._refresh_all()

    def _refresh_all(self):
        """Refresh all three tabs."""
        # Refresh layer console
        if self._layer_console and not sip_isdeleted(self._layer_console):
            try:
                self._layer_console.refresh(full=True)
            except Exception as exc:
                print(f"[MissionLogsWindow] Warning: Layer console refresh failed: {exc}")

        # Refresh marker log
        if self._marker_log and not sip_isdeleted(self._marker_log):
            try:
                self._marker_log.refresh()
            except Exception as exc:
                print(f"[MissionLogsWindow] Warning: Marker log refresh failed: {exc}")

        # Refresh mission details
        if self._mission_details and self._mission_info_fetcher and not sip_isdeleted(self._mission_details):
            try:
                info = self._mission_info_fetcher()
                self._mission_details.set_mission_info(info)
            except Exception as exc:
                print(f"[MissionLogsWindow] Failed to fetch mission info: {exc}")
                self._mission_details.set_mission_info({})

    def _save_settings(self):
        """Persist window state."""
        settings = QSettings()
        settings.setValue(self.SETTINGS_GEOMETRY_KEY, self.saveGeometry())
        settings.setValue(self.SETTINGS_TAB_KEY, self.tab_widget.currentIndex())

    def _load_settings(self):
        """Restore window state."""
        settings = QSettings()

        # Restore geometry
        geometry = settings.value(self.SETTINGS_GEOMETRY_KEY)
        if geometry:
            self.restoreGeometry(geometry)

        # Restore active tab
        tab_index = settings.value(self.SETTINGS_TAB_KEY, 0, type=int)
        if 0 <= tab_index < self.tab_widget.count():
            self.tab_widget.setCurrentIndex(tab_index)

    def showEvent(self, event):
        """Handle show event - refresh data when window is shown."""
        super().showEvent(event)
        # Refresh on show to ensure data is current
        if not self._cleanup_in_progress:
            self._refresh_all()

    def closeEvent(self, event):
        """Handle close event - cleanup, save state, and emit signal."""
        # Emit closed signal before cleanup. cleanup() blocks signals to reduce
        # teardown races, so emitting after cleanup can suppress delivery.
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
            print(f"[MissionLogsWindow] Warning: Failed to save settings: {exc}")

        # Clean up child widgets (check for deleted Qt objects)
        if self._layer_console and not sip_isdeleted(self._layer_console):
            try:
                self._layer_console.cleanup()
            except Exception as exc:
                print(f"[MissionLogsWindow] Warning: Layer console cleanup failed: {exc}")

        if self._marker_log and not sip_isdeleted(self._marker_log):
            try:
                self._marker_log.cleanup()
            except Exception as exc:
                print(f"[MissionLogsWindow] Warning: Marker log cleanup failed: {exc}")

        if self._mission_details and not sip_isdeleted(self._mission_details):
            try:
                self._mission_details.cleanup()
            except Exception as exc:
                print(f"[MissionLogsWindow] Warning: Mission details cleanup failed: {exc}")

        # Disconnect button signals
        try:
            self.refresh_all_button.clicked.disconnect(self._refresh_all)
        except (TypeError, RuntimeError):
            pass

        try:
            self.close_button.clicked.disconnect(self.close)
        except (TypeError, RuntimeError):
            pass

        # Clear references
        self._catalog_service = None
        self._marker_fetcher = None
        self._mission_info_fetcher = None
        self._layer_console = None
        self._marker_log = None
        self._mission_details = None


__all__ = ['MissionLogsWindow', 'MissionDetailsWidget']
