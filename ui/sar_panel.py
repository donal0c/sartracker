# -*- coding: utf-8 -*-
"""
SAR Panel UI

Main docked control panel for SAR tracking operations.
"""

from qgis.PyQt.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QListWidget, QListWidgetItem,
    QGroupBox, QSpinBox, QCheckBox, QFileDialog, QLineEdit
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

        # Map Tools Section
        tools_group = QGroupBox("Map Tools")
        tools_layout = QVBoxLayout()

        self.add_poi_button = QPushButton("Add Point of Interest (POI)")
        self.add_poi_button.clicked.connect(self._on_add_poi)
        tools_layout.addWidget(self.add_poi_button)

        self.add_casualty_button = QPushButton("Add Casualty")
        self.add_casualty_button.clicked.connect(self._on_add_casualty)
        tools_layout.addWidget(self.add_casualty_button)

        self.coord_converter_button = QPushButton("Coordinate Converter")
        self.coord_converter_button.clicked.connect(self._on_coordinate_converter)
        tools_layout.addWidget(self.coord_converter_button)

        self.measure_button = QPushButton("Measure Distance & Bearing")
        self.measure_button.clicked.connect(self._on_measure_distance)
        tools_layout.addWidget(self.measure_button)

        tools_group.setLayout(tools_layout)
        layout.addWidget(tools_group)

        # Spacer
        layout.addStretch()
        
        main_widget.setLayout(layout)
        self.setWidget(main_widget)
        
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

    def _on_coordinate_converter(self):
        """Handle Coordinate Converter button click."""
        self.coordinate_converter_requested.emit()

    def _on_measure_distance(self):
        """Handle Measure Distance button click."""
        self.measure_distance_requested.emit()

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
