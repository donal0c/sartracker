# -*- coding: utf-8 -*-
"""
SAR Panel UI

Main docked control panel for SAR tracking operations.
"""

from qgis.PyQt.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QListWidget, QListWidgetItem,
    QGroupBox, QSpinBox, QCheckBox, QFileDialog, QLineEdit,
    QScrollArea
)
from qgis.PyQt.QtCore import QTimer, pyqtSignal, QSettings
from qgis.PyQt.QtGui import QColor
from datetime import datetime
from typing import Optional, List, Dict

# Import Qt5/Qt6 compatible constants
from ..utils.qt_compat import (
    LeftDockWidgetArea, RightDockWidgetArea,
    Checked
)


class SARPanel(QDockWidget):
    """
    Main SAR tracking control panel.
    
    Signals:
        mission_started: Emitted when mission starts (mission_name: str)
        mission_paused: Emitted when mission pauses
        mission_resumed: Emitted when mission resumes
        mission_finished: Emitted when mission finishes
        refresh_requested: Emitted when manual refresh requested
        csv_load_requested: Emitted when user wants to load CSV (file_path: str)
    """
    
    mission_started = pyqtSignal(str)  # mission_name
    mission_paused = pyqtSignal()
    mission_resumed = pyqtSignal()
    mission_finished = pyqtSignal()
    refresh_requested = pyqtSignal()
    csv_load_requested = pyqtSignal(str)  # file_path
    add_poi_requested = pyqtSignal()
    add_casualty_requested = pyqtSignal()
    add_hazard_requested = pyqtSignal()
    line_tool_requested = pyqtSignal()
    range_rings_tool_requested = pyqtSignal()
    coordinate_converter_requested = pyqtSignal()
    measure_distance_requested = pyqtSignal()
    autosave_requested = pyqtSignal()  # Request to save project
    
    def __init__(self, parent=None):
        super().__init__("SAR Tracking", parent)
        
        self.setAllowedAreas(LeftDockWidgetArea | RightDockWidgetArea)
        
        # State
        self.mission_active = False
        self.is_paused = False  # Renamed to avoid shadowing the signal
        self.mission_start_time = None
        self.auto_refresh_enabled = False
        self.autosave_enabled = False
        self.last_autosave_time = None
        self.focus_mode_active = False
        self.hidden_panels = []  # Track which panels we hid

        # Setup UI
        self._setup_ui()

        # Setup auto-refresh timer
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self._on_auto_refresh)

        # Setup UI update timer (updates elapsed time every second)
        self.ui_update_timer = QTimer()
        self.ui_update_timer.timeout.connect(self._update_mission_status)
        self.ui_update_timer.start(1000)  # Update every second

        # Setup auto-save timer
        self.autosave_timer = QTimer()
        self.autosave_timer.timeout.connect(self._on_autosave)
        
    def _setup_ui(self):
        """Build the panel UI."""
        main_widget = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # Focus Mode Toggle (at top)
        focus_layout = QHBoxLayout()
        self.focus_mode_button = QPushButton("Enter Focus Mode")
        self.focus_mode_button.setToolTip(
            "Hide other QGIS panels for cleaner workspace.\n"
            "Press F11 for full-screen mode."
        )
        self.focus_mode_button.clicked.connect(self._toggle_focus_mode)
        focus_layout.addWidget(self.focus_mode_button)
        layout.addLayout(focus_layout)

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
        
        # Mission time
        self.mission_time_label = QLabel("Elapsed: --:--:--")
        mission_layout.addWidget(self.mission_time_label)
        
        # Mission controls
        controls_layout = QHBoxLayout()
        
        self.start_button = QPushButton("Start Mission")
        self.start_button.clicked.connect(self._on_start_mission)
        controls_layout.addWidget(self.start_button)
        
        self.pause_button = QPushButton("Pause")
        self.pause_button.clicked.connect(self._on_pause_mission)
        self.pause_button.setEnabled(False)
        controls_layout.addWidget(self.pause_button)
        
        self.finish_button = QPushButton("Finish")
        self.finish_button.clicked.connect(self._on_finish_mission)
        self.finish_button.setEnabled(False)
        controls_layout.addWidget(self.finish_button)
        
        mission_layout.addLayout(controls_layout)
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
        
        # Auto-Refresh Section
        refresh_group = QGroupBox("Auto-Refresh")
        refresh_layout = QVBoxLayout()
        
        # Enable/disable checkbox
        self.auto_refresh_checkbox = QCheckBox("Enable auto-refresh")
        self.auto_refresh_checkbox.stateChanged.connect(self._on_auto_refresh_toggled)
        refresh_layout.addWidget(self.auto_refresh_checkbox)
        
        # Interval setting
        interval_layout = QHBoxLayout()
        interval_layout.addWidget(QLabel("Interval (seconds):"))
        self.refresh_interval_spin = QSpinBox()
        self.refresh_interval_spin.setMinimum(5)
        self.refresh_interval_spin.setMaximum(300)
        self.refresh_interval_spin.setValue(30)
        self.refresh_interval_spin.valueChanged.connect(self._on_interval_changed)
        interval_layout.addWidget(self.refresh_interval_spin)
        refresh_layout.addLayout(interval_layout)
        
        # Manual refresh button
        self.refresh_button = QPushButton("Refresh Now")
        self.refresh_button.clicked.connect(self._on_manual_refresh)
        refresh_layout.addWidget(self.refresh_button)
        
        refresh_group.setLayout(refresh_layout)
        layout.addWidget(refresh_group)

        # Auto-Save Section
        autosave_group = QGroupBox("Auto-Save")
        autosave_layout = QVBoxLayout()

        # Enable/disable checkbox
        self.autosave_checkbox = QCheckBox("Enable auto-save")
        self.autosave_checkbox.stateChanged.connect(self._on_autosave_toggled)
        autosave_layout.addWidget(self.autosave_checkbox)

        # Interval setting
        save_interval_layout = QHBoxLayout()
        save_interval_layout.addWidget(QLabel("Interval (minutes):"))
        self.autosave_interval_spin = QSpinBox()
        self.autosave_interval_spin.setMinimum(1)
        self.autosave_interval_spin.setMaximum(60)
        self.autosave_interval_spin.setValue(5)
        self.autosave_interval_spin.valueChanged.connect(self._on_autosave_interval_changed)
        save_interval_layout.addWidget(self.autosave_interval_spin)
        autosave_layout.addLayout(save_interval_layout)

        # Last save time
        self.autosave_status_label = QLabel("Last save: Never")
        self.autosave_status_label.setStyleSheet("QLabel { color: #666; font-size: 10px; }")
        autosave_layout.addWidget(self.autosave_status_label)

        # Manual save button
        self.save_now_button = QPushButton("Save Project Now")
        self.save_now_button.clicked.connect(self._on_manual_save)
        autosave_layout.addWidget(self.save_now_button)

        autosave_group.setLayout(autosave_layout)
        layout.addWidget(autosave_group)

        # Data Source Section
        data_group = QGroupBox("Data Source")
        data_layout = QVBoxLayout()
        
        self.load_csv_button = QPushButton("Load CSV File...")
        self.load_csv_button.clicked.connect(self._on_load_csv)
        data_layout.addWidget(self.load_csv_button)
        
        self.data_source_label = QLabel("Source: None")
        self.data_source_label.setWordWrap(True)
        data_layout.addWidget(self.data_source_label)
        
        data_group.setLayout(data_layout)
        layout.addWidget(data_group)

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
        self.add_clue_button.clicked.connect(self._on_add_casualty)
        markers_grid.addWidget(self.add_clue_button, 0, 1)

        self.add_hazard_button = QPushButton("Hazard")
        self.add_hazard_button.setToolTip(
            "Mark safety hazards on the map:\n"
            "Cliffs, water hazards, bogs, dense vegetation, etc."
        )
        self.add_hazard_button.clicked.connect(self._on_add_hazard)
        markers_grid.addWidget(self.add_hazard_button, 1, 0)

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
        self.search_area_button.setToolTip("Draw polygon search areas with status tracking")
        self.search_area_button.setEnabled(False)  # Disabled until implemented
        drawing_grid.addWidget(self.search_area_button, 0, 1)

        self.range_rings_button = QPushButton("Range Rings")
        self.range_rings_button.setToolTip("Create distance circles (LPB-based or custom)")
        self.range_rings_button.clicked.connect(self._on_range_rings_tool)
        drawing_grid.addWidget(self.range_rings_button, 1, 0)

        self.bearing_line_button = QPushButton("Bearing Line")
        self.bearing_line_button.setToolTip("Draw azimuth/bearing lines for direction finding")
        self.bearing_line_button.setEnabled(False)  # Disabled until implemented
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
        mission_name = self.mission_name_input.text().strip()
        if not mission_name:
            mission_name = f"Mission {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            self.mission_name_input.setText(mission_name)
        
        self.mission_active = True
        self.is_paused = False
        self.mission_start_time = datetime.now()

        self._update_mission_status()
        self.mission_started.emit(mission_name)
        
    def _on_pause_mission(self):
        """Handle pause/resume button click."""
        if self.is_paused:
            # Resume
            self.is_paused = False
            self.pause_button.setText("Pause")
            self.mission_resumed.emit()
        else:
            # Pause
            self.is_paused = True
            self.pause_button.setText("Resume")
            self.mission_paused.emit()

        self._update_mission_status()
        self.save_mission_state()  # Save state for auto-resume
        
    def _on_finish_mission(self):
        """Handle finish mission button click."""
        self.mission_active = False
        self.is_paused = False
        self.mission_start_time = None

        self._update_mission_status()
        self.save_mission_state()  # Clear saved state
        self.mission_finished.emit()
        
    def _update_mission_status(self):
        """Update mission status UI."""
        if not self.mission_active:
            self.mission_status_label.setText("Status: <b>No active mission</b>")
            self.mission_time_label.setText("Elapsed: --:--:--")
            self.start_button.setEnabled(True)
            self.pause_button.setEnabled(False)
            self.finish_button.setEnabled(False)
            self.mission_name_input.setEnabled(True)
        else:
            if self.is_paused:
                status = "Status: <b style='color: orange;'>Paused</b>"
            else:
                status = "Status: <b style='color: green;'>Active</b>"
            self.mission_status_label.setText(status)
            
            self.start_button.setEnabled(False)
            self.pause_button.setEnabled(True)
            self.finish_button.setEnabled(True)
            self.mission_name_input.setEnabled(False)
            
            # Update elapsed time
            if self.mission_start_time:
                elapsed = datetime.now() - self.mission_start_time
                hours, remainder = divmod(int(elapsed.total_seconds()), 3600)
                minutes, seconds = divmod(remainder, 60)
                self.mission_time_label.setText(f"Elapsed: {hours:02d}:{minutes:02d}:{seconds:02d}")
    
    def _on_auto_refresh_toggled(self, state):
        """Handle auto-refresh checkbox toggle."""
        self.auto_refresh_enabled = (state == Checked)
        
        if self.auto_refresh_enabled:
            interval_ms = self.refresh_interval_spin.value() * 1000
            self.refresh_timer.start(interval_ms)
        else:
            self.refresh_timer.stop()
    
    def _on_interval_changed(self, value):
        """Handle refresh interval change."""
        if self.auto_refresh_enabled:
            self.refresh_timer.stop()
            self.refresh_timer.start(value * 1000)
    
    def _on_auto_refresh(self):
        """Handle auto-refresh timer."""
        # Only refresh if mission is active and not paused, OR if no mission is active
        if not self.mission_active or (self.mission_active and not self.is_paused):
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

    def _on_add_poi(self):
        """Handle Add POI button click."""
        self.add_poi_requested.emit()

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

    def _on_line_tool(self):
        """Handle Line Tool button click."""
        self.line_tool_requested.emit()

    def _on_range_rings_tool(self):
        """Handle Range Rings Tool button click."""
        self.range_rings_tool_requested.emit()

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

    def _on_autosave_toggled(self, state):
        """Handle auto-save checkbox toggle."""
        self.autosave_enabled = (state == Checked)

        if self.autosave_enabled:
            interval_ms = self.autosave_interval_spin.value() * 60 * 1000  # Convert minutes to ms
            self.autosave_timer.start(interval_ms)
        else:
            self.autosave_timer.stop()

    def _on_autosave_interval_changed(self, value):
        """Handle auto-save interval change."""
        if self.autosave_enabled:
            self.autosave_timer.stop()
            self.autosave_timer.start(value * 60 * 1000)  # Convert minutes to ms

    def _on_autosave(self):
        """Handle auto-save timer - request project save."""
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
        time_str = self.last_autosave_time.strftime("%H:%M:%S")

        if success:
            self.autosave_status_label.setText(f"Last save: {time_str} ✓")
            self.autosave_status_label.setStyleSheet("QLabel { color: #0a0; font-size: 10px; }")
        else:
            self.autosave_status_label.setText(f"Last save: {time_str} ✗ Failed")
            self.autosave_status_label.setStyleSheet("QLabel { color: #d00; font-size: 10px; }")

    def save_mission_state(self):
        """Save current mission state to QSettings for auto-resume."""
        settings = QSettings()

        if self.mission_active and self.is_paused:
            # Save paused mission state
            settings.setValue("SAR_Tracker/mission_paused", True)
            settings.setValue("SAR_Tracker/mission_name", self.mission_name_input.text())
            settings.setValue("SAR_Tracker/mission_start_time", self.mission_start_time.isoformat())
        else:
            # Clear paused mission state
            settings.remove("SAR_Tracker/mission_paused")
            settings.remove("SAR_Tracker/mission_name")
            settings.remove("SAR_Tracker/mission_start_time")

    def load_mission_state(self):
        """
        Load mission state from QSettings for auto-resume.

        Returns:
            dict or None: Mission state if exists, None otherwise
        """
        settings = QSettings()

        if settings.value("SAR_Tracker/mission_paused", False, bool):
            return {
                'name': settings.value("SAR_Tracker/mission_name", ""),
                'start_time': settings.value("SAR_Tracker/mission_start_time", "")
            }

        return None

    def restore_mission_state(self, state: dict):
        """
        Restore mission from saved state.

        Args:
            state: Mission state dict from load_mission_state()
        """
        self.mission_name_input.setText(state['name'])
        self.mission_start_time = datetime.fromisoformat(state['start_time'])
        self.mission_active = True
        self.is_paused = True
        self.pause_button.setText("Resume")
        self._update_mission_status()

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
                self.focus_mode_button.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; }")
                self.focus_mode_active = True

                # Show message
                from qgis.core import Qgis
                iface.messageBar().pushMessage(
                    "Focus Mode",
                    f"Focus Mode enabled - {len(self.hidden_panels)} panels hidden. Click 'Exit Focus Mode' to restore.",
                    level=Qgis.Info,
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
                self.focus_mode_button.setStyleSheet("")
                self.focus_mode_active = False

                # Show message
                from qgis.core import Qgis
                iface.messageBar().pushMessage(
                    "Focus Mode",
                    f"Focus Mode disabled - {restored} panels restored.",
                    level=Qgis.Info,
                    duration=2
                )

        except Exception as e:
            # Fail gracefully - focus mode is optional
            print(f"Focus mode toggle failed: {e}")
            from qgis.core import Qgis
            from qgis.utils import iface
            iface.messageBar().pushMessage(
                "Focus Mode Error",
                f"Could not toggle Focus Mode: {e}",
                level=Qgis.Warning,
                duration=3
            )
