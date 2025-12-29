# -*- coding: utf-8 -*-
"""
SAR Panel UI

Main docked control panel for SAR tracking operations.
"""

from qgis.PyQt.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QListWidget, QListWidgetItem,
    QGroupBox, QFileDialog, QLineEdit,
    QScrollArea, QComboBox, QStackedWidget,
    QToolButton, QMessageBox, QStyle
)
from qgis.PyQt.QtCore import Qt, QTimer, pyqtSignal, QSettings, QObject
from qgis.PyQt.QtGui import QColor, QFont, QIcon
try:
    from qgis.PyQt.sip import isdeleted as sip_isdeleted
except ImportError:
    try:
        import sip
        sip_isdeleted = sip.isdeleted
    except ImportError:
        # Fallback: always assume objects are valid
        sip_isdeleted = lambda obj: False

# Create sip namespace for compatibility
class sip:
    isdeleted = staticmethod(sip_isdeleted)
from datetime import datetime
from typing import Optional, List, Dict, Any, Callable, Tuple
import json
import os
import getpass

# Import Qt5/Qt6 compatible constants and functions
from ..utils.qt_compat import (
    LeftDockWidgetArea, RightDockWidgetArea, AlignRight,
    ToolButtonTextBesideIcon, PointingHandCursor,
    MessageBoxYes, MessageBoxNo
)
from ..utils.notify import info, warning, error, success
from ..config.keys import ConfigStore, SETTINGS_KEYS
from ..controllers.mission_controller import MissionState


class SARPanel(QDockWidget):
    """
    Main SAR tracking control panel.
    
    Signals:
        refresh_requested: Emitted when manual refresh requested
        csv_load_requested: Emitted when user wants to load CSV (file_path: str)
        marker_edit_requested: Emitted when user requests marker edit
        marker_delete_requested: Emitted when user requests marker delete
        marker_zoom_requested: Emitted when user wants to zoom to marker
    """
    
    refresh_requested = pyqtSignal()
    csv_load_requested = pyqtSignal(str)  # file_path
    add_poi_requested = pyqtSignal()
    add_clue_requested = pyqtSignal()
    add_casualty_requested = pyqtSignal()
    add_hazard_requested = pyqtSignal()
    line_tool_requested = pyqtSignal()
    polygon_tool_requested = pyqtSignal()
    range_rings_tool_requested = pyqtSignal()
    bearing_tool_requested = pyqtSignal()
    coordinate_converter_requested = pyqtSignal()
    measure_distance_requested = pyqtSignal()
    autosave_requested = pyqtSignal()  # Request to save project
    clear_measurements_requested = pyqtSignal()
    marker_edit_requested = pyqtSignal(str, str)
    marker_delete_requested = pyqtSignal(str, str)
    marker_zoom_requested = pyqtSignal(float, float)
    attachment_open_requested = pyqtSignal(str)
    unlock_mission_requested = pyqtSignal()
    gpx_import_file_requested = pyqtSignal(str)  # file_path
    gpx_import_folder_requested = pyqtSignal(str)  # folder_path
    gpx_watch_folder_requested = pyqtSignal(str)  # folder_path
    finalize_mission_requested = pyqtSignal()  # Request to finalize and archive mission

    # Phase N1: Provider signals removed - configuration moved to Settings Panel

    def __init__(self, parent=None, mission_controller=None, layers_controller=None):
        super().__init__("SAR Tracking", parent)
        
        self.setAllowedAreas(LeftDockWidgetArea | RightDockWidgetArea)
        
        # State
        self._mission_controller = mission_controller
        self._layers_controller = layers_controller
        self._mission_state = MissionState.IDLE
        self.auto_refresh_enabled = False
        self.auto_refresh_interval_seconds = SETTINGS_KEYS.AUTO_REFRESH_INTERVAL_DEFAULT
        self.autosave_enabled = False
        self.autosave_interval_minutes = SETTINGS_KEYS.AUTO_SAVE_INTERVAL_DEFAULT
        self.last_autosave_time = None
        self._last_autosave_success: Optional[bool] = None
        self.focus_mode_active = False
        self.hidden_panels = []  # Track which panels we hid
        self._pause_flash = False
        self._is_finalized = False
        self._is_active = True
        self._audit_warning_logged = False
        self._mission_controller_connections: List[Tuple[Any, Callable]] = []

        # Setup UI
        self._setup_ui()

        # NOTE: Layer Console and Marker Log widgets moved to Mission Logs window
        # Access via menu: SAR Tracker > Mission Logs...

        # Setup auto-refresh timer (Issue #5: Parent = self for proper Qt lifecycle)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self._on_auto_refresh)

        # Setup auto-save timer
        self.autosave_timer = QTimer(self)
        self.autosave_timer.timeout.connect(self._on_autosave)

        # Timer for flashing pause button when paused
        self.pause_flash_timer = QTimer(self)
        self.pause_flash_timer.setInterval(600)
        self.pause_flash_timer.timeout.connect(self._toggle_pause_flash)

        # Load persisted defaults for auto-refresh / auto-save
        self._initialize_auto_settings()

        # Bind mission controller signals if available
        if self._mission_controller:
            # Track connections for proper cleanup (CRITICAL FIX: Issue #1.8)
            conn1 = (self._mission_controller.mission_state_changed, self._on_controller_state_changed)
            conn1[0].connect(conn1[1])
            self._mission_controller_connections.append(conn1)

            conn2 = (self._mission_controller.mission_timing_updated, self.update_mission_timers)
            conn2[0].connect(conn2[1])
            self._mission_controller_connections.append(conn2)

            # Ensure UI reflects existing mission state (e.g., after resume)
            try:
                controller_state = self._mission_controller.state
                snapshot = self._mission_controller.status_snapshot()
                context = {
                    "mission_name": snapshot.get("mission_name"),
                    "started_at": snapshot.get("started_at"),
                    "paused_since": snapshot.get("paused_since")
                }
                self._on_controller_state_changed(controller_state, context)
                self.update_mission_timers(
                    snapshot.get("elapsed_seconds", 0.0),
                    snapshot.get("active_seconds", 0.0)
                )
            except Exception as sync_error:
                print(f"[SARPanel] Warning: Failed to sync mission state: {sync_error}")
        self._refresh_mission_controls()

    def _on_open_attachment_requested(self, path: str):
        """Bubble attachment open requests to the plugin."""
        self.attachment_open_requested.emit(path)

    def _on_marker_edit_requested(self, marker_type: str, marker_id: str):
        """Forward marker edit request to the plugin."""
        self.marker_edit_requested.emit(marker_type, marker_id)

    def _on_marker_delete_requested(self, marker_type: str, marker_id: str):
        """Forward marker delete request to the plugin."""
        self.marker_delete_requested.emit(marker_type, marker_id)

    def _on_marker_zoom_requested(self, lat: float, lon: float):
        """Forward marker zoom request to the plugin."""
        self.marker_zoom_requested.emit(lat, lon)

    def _current_user_name(self) -> str:
        """Get the current user name for audit logging with fallbacks."""
        try:
            stored_name = QSettings().value("sartracker/coordinator_name")
            if stored_name:
                return str(stored_name)
        except Exception as settings_error:
            print(f"[SARPanel] Warning: Failed to read coordinator name: {settings_error}")

        try:
            from qgis.core import QgsApplication
            user = QgsApplication.userFullName()
            if user:
                return user
        except Exception as qgis_error:
            print(f"[SARPanel] Warning: Failed to read QGIS user name: {qgis_error}")

        try:
            user = getpass.getuser()
            if user:
                return user
        except Exception as os_error:
            print(f"[SARPanel] Warning: Failed to read system user name: {os_error}")

        if not getattr(self, "_user_name_warning_logged", False):
            print("[SARPanel] Warning: Could not determine user name; using 'Unknown'")
            self._user_name_warning_logged = True
        return "Unknown"

    def _get_audit_log_path(self) -> Optional[str]:
        """Get path to audit log file.

        Returns:
            Path to logs/audit.jsonl, or None if cannot determine
        """
        try:
            from qgis.core import QgsProject
            project = QgsProject.instance()
            project_path = project.fileName()

            if not project_path:
                # No project loaded, use plugin directory
                plugin_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                logs_dir = os.path.join(plugin_dir, "logs")
            else:
                # Use project directory
                project_dir = os.path.dirname(project_path)
                logs_dir = os.path.join(project_dir, "logs")

            # Create logs directory if it doesn't exist
            os.makedirs(logs_dir, exist_ok=True)

            return os.path.join(logs_dir, "audit.jsonl")
        except Exception as e:
            print(f"[SARPanel] Warning: Could not determine audit log path: {e}")
            return None

    def _log_audit(self, operation: str, layer_id: str, count: int, **kwargs):
        """Log an audit entry to the audit log file.

        Args:
            operation: Operation type (e.g., "bulk_delete")
            layer_id: Layer identifier
            count: Number of items affected
            **kwargs: Additional context to log
        """
        audit_path = self._get_audit_log_path()
        if not audit_path:
            print(f"[SARPanel] Warning: Audit logging disabled (no path available)")
            if not self._audit_warning_logged:
                self._notify(warning, "Audit Logging", "Audit log unavailable; actions will not be recorded.")
                self._audit_warning_logged = True
            return

        try:
            entry = {
                "timestamp": datetime.now().isoformat(),
                "user": self._current_user_name(),
                "operation": operation,
                "layer_id": layer_id,
                "count": count
            }
            entry.update(kwargs)

            # Append to audit log (JSONL format - one JSON object per line)
            with open(audit_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")

            print(f"[SARPanel] Audit: {operation} on {layer_id} by {entry['user']} (count={count})")
            self._audit_warning_logged = False
        except Exception as e:
            print(f"[SARPanel] ERROR: Failed to write audit log: {e}")
            if not self._audit_warning_logged:
                self._notify(error, "Audit Logging", f"Failed to write audit log: {e}")
                self._audit_warning_logged = True

    def _standard_icon(self, *enum_names: str) -> QIcon:
        """
        Resolve a QStyle standard icon with graceful fallbacks.

        Qt 6 distributions occasionally omit certain enum values (e.g.,
        SP_TitleBarMaxButton). This helper tries each enum name in order and
        falls back to an empty QIcon if none are available.
        """
        style = self.style()
        for name in enum_names:
            icon_enum = getattr(QStyle, name, None)
            if icon_enum is None:
                continue
            icon = style.standardIcon(icon_enum)
            if not icon.isNull():
                return icon
        return QIcon()
        
    def _setup_ui(self):
        """Build the panel UI."""
        main_widget = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # Focus Mode Toggle (at top)
        focus_layout = QHBoxLayout()
        self.focus_mode_button = QToolButton()
        self.focus_mode_button.setText("Enter Focus Mode")
        self.focus_mode_button.setToolButtonStyle(ToolButtonTextBesideIcon)
        self.focus_mode_button.setAutoRaise(False)
        self.focus_mode_button.setCursor(PointingHandCursor)
        self.focus_mode_button.setIcon(
            self._standard_icon("SP_TitleBarMaxButton", "SP_TitleBarNormalButton", "SP_DialogYesButton")
        )
        self.focus_mode_button.clicked.connect(self._toggle_focus_mode)
        self.focus_mode_button.setToolTip(
            "Hide other QGIS panels for cleaner workspace.\n"
            "Press F11 for full-screen mode."
        )
        focus_layout.addWidget(self.focus_mode_button)
        layout.addLayout(focus_layout)
        self._apply_focus_mode_style()

        # Mission Info Section
        mission_group = QGroupBox("Mission")
        mission_layout = QVBoxLayout()
        
        # Mission name input
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("Name:"))
        self.mission_name_input = QLineEdit()
        self.mission_name_input.setPlaceholderText("Enter mission name...")
        name_layout.addWidget(self.mission_name_input)
        mission_layout.addLayout(name_layout)
        
        # Mission status
        self.mission_status_label = QLabel("Status: <b>No active mission</b>")
        mission_layout.addWidget(self.mission_status_label)
        
        # Mission timers
        timer_grid = QGridLayout()
        timer_font = QFont("Courier New", 12)
        if not timer_font.exactMatch():
            timer_font = QFont("Monospace", 12)

        elapsed_label = QLabel("Elapsed")
        active_label = QLabel("Active Search")
        self.elapsed_time_value = QLabel("00:00:00")
        self.active_time_value = QLabel("00:00:00")
        self.elapsed_time_value.setFont(timer_font)
        self.active_time_value.setFont(timer_font)
        self.elapsed_time_value.setAlignment(AlignRight)
        self.active_time_value.setAlignment(AlignRight)

        timer_grid.addWidget(elapsed_label, 0, 0)
        timer_grid.addWidget(self.elapsed_time_value, 0, 1)
        timer_grid.addWidget(active_label, 1, 0)
        timer_grid.addWidget(self.active_time_value, 1, 1)
        mission_layout.addLayout(timer_grid)
        
        # Mission controls
        controls_layout = QHBoxLayout()
        
        self.start_button = QToolButton()
        self.start_button.setText("Start Mission")
        self.start_button.setIcon(self._standard_icon("SP_MediaPlay", "SP_ArrowForward"))
        self.start_button.clicked.connect(self._on_start_mission)
        controls_layout.addWidget(self.start_button)
        
        self.pause_button = QToolButton()
        self.pause_button.setText("Pause")
        self.pause_button.setIcon(self._standard_icon("SP_MediaPause", "SP_DialogApplyButton"))
        self.pause_button.clicked.connect(self._on_pause_mission)
        self.pause_button.setEnabled(False)
        controls_layout.addWidget(self.pause_button)
        
        self.finish_button = QToolButton()
        self.finish_button.setText("End Mission")
        self.finish_button.setIcon(self._standard_icon("SP_DialogCloseButton", "SP_DialogCancelButton"))
        self.finish_button.clicked.connect(self._on_finish_mission)
        self.finish_button.setEnabled(False)
        controls_layout.addWidget(self.finish_button)

        mission_layout.addLayout(controls_layout)

        # Finalize Mission button (shown only when mission ended and not yet finalized)
        finalize_layout = QHBoxLayout()
        self.finalize_button = QPushButton("Finalize Mission (Archive & Lock)")
        self.finalize_button.setIcon(self._standard_icon("SP_FileDialogDetailedView", "SP_DirIcon"))
        self.finalize_button.clicked.connect(self._on_finalize_mission)
        self.finalize_button.setVisible(False)  # Hidden until mission ends
        self.finalize_button.setToolTip(
            "Create archive of mission data (.qgz + .gpkg + attachments)\n"
            "and mark as read-only. Use this after mission is complete."
        )
        finalize_layout.addWidget(self.finalize_button)
        mission_layout.addLayout(finalize_layout)
        self._apply_mission_button_styles()

        # Mission storage status
        self.mission_storage_label = QLabel("Storage: <i>Not initialized</i>")
        self.mission_storage_label.setWordWrap(True)
        mission_layout.addWidget(self.mission_storage_label)

        badge_layout = QHBoxLayout()
        self.auto_refresh_status_label = QLabel("Auto Refresh: OFF")
        self.autosave_status_label = QLabel("Auto Save: OFF")
        badge_layout.addWidget(self.auto_refresh_status_label)
        badge_layout.addWidget(self.autosave_status_label)
        badge_layout.addStretch()
        mission_layout.addLayout(badge_layout)
        mission_group.setLayout(mission_layout)
        layout.addWidget(mission_group)

        # NOTE: Layer Console and Marker Log have been moved to the Mission Logs window
        # Access via menu: SAR Tracker > Mission Logs...

        # Devices Section
        devices_group = QGroupBox("Devices")
        devices_layout = QVBoxLayout()
        
        self.devices_list = QListWidget()
        self.devices_list.setMaximumHeight(150)
        devices_layout.addWidget(self.devices_list)
        
        devices_group.setLayout(devices_layout)
        layout.addWidget(devices_group)
        
        # Data Refresh Section (status + manual button)
        refresh_group = QGroupBox("Data Refresh")
        refresh_layout = QVBoxLayout()

        self.refresh_button = QPushButton("Refresh Now")
        self.refresh_button.clicked.connect(self._on_manual_refresh)
        refresh_layout.addWidget(self.refresh_button)

        self.load_csv_button = QPushButton("Load CSV...")
        self.load_csv_button.setToolTip("Load tracking data directly from a Traccar CSV export")
        self.load_csv_button.clicked.connect(self._on_load_csv)
        refresh_layout.addWidget(self.load_csv_button)
        
        refresh_group.setLayout(refresh_layout)
        layout.addWidget(refresh_group)

        # Auto-Save Section (status + manual button)
        autosave_group = QGroupBox("Auto-Save")
        autosave_layout = QVBoxLayout()

        # Manual save button
        self.save_now_button = QPushButton("Save Project Now")
        self.save_now_button.clicked.connect(self._on_manual_save)
        autosave_layout.addWidget(self.save_now_button)

        autosave_group.setLayout(autosave_layout)
        layout.addWidget(autosave_group)

        # ========================================
        # Provider Status Section (Phase N1 - Read-only display)
        # ========================================
        # Note: Provider configuration moved to Settings Panel
        # (Plugins → SAR Tracker → Settings...)
        provider_group = QGroupBox("Data Source Status")
        provider_layout = QVBoxLayout()

        # Read-only provider status display
        self.provider_status_label = QLabel("Provider: None | Status: Not connected")
        self.provider_status_label.setWordWrap(True)
        self.provider_status_label.setStyleSheet(
            "QLabel { "
            "  padding: 8px; "
            "  background-color: #f0f0f0; "
            "  border: 1px solid #ccc; "
            "  border-radius: 3px; "
            "  font-size: 11px; "
            "}"
        )
        self.provider_status_label.setToolTip(
            "Current data provider status.\n"
            "To configure providers, go to:\n"
            "Plugins → SAR Tracker → Settings..."
        )
        provider_layout.addWidget(self.provider_status_label)

        self.data_source_label = QLabel("Source: None")
        self.data_source_label.setStyleSheet(
            "QLabel { "
            "  color: #555; "
            "  font-size: 10px; "
            "}"
        )
        provider_layout.addWidget(self.data_source_label)

        provider_group.setLayout(provider_layout)
        layout.addWidget(provider_group)

        # ========================================
        # Markers & Clues Section
        # ========================================
        markers_group = QGroupBox("Markers & Clues")
        markers_layout = QVBoxLayout()

        # Use grid layout for compact 2-column arrangement
        markers_grid = QGridLayout()

        self.add_ipp_lkp_button = QPushButton("IPP/LKP")
        self.add_ipp_lkp_button.setToolTip(
            "Add Initial Planning Point / Last Known Position\n"
            "The starting point for search planning where the\n"
            "subject was last reliably seen or located."
        )
        self.add_ipp_lkp_button.clicked.connect(self._on_add_poi)
        markers_grid.addWidget(self.add_ipp_lkp_button, 0, 0)

        self.add_clue_button = QPushButton("Clue")
        self.add_clue_button.setToolTip(
            "Add evidence or clues found during search:\n"
            "Footprints, clothing, equipment, witness sightings, etc."
        )
        self.add_clue_button.clicked.connect(self._on_add_clue)
        markers_grid.addWidget(self.add_clue_button, 0, 1)

        self.add_hazard_button = QPushButton("Hazard")
        self.add_hazard_button.setToolTip(
            "Mark safety hazards on the map:\n"
            "Cliffs, water hazards, bogs, dense vegetation, etc."
        )
        self.add_hazard_button.clicked.connect(self._on_add_hazard)
        markers_grid.addWidget(self.add_hazard_button, 1, 0)

        self.add_casualty_button = QPushButton("Casualty")
        self.add_casualty_button.setToolTip(
            "Add found injured or deceased person:\n"
            "CRITICAL: Use for actual casualties requiring medical response,\n"
            "evacuation, and legal documentation. NOT for evidence/clues."
        )
        self.add_casualty_button.clicked.connect(self._on_add_casualty)
        markers_grid.addWidget(self.add_casualty_button, 1, 1)

        markers_layout.addLayout(markers_grid)
        markers_group.setLayout(markers_layout)
        layout.addWidget(markers_group)

        # ========================================
        # Drawing Tools Section
        # ========================================
        drawing_group = QGroupBox("Drawing Tools")
        drawing_layout = QVBoxLayout()

        # Active tool indicator
        active_tool_layout = QHBoxLayout()
        active_tool_layout.addWidget(QLabel("Active:"))
        self.active_tool_label = QLabel("<i>None</i>")
        self.active_tool_label.setStyleSheet("QLabel { color: #0066cc; font-weight: bold; }")
        active_tool_layout.addWidget(self.active_tool_label)
        active_tool_layout.addStretch()
        drawing_layout.addLayout(active_tool_layout)

        # Drawing tools grid (2 columns) - placeholders for now
        drawing_grid = QGridLayout()

        # Note: These will be implemented in Week 1 Days 2-5
        self.line_tool_button = QPushButton("Line")
        self.line_tool_button.setToolTip("Draw lines for routes, boundaries, or paths.\nClick to add points, right-click to finish.")
        self.line_tool_button.clicked.connect(self._on_line_tool)
        drawing_grid.addWidget(self.line_tool_button, 0, 0)

        self.search_area_button = QPushButton("Search Area")
        self.search_area_button.setToolTip("Draw polygon search areas with status tracking.\nClick to add vertices, right-click to finish (min 3 vertices).")
        self.search_area_button.setEnabled(False)  # DISABLED - Qt event loop freeze issue (see docs/COMPREHENSIVE_POLYGON_FREEZE_ANALYSIS.md)
        self.search_area_button.clicked.connect(self._on_polygon_tool)
        drawing_grid.addWidget(self.search_area_button, 0, 1)

        self.range_rings_button = QPushButton("Range Rings")
        self.range_rings_button.setToolTip("Create distance circles (LPB-based or custom)")
        self.range_rings_button.clicked.connect(self._on_range_rings_tool)
        drawing_grid.addWidget(self.range_rings_button, 1, 0)

        self.bearing_line_button = QPushButton("Bearing Line")
        self.bearing_line_button.setToolTip("Draw azimuth/bearing lines for direction finding")
        self.bearing_line_button.clicked.connect(self._on_bearing_tool)
        drawing_grid.addWidget(self.bearing_line_button, 1, 1)

        self.sector_button = QPushButton("Search Sector")
        self.sector_button.setToolTip("Draw pie-slice sectors for search areas")
        self.sector_button.setEnabled(False)  # Disabled until implemented
        drawing_grid.addWidget(self.sector_button, 2, 0)

        self.text_label_button = QPushButton("Text Label")
        self.text_label_button.setToolTip("Add text annotations to the map")
        self.text_label_button.setEnabled(False)  # Disabled until implemented
        drawing_grid.addWidget(self.text_label_button, 2, 1)

        self.gpx_import_button = QPushButton("Import GPX")
        self.gpx_import_button.setToolTip("Import GPS tracks from GPX files")
        self.gpx_import_button.clicked.connect(self._on_gpx_import)
        drawing_grid.addWidget(self.gpx_import_button, 3, 0, 1, 2)  # Full width

        drawing_layout.addLayout(drawing_grid)
        drawing_group.setLayout(drawing_layout)
        layout.addWidget(drawing_group)

        # ========================================
        # Utilities Section
        # ========================================
        utilities_group = QGroupBox("Utilities")
        utilities_layout = QVBoxLayout()

        utilities_grid = QGridLayout()

        self.coord_converter_button = QPushButton("Coordinate Converter")
        self.coord_converter_button.clicked.connect(self._on_coordinate_converter)
        utilities_grid.addWidget(self.coord_converter_button, 0, 0)

        self.measure_button = QPushButton("Measure Distance")
        self.measure_button.clicked.connect(self._on_measure_distance)
        utilities_grid.addWidget(self.measure_button, 0, 1)

        utilities_layout.addLayout(utilities_grid)

        measurements_layout = QHBoxLayout()
        self.measurements_status_label = QLabel("Measurements pinned: 0")
        self.measurements_status_label.setStyleSheet("QLabel { color: #666; }")
        measurements_layout.addWidget(self.measurements_status_label)

        self.clear_measurements_button = QPushButton("Clear Measurements")
        self.clear_measurements_button.setEnabled(False)
        self.clear_measurements_button.clicked.connect(self._on_clear_measurements_clicked)
        measurements_layout.addWidget(self.clear_measurements_button)
        utilities_layout.addLayout(measurements_layout)

        utilities_group.setLayout(utilities_layout)
        layout.addWidget(utilities_group)

        # Spacer
        layout.addStretch()

        main_widget.setLayout(layout)

        # Wrap in scroll area so content is always accessible
        scroll_area = QScrollArea()
        scroll_area.setWidget(main_widget)
        scroll_area.setWidgetResizable(True)  # Important: makes content resize with panel

        self.setWidget(scroll_area)
        
    def _on_start_mission(self):
        """Handle start mission button click."""
        if not self._mission_controller:
            QMessageBox.warning(
                self,
                "Mission Control",
                "Mission controller unavailable. Restart plugin."
            )
            return

        # Guard against double-start even if UI is out of sync
        try:
            if self._mission_controller.state not in (MissionState.IDLE, MissionState.FINISHED):
                QMessageBox.information(
                    self,
                    "Mission Control",
                    "A mission is already active. Resume, pause/resume, or finish before starting a new mission."
                )
                return
        except Exception:
            # If state check fails, continue to normal start flow
            pass

        mission_name = self.mission_name_input.text().strip()
        if not mission_name:
            mission_name = f"Mission {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            self.mission_name_input.setText(mission_name)

        try:
            self._mission_controller.start_mission(mission_name)
        except ValueError as exc:
            print(f"[SARPanel] Mission start validation failed: {exc}")
            QMessageBox.warning(self, "Mission Control", str(exc))
        except RuntimeError as exc:
            print(f"[SARPanel] Mission start error: {exc}")
            QMessageBox.information(self, "Mission Control", str(exc))
        except Exception as exc:
            print(f"[SARPanel] CRITICAL: Unexpected mission start error: {exc}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Mission Control", f"Unexpected error: {exc}")
        
    def _on_pause_mission(self):
        """Handle pause/resume button click."""
        if not self._mission_controller:
            return

        try:
            if self._mission_state == MissionState.PAUSED:
                self._mission_controller.resume_mission()
            else:
                self._mission_controller.pause_mission()
        except Exception as exc:
            print(f"[SARPanel] CRITICAL: Mission pause/resume error: {exc}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Mission Control", f"Error pausing/resuming mission: {exc}")
        
    def _on_finish_mission(self):
        """Handle finish mission button click (End Mission)."""
        if not self._mission_controller:
            return

        confirm = QMessageBox.question(
            self,
            "End Mission",
            "Are you sure you want to end this mission?\n\n"
            "This will:\n"
            "• Stop mission timers\n"
            "• Keep all mission data editable in the current project\n"
            "• Reset UI for the next mission\n\n"
            "Mission data remains saved in the GeoPackage.\n"
            "Use 'Finalize Mission' later to archive and lock the data.",
            MessageBoxYes | MessageBoxNo,
            MessageBoxNo
        )

        if confirm != MessageBoxYes:
            return

        try:
            self._mission_controller.finish_mission()
        except Exception as exc:
            print(f"[SARPanel] CRITICAL: Mission finish error: {exc}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Mission Control", f"Error finishing mission: {exc}")

    def _on_finalize_mission(self):
        """Handle finalize mission button click."""
        if self._is_finalized:
            self.unlock_mission_requested.emit()
            return

        confirm = QMessageBox.question(
            self,
            "Finalize Mission",
            "This will create an archive of the mission and mark it as read-only.\n\n"
            "The archive will include:\n"
            "• QGIS project file (.qgz)\n"
            "• Mission GeoPackage (.gpkg)\n"
            "• All attachments\n\n"
            "After finalization, the mission data cannot be edited without\n"
            "admin override.\n\n"
            "Continue with finalization?",
            MessageBoxYes | MessageBoxNo,
            MessageBoxNo
        )

        if confirm != MessageBoxYes:
            return

        # Emit signal to sartracker.py to handle archiving
        self.finalize_mission_requested.emit()

    def _on_controller_state_changed(self, state: MissionState, context: dict):
        """React to mission controller state updates."""
        self._mission_state = state

        mission_name = context.get('mission_name')
        if mission_name:
            self.mission_name_input.setText(mission_name)

        if state == MissionState.ACTIVE:
            status = "Status: <b style='color: #22aa5f;'>Active</b>"
        elif state == MissionState.PAUSED:
            status = "Status: <b style='color: orange;'>Paused</b>"
        elif state == MissionState.FINISHED:
            status = "Status: <b style='color: #c0392b;'>Finished</b>"
        else:
            status = "Status: <b>No active mission</b>"

        self.mission_status_label.setText(status)
        self.mission_name_input.setEnabled(state in (MissionState.IDLE, MissionState.FINISHED))
        self._refresh_mission_controls()

    def update_mission_timers(self, elapsed_seconds: float, active_seconds: float):
        """Update elapsed/active timer labels."""
        self.elapsed_time_value.setText(self._format_seconds(elapsed_seconds))
        self.active_time_value.setText(self._format_seconds(active_seconds))

    def _refresh_mission_controls(self):
        """Sync button enablement and styles to mission state."""
        if self._mission_state == MissionState.ACTIVE:
            self.start_button.setEnabled(False)
            self.pause_button.setEnabled(True)
            self.finish_button.setEnabled(True)
            self.pause_button.setText("Pause")
            self.pause_button.setIcon(self._standard_icon("SP_MediaPause", "SP_DialogApplyButton"))
            self.pause_flash_timer.stop()
            self._pause_flash = False
            self._set_button_state(self.pause_button, "flashOn", False)
            self._set_button_state(self.start_button, "state", "active")
            self._set_button_state(self.pause_button, "state", "pause")
            self._set_button_state(self.finish_button, "state", "ready")
        elif self._mission_state == MissionState.PAUSED:
            self.start_button.setEnabled(False)
            self.pause_button.setEnabled(True)
            self.finish_button.setEnabled(True)
            self.pause_button.setText("Resume")
            self.pause_button.setIcon(self._standard_icon("SP_MediaPlay", "SP_ArrowForward"))
            self.pause_flash_timer.start()
            self._set_button_state(self.start_button, "state", "active")
            self._set_button_state(self.pause_button, "state", "resume")
            self._set_button_state(self.pause_button, "flashOn", True)
            self._set_button_state(self.finish_button, "state", "ready")
        else:
            self.start_button.setEnabled(True)
            self.pause_button.setEnabled(False)
            self.finish_button.setEnabled(False)
            self.pause_button.setText("Pause")
            self.pause_button.setIcon(self._standard_icon("SP_MediaPause", "SP_DialogApplyButton"))
            self.pause_flash_timer.stop()
            self._pause_flash = False
            self._set_button_state(self.pause_button, "flashOn", False)
            self._set_button_state(self.start_button, "state", "idle")
            self._set_button_state(self.pause_button, "state", "pause")
            self._set_button_state(self.finish_button, "state", "idle")

    def _set_button_state(self, button: QToolButton, prop_name: str, value):
        """Set dynamic stylesheet property and refresh widget."""
        if not hasattr(button, 'setProperty'):
            return
        button.setProperty(prop_name, value)
        button.style().unpolish(button)
        button.style().polish(button)
        button.update()

    def _toggle_pause_flash(self):
        """Flash pause button while mission paused."""
        if not self._is_active:
            return
        self._pause_flash = not self._pause_flash
        self._set_button_state(self.pause_button, "flashOn", self._pause_flash)

    def _format_seconds(self, seconds: float) -> str:
        import math
        # Guard against NaN/Inf values which would crash int()
        if seconds is None or not math.isfinite(seconds):
            seconds = 0.0
        total = max(0, int(seconds))
        hours, remainder = divmod(total, 3600)
        minutes, secs = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    def _apply_mission_button_styles(self):
        """Apply consistent styling for mission control buttons."""
        start_style = """
        QToolButton {
            border-radius: 6px;
            padding: 8px 18px;
            font-weight: 600;
        }
        QToolButton[state="idle"] {
            background-color: #1f8b4d;
            color: #ffffff;
        }
        QToolButton[state="active"] {
            background-color: #25a65c;
            color: #ffffff;
        }
        QToolButton:disabled {
            background-color: #94a3b8;
            color: #f2f2f2;
        }
        """
        pause_style = """
        QToolButton {
            border-radius: 6px;
            padding: 8px 18px;
            font-weight: 600;
        }
        QToolButton[state="pause"] {
            background-color: #ffa94d;
            color: #1f1f1f;
        }
        QToolButton[state="resume"] {
            background-color: #ff8c00;
            color: #ffffff;
        }
        QToolButton[flashOn="true"] {
            border: 2px solid #ffe0b2;
        }
        QToolButton:disabled {
            background-color: #94a3b8;
            color: #f2f2f2;
        }
        """
        finish_style = """
        QToolButton {
            border-radius: 6px;
            padding: 8px 18px;
            font-weight: 600;
        }
        QToolButton[state="ready"] {
            background-color: #c0392b;
            color: #ffffff;
        }
        QToolButton:disabled {
            background-color: #94a3b8;
            color: #f2f2f2;
        }
        """

        self.start_button.setStyleSheet(start_style)
        self.pause_button.setStyleSheet(pause_style)
        self.finish_button.setStyleSheet(finish_style)

    # NOTE: configure_marker_log, refresh_marker_log removed
    # Layer Console and Marker Log are now in the Mission Logs window
    # Access via menu: SAR Tracker > Mission Logs...

    def _apply_focus_mode_style(self):
        """Update focus mode button styling."""
        if not hasattr(self, 'focus_mode_button') or not self.focus_mode_button:
            return
        if self.focus_mode_active:
            self.focus_mode_button.setStyleSheet(
                "QToolButton {"
                "  background-color: #4066d6;"
                "  color: #ffffff;"
                "  padding: 6px 14px;"
                "  border-radius: 4px;"
                "  border: 1px solid #2e4fb4;"
                "  font-weight: 600;"
                "}"
            )
        else:
            self.focus_mode_button.setStyleSheet(
                "QToolButton {"
                "  padding: 6px 14px;"
                "  border-radius: 4px;"
                "  border: 1px solid #5b6da5;"
                "  color: #1f2a44;"
                "  background-color: #f5f7ff;"
                "  font-weight: 600;"
                "}"
                "\n"
                "QToolButton:hover {"
                "  background-color: #e0e6ff;"
                "}"
            )
    
    def _initialize_auto_settings(self):
        """Load persisted auto-refresh/save defaults on startup."""
        try:
            auto_refresh_enabled = ConfigStore.get_auto_refresh_enabled()
            auto_refresh_interval = ConfigStore.get_auto_refresh_interval()
            auto_save_enabled = ConfigStore.get_auto_save_enabled()
            auto_save_interval = ConfigStore.get_auto_save_interval()
        except Exception as e:
            print(f"[SARPANEL] Warning: Failed to load auto settings from QSettings: {e}")
            auto_refresh_enabled = SETTINGS_KEYS.AUTO_REFRESH_ENABLED_DEFAULT
            auto_refresh_interval = SETTINGS_KEYS.AUTO_REFRESH_INTERVAL_DEFAULT
            auto_save_enabled = SETTINGS_KEYS.AUTO_SAVE_ENABLED_DEFAULT
            auto_save_interval = SETTINGS_KEYS.AUTO_SAVE_INTERVAL_DEFAULT

        self.set_auto_refresh_config(auto_refresh_enabled, auto_refresh_interval)
        self.set_autosave_config(auto_save_enabled, auto_save_interval)

    def set_auto_refresh_config(self, enabled: bool, interval_seconds: int):
        """Apply auto-refresh configuration coming from Settings panel."""
        interval = interval_seconds or SETTINGS_KEYS.AUTO_REFRESH_INTERVAL_DEFAULT
        interval = int(max(SETTINGS_KEYS.AUTO_REFRESH_INTERVAL_MIN,
                           min(interval, SETTINGS_KEYS.AUTO_REFRESH_INTERVAL_MAX)))
        self.auto_refresh_enabled = bool(enabled)
        self.auto_refresh_interval_seconds = interval
        self._update_auto_refresh_status_label()
        self._apply_auto_refresh_timer()

    def _apply_auto_refresh_timer(self):
        """Start/stop the auto-refresh timer based on current config."""
        if not self._is_active:
            self.refresh_timer.stop()
            return
        if self.auto_refresh_enabled:
            self.refresh_timer.start(self.auto_refresh_interval_seconds * 1000)
        else:
            self.refresh_timer.stop()

    def _update_auto_refresh_status_label(self):
        """Update the read-only auto-refresh status indicator."""
        if self.auto_refresh_enabled:
            text = f"Auto Refresh ON ({self.auto_refresh_interval_seconds}s)"
            color = "#1f8b4d"
        else:
            text = "Auto Refresh OFF"
            color = "#555"
        self._set_feature_badge(self.auto_refresh_status_label, text, self.auto_refresh_enabled, color)

    def set_autosave_config(self, enabled: bool, interval_minutes: int):
        """Apply auto-save configuration coming from Settings panel."""
        interval = interval_minutes or SETTINGS_KEYS.AUTO_SAVE_INTERVAL_DEFAULT
        interval = int(max(SETTINGS_KEYS.AUTO_SAVE_INTERVAL_MIN,
                           min(interval, SETTINGS_KEYS.AUTO_SAVE_INTERVAL_MAX)))
        self.autosave_enabled = bool(enabled)
        self.autosave_interval_minutes = interval
        self._update_autosave_status_label()
        self._apply_autosave_timer()

    def _apply_autosave_timer(self):
        """Start/stop the auto-save timer based on current config."""
        if not self._is_active:
            self.autosave_timer.stop()
            return
        if self.autosave_enabled:
            self.autosave_timer.start(self.autosave_interval_minutes * 60 * 1000)
        else:
            self.autosave_timer.stop()

    def _update_autosave_status_label(self):
        """Update the read-only auto-save status indicator."""
        status = "ON" if self.autosave_enabled else "OFF"
        interval_text = f"(every {self.autosave_interval_minutes} min)" if self.autosave_enabled else ""
        if self.last_autosave_time:
            time_str = self.last_autosave_time.strftime("%H:%M:%S")
            if self._last_autosave_success is True:
                last_text = f"{time_str} ✓"
            elif self._last_autosave_success is False:
                last_text = f"{time_str} ✗ Failed"
            else:
                last_text = time_str
        else:
            last_text = "Never"

        color = "#666"
        if self._last_autosave_success is True:
            color = "#1f8b4d"
        elif self._last_autosave_success is False:
            color = "#d00"
        elif self.autosave_enabled:
            color = "#1f8b4d"

        text = f"Auto Save {status}{(' ' + interval_text) if interval_text else ''} | Last: {last_text}"
        self._set_feature_badge(self.autosave_status_label, text, self.autosave_enabled, color)

    # NOTE: Layer Console handlers removed - moved to Mission Logs window
    # Access via menu: SAR Tracker > Mission Logs...

    def _message_bar(self):
        if self._layers_controller and hasattr(self._layers_controller, "iface") and self._layers_controller.iface:
            try:
                return self._layers_controller.iface.messageBar()
            except Exception:
                return None
        return None

    def _notify(self, fn: Callable, title: str, message: str):
        """Push message if message bar available, else log to stdout."""
        bar = self._message_bar()
        if bar:
            fn(bar, title, message)
        else:
            print(f"[{title}] {message}")
    
    def _on_auto_refresh(self):
        """Handle auto-refresh timer."""
        if not self._is_active:
            return
        # Only refresh if mission is not paused (or controller unavailable)
        if not self._mission_controller:
            self.refresh_requested.emit()
            return

        if self._mission_state != MissionState.PAUSED:
            self.refresh_requested.emit()
    
    def _on_manual_refresh(self):
        """Handle manual refresh button."""
        self.refresh_requested.emit()
    
    def _on_load_csv(self):
        """Handle load CSV button."""
        # Show dialog with option to select file or folder
        file_path = QFileDialog.getExistingDirectory(
            self,
            "Select Folder with CSV Files (or Cancel and select single file)",
            ""
        )

        # If user cancelled folder selection, try file selection
        if not file_path:
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                "Select Traccar CSV Export",
                "",
                "CSV Files (*.csv);;All Files (*)"
            )

        if file_path:
            self.csv_load_requested.emit(file_path)
    
    def update_devices(self, devices: List[Dict]):
        """
        Update device list.
        
        Args:
            devices: List of device dicts from provider
        """
        self.devices_list.clear()
        try:
            if devices is None:
                return
            if not isinstance(devices, list):
                raise ValueError("Device payload must be a list")

            invalid = 0
            for device in devices:
                if not isinstance(device, dict):
                    invalid += 1
                    continue

                device_id = device.get('device_id') or device.get('id') or 'Unknown'
                # FR-5: Show device name with device_id fallback
                device_name = device.get('name') or device_id
                status = device.get('status', 'unknown')
                last_update = device.get('last_update', 'Never')

                # Format display text - show name prominently
                text = f"{device_name}"
                if status == 'online':
                    text = f"🟢 {text}"
                elif status == 'offline':
                    text = f"🔴 {text}"
                else:
                    text = f"⚪ {text}"
                
                text += f"\n  Last: {last_update}"
                
                item = QListWidgetItem(text)
                self.devices_list.addItem(item)

            if invalid and not getattr(self, "_devices_warning_logged", False):
                self._notify(warning, "Devices", f"Ignored {invalid} malformed device entries")
                self._devices_warning_logged = True
        except Exception as exc:
            self.devices_list.clear()
            if not getattr(self, "_devices_warning_logged", False):
                self._notify(warning, "Devices", f"Could not display devices: {exc}")
                self._devices_warning_logged = True
    
    def set_data_source(self, source_info: str):
        """
        Update data source label.

        Args:
            source_info: Description of current data source
        """
        self.data_source_label.setText(f"Source: {source_info or 'None'}")

    def set_loading_state(self, loading: bool):
        """
        Show/hide loading indicator during refresh.

        Args:
            loading: True to show loading state, False to hide

        Qt5/Qt6 Compatible: Uses standard Qt widget methods.
        """
        if loading:
            self.refresh_button.setEnabled(False)
            self.refresh_button.setText("Refreshing...")
            self.refresh_button.setStyleSheet("QPushButton { background-color: #FFA500; color: white; }")
        else:
            self.refresh_button.setEnabled(True)
            self.refresh_button.setText("Refresh Now")
            self.refresh_button.setStyleSheet("")

    def _on_add_poi(self):
        """Handle Add POI button click."""
        self.add_poi_requested.emit()

    def _on_add_clue(self):
        """Handle Add Clue button click."""
        self.add_clue_requested.emit()

    def _on_add_casualty(self):
        """Handle Add Casualty button click."""
        self.add_casualty_requested.emit()

    def _on_add_hazard(self):
        """Handle Add Hazard button click."""
        self.add_hazard_requested.emit()

    def _on_coordinate_converter(self):
        """Handle Coordinate Converter button click."""
        self.coordinate_converter_requested.emit()

    def _on_measure_distance(self):
        """Handle Measure Distance button click."""
        self.measure_distance_requested.emit()

    def _on_clear_measurements_clicked(self):
        """Handle Clear Measurements button click."""
        self.clear_measurements_requested.emit()

    def _on_line_tool(self):
        """Handle Line Tool button click."""
        self.line_tool_requested.emit()

    def _on_polygon_tool(self):
        """Handle Polygon Tool (Search Area) button click."""
        self.polygon_tool_requested.emit()

    def _on_range_rings_tool(self):
        """Handle Range Rings Tool button click."""
        self.range_rings_tool_requested.emit()

    def _on_bearing_tool(self):
        """Handle Bearing Tool button click."""
        self.bearing_tool_requested.emit()

    def _on_gpx_import(self):
        """Handle GPX Import button click - show menu with import options."""
        from qgis.PyQt.QtWidgets import QMenu
        from qgis.PyQt.QtCore import QPoint

        menu = QMenu(self)

        # Import GPX File action
        import_file_action = menu.addAction("Import GPX File...")
        import_file_action.triggered.connect(self._on_gpx_import_file)

        # Import GPX Folder action
        import_folder_action = menu.addAction("Import GPX Folder...")
        import_folder_action.triggered.connect(self._on_gpx_import_folder)

        # Watch GPX Folder action
        watch_folder_action = menu.addAction("Watch Folder for New GPX...")
        watch_folder_action.triggered.connect(self._on_gpx_watch_folder)

        # Show menu at button position
        button_pos = self.gpx_import_button.mapToGlobal(QPoint(0, self.gpx_import_button.height()))
        exec_fn = getattr(menu, "exec", None) or getattr(menu, "exec_", None)
        if exec_fn:
            exec_fn(button_pos)

    def _on_gpx_import_file(self):
        """Handle Import GPX File menu action."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select GPX File",
            "",
            "GPX Files (*.gpx);;All Files (*)"
        )

        if file_path:
            self.gpx_import_file_requested.emit(file_path)

    def _on_gpx_import_folder(self):
        """Handle Import GPX Folder menu action."""
        folder_path = QFileDialog.getExistingDirectory(
            self,
            "Select Folder Containing GPX Files"
        )

        if folder_path:
            self.gpx_import_folder_requested.emit(folder_path)

    def _on_gpx_watch_folder(self):
        """Handle Watch GPX Folder menu action."""
        folder_path = QFileDialog.getExistingDirectory(
            self,
            "Select Folder to Watch for New GPX Files"
        )

        if folder_path:
            self.gpx_watch_folder_requested.emit(folder_path)

    def set_active_tool(self, tool_name):
        """
        Update active tool indicator.

        Args:
            tool_name: Name of active tool (or "None")
        """
        if tool_name == "None":
            self.active_tool_label.setText("<i>None</i>")
        else:
            self.active_tool_label.setText(f"<b>{tool_name}</b>")

    def update_measurements_indicator(self, count: int):
        """
        Update pinned measurement counter and clear button state.

        Args:
            count: Number of persisted measurement overlays
        """
        label = "Measurement pinned" if count == 1 else "Measurements pinned"
        self.measurements_status_label.setText(f"{label}: {count}")
        self.clear_measurements_button.setEnabled(count > 0)

    def update_mission_storage(self, primary_path: Optional[str], backup_path: Optional[str] = None, active: bool = True, coordinators: str = ""):
        """
        Update the mission storage status label.

        Args:
            primary_path: Path to the primary mission GeoPackage
            backup_path: Path to the backup mirror directory (if any)
            active: Whether the mission storage is currently active
            coordinators: Optional coordinator roster string
        """
        if not primary_path:
            text = "Storage: <i>Not initialized</i>"
        else:
            state = "active" if active else "idle"
            text = f"Storage ({state}): {primary_path}"
            if coordinators:
                text += f" | Coordinators: {coordinators}"
            if backup_path:
                text += f" | Backup: {backup_path}"
        self.mission_storage_label.setText(text)

    def set_finalize_button_visible(self, visible: bool, is_finalized: bool = False):
        """
        Show or hide the finalize mission button.

        Args:
            visible: Whether to show the button
            is_finalized: If True, show "Already Finalized" disabled state
        """
        if not hasattr(self, 'finalize_button'):
            return

        if is_finalized:
            self._is_finalized = True
            self.finalize_button.setText("Unlock Mission (Admin)")
            self.finalize_button.setToolTip("Mission is finalized. Admin unlock required to edit.")
            self.finalize_button.setEnabled(True)
            self.finalize_button.setVisible(True)
        else:
            self._is_finalized = False
            self.finalize_button.setText("Finalize Mission (Archive & Lock)")
            self.finalize_button.setToolTip(
                "Archive mission data and mark it read-only. Admin unlock required to edit afterwards."
            )
            self.finalize_button.setEnabled(True)
            self.finalize_button.setVisible(visible)

    def disable_drawing_tools(self, reason: str = "Drawing tools unavailable"):
        """
        Disable all drawing tool buttons when tools fail to load.

        This prevents users from clicking buttons that would cause crashes
        when the tool registry or individual tools failed to initialize.

        Args:
            reason: User-friendly explanation for why tools are disabled

        Qt5/Qt6 Compatible: Uses standard QPushButton methods.

        Issue #2 Fix: Prevents crashes when tool registry fails to initialize.
        """
        # Disable all drawing tool buttons
        self.line_tool_button.setEnabled(False)
        self.search_area_button.setEnabled(False)
        self.range_rings_button.setEnabled(False)
        self.bearing_line_button.setEnabled(False)

        # Update tool tips to explain why buttons are disabled
        tooltip = f"⚠ {reason}\n\nRun Diagnostics (SAR Tracker menu) for details."
        self.line_tool_button.setToolTip(tooltip)
        self.search_area_button.setToolTip(tooltip)
        self.range_rings_button.setToolTip(tooltip)
        self.bearing_line_button.setToolTip(tooltip)

        print(f"[SARTRACKER] Drawing tools disabled: {reason}")

    def _on_autosave(self):
        """Handle auto-save timer - request project save."""
        if not self._is_active:
            return
        if self.autosave_enabled:
            self.autosave_requested.emit()

    def _on_manual_save(self):
        """Handle manual save button - request immediate project save."""
        self.autosave_requested.emit()

    def update_autosave_status(self, success: bool):
        """
        Update auto-save status label.

        Args:
            success: Whether the save was successful
        """
        self.last_autosave_time = datetime.now()
        self._last_autosave_success = success
        self._update_autosave_status_label()


    # ========================================
    # Phase N1: Provider configuration methods removed
    # Provider configuration is now handled in Settings Panel
    # (Plugins → SAR Tracker → Settings...)
    # ========================================

    def update_provider_status(self, status_dict: Dict[str, Any]):
        """
        Update provider status strip from controller.

            Args:
                status_dict: Status from ProviderController.status_snapshot() with keys:
                    - provider: str or None
                    - state: str ('ok', 'error', 'testing', 'connecting')
                    - message: str
                    - poll_interval: int or None
                    - poll_active: bool
                    - devices_count: int
                    - last_refresh: str or None
                    - data_state: str ('live', 'cached', 'outage', 'unknown')
                    - cache_age_seconds: float or None

        Qt5/Qt6 Compatible: Uses QLabel.setText().
        """
        try:
            if not isinstance(status_dict, dict):
                raise ValueError("Status payload must be a dict")

            provider = status_dict.get('provider', 'None')
            state = status_dict.get('state', 'unknown')
            message = status_dict.get('message', '')
            devices_count = status_dict.get('devices_count', 0)
            last_refresh = status_dict.get('last_refresh', 'Never')
            poll_active = status_dict.get('poll_active', False)
            poll_interval = status_dict.get('poll_interval')
            last_error = status_dict.get('last_error')
            data_state = status_dict.get('data_state', 'unknown')
            cache_age_seconds = status_dict.get('cache_age_seconds')

            # Format last refresh time
            if last_refresh and last_refresh != 'Never':
                try:
                    # Extract time component from ISO timestamp
                    last_refresh = last_refresh.split('T')[1][:8] if 'T' in last_refresh else last_refresh
                except Exception:
                    pass
            cache_age_display = None
            if cache_age_seconds is not None:
                try:
                    age_minutes = cache_age_seconds / 60
                    if age_minutes >= 60:
                        cache_age_display = f"{age_minutes / 60:.1f}h"
                    else:
                        cache_age_display = f"{age_minutes:.0f}m"
                except Exception:
                    cache_age_display = None

            # Format status text
            status_parts = [f"Provider: {provider}"]
            status_parts.append(f"Devices: {devices_count}")
            if last_refresh != 'Never':
                status_parts.append(f"Last Refresh: {last_refresh}")
            if poll_active:
                if poll_interval:
                    status_parts.append(f"🔄 Polling ({poll_interval}s)")
                else:
                    status_parts.append("🔄 Polling")

            # Add state indicator
            if state == 'testing':
                status_parts.append("⏳ Testing...")
            elif state == 'connecting':
                status_parts.append("⏳ Connecting...")
            elif state == 'refreshing':
                status_parts.append("⏳ Refreshing...")
            elif data_state == 'outage':
                status_parts.append("✗ Offline")
            elif data_state == 'cached':
                if cache_age_display:
                    status_parts.append(f"⚠ Cached ({cache_age_display})")
                else:
                    status_parts.append("⚠ Cached")
            elif state == 'error':
                status_parts.append("✗ Error")
            elif state == 'ok':
                status_parts.append("✓ Connected")

            if last_error and state == 'error':
                status_parts.append(f"Last Error: {last_error}")
            elif message:
                status_parts.append(message)

            status_text = " | ".join(status_parts)
            self.provider_status_label.setText(status_text)

            # Update label background color based on state
            if state == 'ok':
                bg_color = "#d4edda"  # Light green
            elif state == 'error':
                bg_color = "#f8d7da"  # Light red
            elif state in ('testing', 'connecting', 'refreshing'):
                bg_color = "#fff3cd"  # Light yellow
            else:
                bg_color = "#f0f0f0"  # Light gray
            if data_state == 'outage':
                bg_color = "#f8d7da"
            elif data_state == 'cached':
                bg_color = "#fff3cd"

            self.provider_status_label.setStyleSheet(
                f"QLabel {{ "
                f"  padding: 4px; "
                f"  background-color: {bg_color}; "
                f"  border: 1px solid #ccc; "
                f"  border-radius: 3px; "
                f"  font-size: 10px; "
                f"}}"
            )
        except Exception as exc:
            self.provider_status_label.setText("Provider: unavailable | State: unknown")
            self.provider_status_label.setStyleSheet(
                "QLabel { padding: 4px; background-color: #f0f0f0; border: 1px solid #ccc; border-radius: 3px; font-size: 10px; }"
            )
            if not getattr(self, "_provider_warning_logged", False):
                self._notify(warning, "Provider Status", f"Could not render provider status: {exc}")
                self._provider_warning_logged = True

    def _toggle_focus_mode(self):
        """
        Toggle Focus Mode - hide/show other QGIS panels.

        Qt5/Qt6 Compatible: Uses standard Qt widget visibility methods.
        """
        try:
            from qgis.utils import iface

            if not self.focus_mode_active:
                # Enter Focus Mode - hide other panels
                self.hidden_panels = []

                # Get main window and find all dock widgets
                main_window = iface.mainWindow()
                all_docks = main_window.findChildren(QDockWidget)

                # Hide all dock widgets except SAR panel
                for dock in all_docks:
                    if dock != self and dock.isVisible():
                        # Store reference to restore later
                        self.hidden_panels.append(dock)
                        dock.setVisible(False)

                # Update button
                self.focus_mode_button.setText("Exit Focus Mode")
                self.focus_mode_active = True
                self._apply_focus_mode_style()

                # Show message
                info(
                    iface.messageBar(),
                    "Focus Mode",
                    f"Focus Mode enabled - {len(self.hidden_panels)} panels hidden. Click 'Exit Focus Mode' to restore.",
                    duration=3
                )

            else:
                # Exit Focus Mode - restore panels
                # CRITICAL FIX (BUG-025): Guard against deleted panels
                # User may have closed a panel while it was hidden, causing crash
                restored = 0
                for panel in self.hidden_panels:
                    try:
                        # Check if Qt object is still valid before accessing
                        if panel and not sip.isdeleted(panel):
                            panel.setVisible(True)
                            restored += 1
                    except (RuntimeError, AttributeError):
                        # Panel was destroyed - skip it
                        pass

                self.hidden_panels = []

                # Update button
                self.focus_mode_button.setText("Enter Focus Mode")
                self.focus_mode_active = False
                self._apply_focus_mode_style()

                # Show message
                info(
                    iface.messageBar(),
                    "Focus Mode",
                    f"Focus Mode disabled - {restored} panels restored.",
                    duration=2
                )

        except Exception as e:
            # Fail gracefully - focus mode is optional
            print(f"Focus mode toggle failed: {e}")
            from qgis.utils import iface
            warning(
                iface.messageBar(),
                "Focus Mode",
                f"Error in focus mode: {e}",
                duration=3
            )

    def _restore_hidden_panels(self):
        """
        Restore panels hidden by Focus Mode.

        This is called during cleanup to ensure QGIS returns to its prior
        state even if the plugin is unloaded while Focus Mode is active.

        Handles edge cases:
        - Panels already deleted/destroyed (RuntimeError caught)
        - Panels manually re-shown by user (setVisible is no-op)
        - Multiple calls (idempotent via focus_mode_active guard)

        Qt5/Qt6 Compatible: Uses standard QDockWidget visibility methods.

        ISSUE #3 FIX: Ensures Focus Mode exits cleanly during plugin unload.
        """
        if not self.focus_mode_active:
            # Not in focus mode, nothing to restore
            return

        try:
            restored_count = 0
            error_count = 0

            # Iterate over copy of list to avoid issues if Qt deletes objects during iteration
            for panel in list(self.hidden_panels):
                try:
                    # Attempt to restore panel visibility
                    # Note: This may fail if panel was destroyed by user or during shutdown
                    if not panel.isVisible():  # Optional optimization: only restore if still hidden
                        panel.setVisible(True)
                        restored_count += 1
                except RuntimeError as e:
                    # Panel's C++ object was deleted - this is expected in some scenarios
                    # (user closed the panel, or QGIS is shutting down)
                    error_count += 1
                    print(f"[SARTRACKER] Panel restoration skipped - C++ object deleted: {e}")
                except Exception as e:
                    # Unexpected error - log but continue restoring other panels
                    error_count += 1
                    print(f"[SARTRACKER] Warning: Error restoring panel: {e}")

            # Clear state
            self.hidden_panels = []
            self.focus_mode_active = False

            # Update button UI if possible (may fail during shutdown)
            try:
                self.focus_mode_button.setText("Enter Focus Mode")
                self._apply_focus_mode_style()
            except (RuntimeError, AttributeError):
                # Button already destroyed or doesn't exist - ignore
                pass

            # Log result
            if restored_count > 0:
                print(f"[SARTRACKER] Focus Mode cleanup: {restored_count} panels restored, {error_count} errors")

        except Exception as e:
            # Catch-all: Don't let panel restoration crash the cleanup sequence
            print(f"[SARTRACKER] Error in _restore_hidden_panels: {e}")
            # Ensure state is cleared even if restoration failed
            self.hidden_panels = []
            self.focus_mode_active = False

    def cleanup(self):
        """
        Explicit cleanup method for proper resource release.

        Stops all timers, restores hidden panels (if Focus Mode active),
        and disconnects signals before widget destruction.
        This method should be called from the plugin's unload() sequence.

        Called by:
            - sartracker.py:unload() during plugin unload
            - closeEvent() when dock widget is closed by user

        Qt5/Qt6 Compatible: Uses standard QTimer methods (isActive, stop).
        """
        try:
            self._is_active = False

            # NOTE: Layer Console and Marker Log cleanup removed
            # These widgets are now in the Mission Logs window

            # CRITICAL FIX: Disconnect mission controller signals (Issue #1.8)
            if hasattr(self, '_mission_controller_connections'):
                for signal, handler in list(self._mission_controller_connections):
                    try:
                        # CRITICAL FIX: Check if signal parent still exists before disconnect
                        parent = getattr(signal, '__self__', None)
                        if parent and isinstance(parent, QObject):
                            try:
                                _ = parent.objectName()
                            except (RuntimeError, AttributeError):
                                continue
                        signal.disconnect(handler)
                    except (TypeError, RuntimeError, AttributeError):
                        pass
                self._mission_controller_connections = []

            # CRITICAL: Restore hidden panels FIRST (Issue #3 fix)
            # If Focus Mode is active when plugin unloads, we must restore
            # all hidden dock widgets to return QGIS to its prior state
            if hasattr(self, '_restore_hidden_panels'):
                self._restore_hidden_panels()

            # Stop auto-refresh timer
            if hasattr(self, 'refresh_timer') and self.refresh_timer:
                if self.refresh_timer.isActive():
                    self.refresh_timer.stop()
                    print("[SARTRACKER] SARPanel: Stopped refresh_timer")

            if hasattr(self, 'pause_flash_timer') and self.pause_flash_timer:
                if self.pause_flash_timer.isActive():
                    self.pause_flash_timer.stop()

            # Stop autosave timer
            if hasattr(self, 'autosave_timer') and self.autosave_timer:
                if self.autosave_timer.isActive():
                    self.autosave_timer.stop()
                    print("[SARTRACKER] SARPanel: Stopped autosave_timer")

            print("[SARTRACKER] SARPanel: All timers stopped during cleanup")

        except Exception as e:
            # Don't let cleanup errors propagate - log and continue
            print(f"[SARTRACKER] Warning: Error during SARPanel cleanup: {e}")
            import traceback
            traceback.print_exc()

    def _set_feature_badge(self, label: QLabel, text: str, enabled: bool, color: str):
        """Apply consistent badge styling for feature indicators."""
        background = color if enabled else "#4d5563"
        label.setText(text)
        label.setStyleSheet(
            "QLabel {"
            f"  background-color: {background};"
            "  color: #fff;"
            "  padding: 4px 8px;"
            "  border-radius: 6px;"
            "  font-size: 10px;"
            "}"
        )

    def closeEvent(self, event):
        """
        Handle widget close event - stop timers and restore panels before closing.

        This ensures timers are stopped and Focus Mode is exited when user manually
        closes the dock widget (not just during plugin unload).

        Args:
            event: QCloseEvent from Qt

        Qt5/Qt6 Compatible: Standard Qt event handler.
        """
        # Stop all timers and restore panels before closing
        self.cleanup()

        # Call parent implementation to complete close
        super().closeEvent(event)

        print("[SARTRACKER] SARPanel: closeEvent handled, timers stopped")
