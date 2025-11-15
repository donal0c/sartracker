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
from qgis.PyQt.QtCore import QTimer, pyqtSignal, QSettings
from qgis.PyQt.QtGui import QColor, QFont
from datetime import datetime
from typing import Optional, List, Dict, Any

# Import Qt5/Qt6 compatible constants and functions
from ..utils.qt_compat import (
    LeftDockWidgetArea, RightDockWidgetArea, AlignRight
)
from ..utils.notify import info, warning, error
from ..config.keys import ConfigStore, SETTINGS_KEYS
from ..controllers.mission_controller import MissionState


class SARPanel(QDockWidget):
    """
    Main SAR tracking control panel.
    
    Signals:
        refresh_requested: Emitted when manual refresh requested
        csv_load_requested: Emitted when user wants to load CSV (file_path: str)
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

    # Phase N1: Provider signals removed - configuration moved to Settings Panel

    def __init__(self, parent=None, mission_controller=None):
        super().__init__("SAR Tracking", parent)
        
        self.setAllowedAreas(LeftDockWidgetArea | RightDockWidgetArea)
        
        # State
        self._mission_controller = mission_controller
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

        # Setup UI
        self._setup_ui()

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
            self._mission_controller.mission_state_changed.connect(self._on_controller_state_changed)
            self._mission_controller.mission_timing_updated.connect(self.update_mission_timers)
        
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
        self.focus_mode_button.setIcon(self.style().standardIcon(QStyle.SP_TitleBarMaxButton))
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
        self.start_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.start_button.clicked.connect(self._on_start_mission)
        controls_layout.addWidget(self.start_button)
        
        self.pause_button = QToolButton()
        self.pause_button.setText("Pause")
        self.pause_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
        self.pause_button.clicked.connect(self._on_pause_mission)
        self.pause_button.setEnabled(False)
        controls_layout.addWidget(self.pause_button)
        
        self.finish_button = QToolButton()
        self.finish_button.setText("Finish")
        self.finish_button.setIcon(self.style().standardIcon(QStyle.SP_DialogCloseButton))
        self.finish_button.clicked.connect(self._on_finish_mission)
        self.finish_button.setEnabled(False)
        controls_layout.addWidget(self.finish_button)
        
        mission_layout.addLayout(controls_layout)
        self._apply_mission_button_styles()

        badge_layout = QHBoxLayout()
        self.auto_refresh_status_label = QLabel("Auto Refresh: OFF")
        self.autosave_status_label = QLabel("Auto Save: OFF")
        badge_layout.addWidget(self.auto_refresh_status_label)
        badge_layout.addWidget(self.autosave_status_label)
        badge_layout.addStretch()
        mission_layout.addLayout(badge_layout)
        mission_group.setLayout(mission_layout)
        layout.addWidget(mission_group)
        
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
        self.gpx_import_button.setEnabled(False)  # Disabled until implemented
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

        mission_name = self.mission_name_input.text().strip()
        if not mission_name:
            mission_name = f"Mission {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            self.mission_name_input.setText(mission_name)

        try:
            self._mission_controller.start_mission(mission_name)
        except ValueError as exc:
            QMessageBox.warning(self, "Mission Control", str(exc))
        except RuntimeError as exc:
            QMessageBox.information(self, "Mission Control", str(exc))
        
    def _on_pause_mission(self):
        """Handle pause/resume button click."""
        if not self._mission_controller:
            return

        if self._mission_state == MissionState.PAUSED:
            self._mission_controller.resume_mission()
        else:
            self._mission_controller.pause_mission()
        
    def _on_finish_mission(self):
        """Handle finish mission button click."""
        if not self._mission_controller:
            return

        confirm = QMessageBox.question(
            self,
            "Finish Mission",
            "Are you sure you want to finish this mission?\n\n"
            "This will reset timers and deactivate mission controls.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if confirm != QMessageBox.Yes:
            return

        self._mission_controller.finish_mission()
        
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
            self.pause_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
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
            self.pause_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
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
            self.pause_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
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
        self._pause_flash = not self._pause_flash
        self._set_button_state(self.pause_button, "flashOn", self._pause_flash)

    def _format_seconds(self, seconds: float) -> str:
        total = max(0, int(seconds or 0))
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
        self._set_button_state(self.start_button, "state", "idle")
        self._set_button_state(self.pause_button, "state", "pause")
        self._set_button_state(self.pause_button, "flashOn", False)
        self._set_button_state(self.finish_button, "state", "idle")

    def _apply_focus_mode_style(self):
        """Update focus mode button styling."""
        if not hasattr(self, 'focus_mode_button') or not self.focus_mode_button:
            return
        if self.focus_mode_active:
            self.focus_mode_button.setStyleSheet(
                "QToolButton { background-color: #4066d6; color: #ffffff; padding: 6px 12px; border-radius: 4px; }"
            )
        else:
            self.focus_mode_button.setStyleSheet(
                "QToolButton { padding: 6px 12px; border-radius: 4px; }"
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
    
    def _on_auto_refresh(self):
        """Handle auto-refresh timer."""
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
        
        for device in devices:
            device_id = device.get('device_id', 'Unknown')
            status = device.get('status', 'unknown')
            last_update = device.get('last_update', 'Never')
            
            # Format display text
            text = f"{device_id}"
            if status == 'online':
                text = f"🟢 {text}"
            elif status == 'offline':
                text = f"🔴 {text}"
            else:
                text = f"⚪ {text}"
            
            text += f"\n  Last: {last_update}"
            
            item = QListWidgetItem(text)
            self.devices_list.addItem(item)
    
    def set_data_source(self, source_info: str):
        """
        Update data source label.

        Args:
            source_info: Description of current data source
        """
        self.data_source_label.setText(f"Source: {source_info}")

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

        Qt5/Qt6 Compatible: Uses QLabel.setText().
        """
        provider = status_dict.get('provider', 'None')
        state = status_dict.get('state', 'unknown')
        message = status_dict.get('message', '')
        devices_count = status_dict.get('devices_count', 0)
        last_refresh = status_dict.get('last_refresh', 'Never')
        poll_active = status_dict.get('poll_active', False)

        # Format last refresh time
        if last_refresh and last_refresh != 'Never':
            try:
                # Extract time component from ISO timestamp
                last_refresh = last_refresh.split('T')[1][:8] if 'T' in last_refresh else last_refresh
            except:
                pass

        # Format status text
        status_parts = [f"Provider: {provider}"]
        status_parts.append(f"Devices: {devices_count}")
        if last_refresh != 'Never':
            status_parts.append(f"Last Refresh: {last_refresh}")
        if poll_active:
            status_parts.append("🔄 Polling")

        # Add state indicator
        if state == 'ok':
            status_parts.append("✓ Connected")
        elif state == 'error':
            status_parts.append("✗ Error")
        elif state == 'testing':
            status_parts.append("⏳ Testing...")
        elif state == 'connecting':
            status_parts.append("⏳ Connecting...")

        status_text = " | ".join(status_parts)
        self.provider_status_label.setText(status_text)

        # Update label background color based on state
        if state == 'ok':
            bg_color = "#d4edda"  # Light green
        elif state == 'error':
            bg_color = "#f8d7da"  # Light red
        elif state in ('testing', 'connecting'):
            bg_color = "#fff3cd"  # Light yellow
        else:
            bg_color = "#f0f0f0"  # Light gray

        self.provider_status_label.setStyleSheet(
            f"QLabel {{ "
            f"  padding: 4px; "
            f"  background-color: {bg_color}; "
            f"  border: 1px solid #ccc; "
            f"  border-radius: 3px; "
            f"  font-size: 10px; "
            f"}}"
        )

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
                restored = 0
                for panel in self.hidden_panels:
                    panel.setVisible(True)
                    restored += 1

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
